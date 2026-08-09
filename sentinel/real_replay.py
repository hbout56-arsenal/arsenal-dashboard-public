#!/usr/bin/env python3
"""
sentinel/real_replay.py — DISPATCH 114 PRE-ARM · re-run tests A-F on REAL archived internals

[MAC-LOCAL] This is step 1 of pre-arm validation. It reads the collector's REAL archived
internals rows (internals_live.csv — schema matches internals_snapshot.json: ts, add, vold,
trin, tick, ...), slices the trailing 30x1-min window at each event time, builds Internals
from REAL rows, and re-runs the frozen qualifier for the six acceptance events. It reports
pass/fail per test with the ACTUAL gate values computed from real rows and FLAGS any
divergence from the reconstructed-fixture run.

This CANNOT run in the cloud public repo (the raw July/August internals rows are not
mirrored — only a per-date archived flag is). Run it on the Mac where internals_live.csv
lives. The self-test below proves the harness mechanics against a synthetic CSV.

Usage:
  python3 sentinel/real_replay.py --csv /path/to/internals_live.csv
  python3 sentinel/real_replay.py --selftest        # synthetic-CSV mechanics proof
"""
from __future__ import annotations
from typing import List, Dict, Optional
import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sentinel import Candidate, Internals, SessionState, qualify, FULL_ROWS  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
EVENTS_PATH = os.path.join(HERE, "pre_arm_events.json")

# collector CSV column names (from internals_snapshot.json rows)
COL_TS = "ts"           # "YYYY-MM-DDTHH:MM:SS"
COL_ADD = "add"
COL_VOLD = "vold"
COL_TRIN = "trin"
COL_TICK = "tick"


def _f(x) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def load_rows(csv_path: str) -> List[Dict]:
    """Read internals_live.csv into typed rows (ts str + add/vold/trin/tick floats)."""
    rows = []
    with open(csv_path, newline="") as fh:
        for r in csv.DictReader(fh):
            ts = r.get(COL_TS) or r.get("timestamp") or ""
            rows.append({
                "ts": ts,
                "date": ts[:10],
                "hhmm": ts[11:16],
                "add": _f(r.get(COL_ADD)),
                "vold": _f(r.get(COL_VOLD)),
                "trin": _f(r.get(COL_TRIN)),
                "tick": _f(r.get(COL_TICK)),
            })
    return rows


def window_slice(rows: List[Dict], date: str, hhmm: str, n: int = FULL_ROWS) -> List[Dict]:
    """The last n rows on `date` at or before hhmm (oldest first)."""
    def keyok(r):
        return r["date"] == date and r["hhmm"] <= hhmm and None not in (
            r["add"], r["vold"], r["trin"])
    day = [r for r in rows if keyok(r)]
    day.sort(key=lambda r: r["hhmm"])
    return day[-n:]


def internals_from_rows(win: List[Dict], feed_age_s: float = 60.0) -> Internals:
    return Internals(
        add=[r["add"] for r in win],
        vold=[r["vold"] for r in win],
        trin=[r["trin"] for r in win],
        tick=[r["tick"] for r in win if r["tick"] is not None],
        feed_age_s=feed_age_s,
    )


def _candidate(ev: Dict, ts_et: str, intern: Internals) -> Candidate:
    return Candidate(
        ts_et=ts_et, date=ev["date"], setup=ev["setup"], direction=ev["direction"],
        level=ev["level"], level_name=ev["level_name"], entry=ev["entry"], stop=ev["stop"],
        t1=ev["t1"], t2=ev["t2"], invalidating_extreme=ev["invalidating_extreme"],
        atr5m=ev["atr5m"], internals=intern,
        pool_tagged=ev.get("pool_tagged", False),
        rejected_within_bars=ev.get("rejected_within_bars"),
        aligned=ev.get("aligned"),
    )


def _sign(x: Optional[float]) -> str:
    if x is None:
        return "?"
    return "+" if x > 0 else ("-" if x < 0 else "0")


