#!/usr/bin/env python3
"""
sentinel/pre_arm_gate.py — DISPATCH 114 PRE-ARM · the automated ARM / DO-NOT-ARM decision

Step 4. Reads the shadow forward ledger (>=10 sessions) and returns ARM only if ALL four
hard criteria hold:
  1. shadow fires <= 3/day        (every session)
  2. zero fires outside the window (09:35-11:30 / 14:00-15:15 ET)
  3. zero duplicate levels         (debounce held: no two qualified fires same session,
                                    same setup, within +/-3pts)
  4. no obvious 8/3-style trend-fighting shorts among the qualified set:
       - a qualified SHORT with ADD_slope >= 0 (fighting a rising tape), OR
       - a qualified SHORT logged on a TREND_UP day, OR
       - >= 2 qualified SHORTs in one session at ASCENDING levels (the 8/3 signature)

Minimum 10 distinct shadow sessions; fewer => NOT-READY (keep accruing). Writes a verdict
JSON. This makes the arming call mechanical, not a judgement call at the end of ten days.

Usage:
  python3 sentinel/pre_arm_gate.py                       # reads ledgers/sentinel_forward.csv
  python3 sentinel/pre_arm_gate.py --ledger PATH --out sentinel_prearm_verdict.json
  python3 sentinel/pre_arm_gate.py --selftest
"""
from __future__ import annotations
from typing import List, Dict
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ledger as L  # noqa: E402
from sentinel import WINDOWS_ET, _hhmm_to_min, LEVEL_TOL_PTS, MAX_QUALIFIED_PER_DAY  # noqa: E402

MIN_SESSIONS = 10
MAX_FIRES_PER_DAY = 3  # the arming ceiling (stricter than the engine's daily cap of 2? no —
#                        the daily cap is 2; 3/day is the shadow acceptance ceiling incl. any
#                        cap edge. A clean run should sit at or under the cap.)
DEFAULT_OUT = os.path.join(L.ROOT, "sentinel_prearm_verdict.json")


def _in_window(hhmm: str) -> bool:
    t = _hhmm_to_min(hhmm)
    return any(_hhmm_to_min(lo) <= t <= _hhmm_to_min(hi) for lo, hi in WINDOWS_ET)


def evaluate(rows: List[Dict]) -> Dict:
    qualified = [r for r in rows if r.get("qualified") == "Y"]
    sessions = sorted({r["date"] for r in rows})
    n_sessions = len(sessions)

    # criterion 1 — fires per day
    per_day: Dict[str, int] = {}
    for r in qualified:
        per_day[r["date"]] = per_day.get(r["date"], 0) + 1
    over_cap = {d: c for d, c in per_day.items() if c > MAX_FIRES_PER_DAY}
    c1 = len(over_cap) == 0

    # criterion 2 — off-window fires
    off_window = [f'{r["date"]} {r["ts"]}' for r in qualified if not _in_window(r["ts"])]
    c2 = len(off_window) == 0

    # criterion 3 — duplicate levels within a session
    dup = []
    by_session: Dict[str, List[Dict]] = {}
    for r in qualified:
        by_session.setdefault(r["date"], []).append(r)
    for date, rs in by_session.items():
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)):
                if rs[i]["setup"] == rs[j]["setup"] and \
                   abs(float(rs[i]["level"]) - float(rs[j]["level"])) <= LEVEL_TOL_PTS:
                    dup.append(f'{date} {rs[i]["setup"]} {rs[i]["level"]}/{rs[j]["level"]}')
    c3 = len(dup) == 0

    # criterion 4 — trend-fighting shorts
    tf = []
    shorts_by_session: Dict[str, List[Dict]] = {}
    for r in qualified:
        if r["dir"] != "SHORT":
            continue
        shorts_by_session.setdefault(r["date"], []).append(r)
        add_slope = r.get("add_slope")
        try:
            asl = float(add_slope) if add_slope not in ("", None) else None
        except ValueError:
            asl = None
        if asl is not None and asl >= 0:
            tf.append(f'{r["date"]} {r["ts"]} SHORT ADD_slope={asl} (rising tape)')
        if (r.get("day_type") or "").upper() == "TREND_UP":
            tf.append(f'{r["date"]} {r["ts"]} SHORT on TREND_UP day')
    # ascending-shorts signature
    for date, rs in shorts_by_session.items():
        rs_sorted = sorted(rs, key=lambda r: r["ts"])
        levels = [float(r["level"]) for r in rs_sorted]
        if len(levels) >= 2 and all(levels[k] < levels[k + 1] for k in range(len(levels) - 1)):
            tf.append(f'{date} {len(levels)} ascending SHORTs {levels} (8/3 signature)')
    c4 = len(tf) == 0

    ready = n_sessions >= MIN_SESSIONS
    all_pass = c1 and c2 and c3 and c4
    if not ready:
        verdict = "NOT-READY"
    elif all_pass:
        verdict = "ARM"
    else:
        verdict = "DO-NOT-ARM"

    return {
        "schema": "sentinel_prearm_verdict/1",
        "dispatch": 114,
        "verdict": verdict,
        "n_sessions": n_sessions,
        "min_sessions": MIN_SESSIONS,
        "n_qualified": len(qualified),
        "n_rows": len(rows),
        "criteria": {
            "1_fires_per_day_le_3": {"pass": c1, "max_per_day": MAX_FIRES_PER_DAY,
                                     "per_day": per_day, "over_cap": over_cap},
            "2_zero_off_window": {"pass": c2, "off_window": off_window},
            "3_zero_duplicate_levels": {"pass": c3, "duplicates": dup},
            "4_no_trend_fighting_shorts": {"pass": c4, "flags": tf},
        },
        "note": "ARM only on all-four-pass AND >=10 sessions. Any DO-NOT-ARM flag is a "
                "blocker — fix the gate or the setup, re-shadow, re-evaluate. "
                "Arming (the launchd plist) stays a private-tree step even on ARM.",
    }