def run(csv_path: str) -> int:
    with open(EVENTS_PATH) as fh:
        spec = json.load(fh)
    rows = load_rows(csv_path)
    signs = spec.get("expected_slope_signs_from_evidence", {})

    print("SENTINEL D114 PRE-ARM · real-rows replay")
    print(f"  csv: {csv_path}   rows: {len(rows)}")
    print("=" * 72)
    fails = 0
    diverged = 0
    # one session per date so debounce/cap behave as they would live
    sessions: Dict[str, SessionState] = {}
    # evaluate in dispatch order by test label
    for ev in sorted(spec["events"], key=lambda e: e["test"]):
        date, ts = ev["date"], ev["ts_et"]
        win = window_slice(rows, date, ts)
        if len(win) < 2:
            print(f"  {ev['test']} {date} {ts}: NO REAL ROWS in window "
                  f"(have {len(win)}) — cannot validate. [BLOCKED]")
            fails += 1
            continue
        intern = internals_from_rows(win)
        sess = sessions.setdefault(date, SessionState(date=date))
        d = qualify(_candidate(ev, ts, intern), sess)

        emit = d.emit_email()
        exp_emit = ev.get("expect_emit")
        # verdict check
        ok = True
        if exp_emit is not None:
            ok = (emit == exp_emit)
        if "expect_reason" in ev and not emit:
            ok = ok and (d.reason == ev["expect_reason"])
        if "expect_reason_prefix" in ev and not emit:
            ok = ok and d.reason.startswith(ev["expect_reason_prefix"])

        # in-window probe (isolate the slope gate for off-window fades)
        probe_note = ""
        if ev.get("in_window_probe_ts"):
            pintern = internals_from_rows(window_slice(rows, date, ev["in_window_probe_ts"]))
            pd = qualify(_candidate(ev, ev["in_window_probe_ts"], pintern),
                         SessionState(date=date))
            pref = ev.get("in_window_expect_reason_prefix", "SLOPE")
            pin_ok = (not pd.emit_email()) and pd.reason.startswith(pref)
            ok = ok and pin_ok
            probe_note = f" | in-window({ev['in_window_probe_ts']})->{pd.reason}"

        # divergence-from-evidence flag: do the REAL slope signs match the documented signs?
        dsign = signs.get(date, {})
        real_signs = {"add": _sign(d.add_slope), "vold": _sign(d.vold_slope),
                      "trin": _sign(d.trin_slope)}
        sign_flags = []
        for k, exp in dsign.items():
            if k in ("add", "vold", "trin") and real_signs[k] != "?" and real_signs[k] != exp:
                sign_flags.append(f"{k} real{real_signs[k]} != evidence{exp}")
        if sign_flags:
            diverged += 1

        if not ok:
            fails += 1
        gv = (f"ADD_slope {d.add_slope}, VOLD_slope {d.vold_slope}, "
              f"TRIN_slope {d.trin_slope}, |ADDΔ| {d.divergence}")
        print(f"  {ev['test']} {date} {ts} {ev['setup']} {ev['direction']}: "
              f"emit={emit} reason={d.reason}  [{'PASS' if ok else 'FAIL'}]{probe_note}")
        print(f"       real gates: {gv}")
        if sign_flags:
            print(f"       ⚠ DIVERGENCE vs fixture/evidence: {'; '.join(sign_flags)}")

    print("=" * 72)
    verdict = "ALL PASS — real rows confirm the fixture run" if (fails == 0 and diverged == 0) \
        else ("PASS but SLOPE-SIGN DIVERGENCE — investigate before arming" if fails == 0
              else "FAIL — do NOT arm")
    print(f"  fails={fails}  slope_sign_divergences={diverged}  =>  {verdict}")
    return 0 if (fails == 0 and diverged == 0) else 1


# ── self-test (synthetic CSV mechanics) ──────────────────────────────────────
def _selftest() -> int:
    import tempfile
    fails = 0

    def check(name, cond):
        nonlocal fails
        print(f"  {'PASS' if cond else 'FAIL'}  {name}")
        if not cond:
            fails += 1

    # synthesize a 7/16-like declining-ADD window (a real SHORT should qualify)
    tmp = os.path.join(tempfile.mkdtemp(), "internals_live.csv")
    cols = [COL_TS, COL_ADD, COL_VOLD, COL_TRIN, COL_TICK]
    with open(tmp, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        n = FULL_ROWS
        for i in range(n):
            frac = i / (n - 1)
            mm = 20 + i  # 10:20 .. 10:49
            w.writerow({
                COL_TS: f"2026-07-16T{10:02d}:{mm:02d}:00",
                COL_ADD: round(950 - 600 * frac, 1),      # ADD falling
                COL_VOLD: round(450e6 - 800e6 * frac, 0),  # VOLD falling
                COL_TRIN: round(0.85 + 0.85 * frac, 3),    # TRIN rising
                COL_TICK: round(-120 - 260 * frac, 0),
            })
    rows = load_rows(tmp)
    check("loaded 30 rows", len(rows) == FULL_ROWS)
    win = window_slice(rows, "2026-07-16", "10:49")
    check("window slice = 30 rows", len(win) == FULL_ROWS)
    intern = internals_from_rows(win)
    ev = {"date": "2026-07-16", "setup": "Cluster Fade", "direction": "SHORT",
          "level": 7618.0, "level_name": "cluster-VAH", "entry": 7617.0, "stop": 7627.0,
          "t1": 7601.0, "t2": 7589.0, "invalidating_extreme": 7620.0, "atr5m": 4.0,
          "pool_tagged": True, "rejected_within_bars": 2}
    d = qualify(_candidate(ev, "10:49", intern), SessionState(date="2026-07-16"))
    check("real-row SHORT qualifies", d.emit_email())
    check("ADD slope negative from real rows", d.add_slope < 0)
    check("no rows => BLOCKED-safe empty slice", len(window_slice(rows, "2026-01-01", "10:00")) == 0)

    print(f"\nreal_replay self-test: {'ALL PASS' if fails == 0 else str(fails) + ' FAILED'}")
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="path to internals_live.csv (the collector archive)")
    ap.add_argument("--selftest", action="store_true", help="synthetic-CSV mechanics proof")
    a = ap.parse_args()
    if a.selftest or not a.csv:
        if not a.csv and not a.selftest:
            print("no --csv given; running --selftest (cloud has no real archive).\n")
        sys.exit(1 if _selftest() else 0)
    sys.exit(run(a.csv))


if __name__ == "__main__":
    main()