def run(ledger_path: str, out_path: str) -> int:
    rows = L.read_ledger(ledger_path)
    v = evaluate(rows)
    with open(out_path, "w") as fh:
        json.dump(v, fh, indent=2)
    print(f"SENTINEL D114 PRE-ARM gate  =>  {v['verdict']}")
    print(f"  sessions {v['n_sessions']}/{v['min_sessions']}   qualified {v['n_qualified']}")
    for k, c in v["criteria"].items():
        print(f"  [{'PASS' if c['pass'] else 'FAIL'}] {k}")
        for kk, vv in c.items():
            if kk != "pass" and vv:
                print(f"        {kk}: {vv}")
    print(f"  verdict written -> {out_path}")
    return 0 if v["verdict"] == "ARM" else (0 if v["verdict"] == "NOT-READY" else 1)


# ── self-test ────────────────────────────────────────────────────────────────
def _mkrow(date, ts, setup, dirn, level, qualified="Y", add_slope="", day_type="TREND_DOWN"):
    return {**{k: "" for k in L.FIELDS}, "ts": ts, "date": date, "setup": setup,
            "dir": dirn, "level": level, "entry": level, "stop": level + 10,
            "t1": level - 15, "t2": level - 27, "add_slope": add_slope,
            "qualified": qualified, "suppression_reason": "" if qualified == "Y" else "WINDOW",
            "day_type": day_type}


def _selftest() -> int:
    fails = 0

    def check(name, cond):
        nonlocal fails
        print(f"  {'PASS' if cond else 'FAIL'}  {name}")
        if not cond:
            fails += 1

    # clean 10-session run: 1 qualified short/day, in-window, ADD falling, trend-down => ARM
    clean = []
    for i in range(10):
        d = f"2026-08-{11 + i:02d}"
        clean.append(_mkrow(d, "10:30", "Cluster Fade", "SHORT", 7600 - i, add_slope="-15.0"))
    v = evaluate(clean)
    check("clean 10 sessions => ARM", v["verdict"] == "ARM")

    # < 10 sessions => NOT-READY
    check("3 sessions => NOT-READY", evaluate(clean[:3])["verdict"] == "NOT-READY")

    # off-window fire => DO-NOT-ARM
    off = list(clean) + [_mkrow("2026-08-11", "09:32", "Cluster Fade", "SHORT", 7500,
                                add_slope="-15.0")]
    v = evaluate(off)
    check("off-window => DO-NOT-ARM", v["verdict"] == "DO-NOT-ARM" and
          not v["criteria"]["2_zero_off_window"]["pass"])

    # 8/3-style: 3 ascending shorts in one session, ADD rising, TREND_UP => DO-NOT-ARM
    bad = []
    for i in range(10):
        bad.append(_mkrow(f"2026-09-{1 + i:02d}", "10:30", "Cluster Fade", "SHORT", 7600))
    bad += [_mkrow("2026-09-01", "11:05", "Cluster Fade", "SHORT", 7610, add_slope="31.0",
                   day_type="TREND_UP"),
            _mkrow("2026-09-01", "11:26", "Cluster Fade", "SHORT", 7620, add_slope="31.0",
                   day_type="TREND_UP")]
    v = evaluate(bad)
    check("ascending/ADD-rising/TREND_UP shorts => DO-NOT-ARM",
          v["verdict"] == "DO-NOT-ARM" and not v["criteria"]["4_no_trend_fighting_shorts"]["pass"])
    check("trend-fight flags populated",
          len(v["criteria"]["4_no_trend_fighting_shorts"]["flags"]) >= 2)

    # duplicate level => DO-NOT-ARM
    dup = list(clean) + [_mkrow("2026-08-11", "10:45", "Cluster Fade", "SHORT", 7600.0,
                                add_slope="-15.0")]
    # note 2026-08-11 already has 7600 at 10:30 => duplicate within +/-3, also 2/day (ok<=3)
    v = evaluate(dup)
    check("duplicate level => DO-NOT-ARM",
          not v["criteria"]["3_zero_duplicate_levels"]["pass"])

    # >3 fires/day => DO-NOT-ARM
    flood = list(clean)
    for k in range(4):
        flood.append(_mkrow("2026-08-11", f"10:{10 + k}", "Cluster Fade", "SHORT",
                            7580 - k * 5, add_slope="-15.0"))
    v = evaluate(flood)
    check(">3 fires/day => DO-NOT-ARM", not v["criteria"]["1_fires_per_day_le_3"]["pass"])

    print(f"\npre_arm_gate self-test: {'ALL PASS' if fails == 0 else str(fails) + ' FAILED'}")
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", default=L.LEDGER_CSV)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(1 if _selftest() else 0)
    sys.exit(run(a.ledger, a.out))


if __name__ == "__main__":
    main()
