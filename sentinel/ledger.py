#!/usr/bin/env python3
"""
sentinel/ledger.py — DISPATCH 114 · SENTINEL forward ledger + labeler + scorecard

Every fire AND every suppressed near-miss is appended to `ledgers/sentinel_forward.csv`.
A nightly triple-barrier labeler stamps the outcome (T1/T2/stop, else time-barrier) from
the day's bars. The scorecard builder rolls the ledger into `sentinel_scorecard.json`
(n_fired, n_qualified, win%, expectancy, by setup, by day-type). DESCRIPTIVE until n>=30.

So this is never email archaeology again: the ledger is the record, the scorecard is the
read. SIMULATED / advisory — not financial advice.

Run:  python3 sentinel/ledger.py     # self-test (round-trip + scorecard mechanics)
"""
from __future__ import annotations
from typing import List, Dict, Optional
import csv
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LEDGER_DIR = os.path.join(ROOT, "ledgers")
LEDGER_CSV = os.path.join(LEDGER_DIR, "sentinel_forward.csv")
SCORECARD_JSON = os.path.join(ROOT, "sentinel_scorecard.json")

VALIDATED_N = 30  # below this the scorecard is DESCRIPTIVE, never edge

FIELDS = ["ts", "date", "setup", "level", "dir", "entry", "stop", "t1", "t2",
          "add_slope", "vold_slope", "trin_slope", "divergence", "atr5m",
          "qualified", "suppression_reason", "taken", "outcome", "R", "day_type"]


def row_from_decision(candidate, decision, taken: bool = False, day_type: str = "") -> Dict:
    """Build a ledger row from a Candidate + Decision (outcome/R stamped later)."""
    def r(x, nd=3):
        return round(x, nd) if isinstance(x, (int, float)) else x
    return {
        "ts": candidate.ts_et, "date": candidate.date, "setup": candidate.setup,
        "level": candidate.level, "dir": candidate.direction,
        "entry": candidate.entry, "stop": candidate.stop, "t1": candidate.t1, "t2": candidate.t2,
        "add_slope": r(decision.add_slope) if decision.add_slope is not None else "",
        "vold_slope": r(decision.vold_slope) if decision.vold_slope is not None else "",
        "trin_slope": r(decision.trin_slope) if decision.trin_slope is not None else "",
        "divergence": r(decision.divergence, 1) if decision.divergence is not None else "",
        "atr5m": candidate.atr5m,
        "qualified": "Y" if decision.qualified else "N",
        "suppression_reason": "" if decision.qualified else decision.reason,
        "taken": "Y" if taken else "N",
        "outcome": "",   # stamped by the nightly labeler
        "R": "",         # stamped by the nightly labeler
        "day_type": day_type,
    }


def ensure_ledger() -> None:
    os.makedirs(LEDGER_DIR, exist_ok=True)
    if not os.path.exists(LEDGER_CSV):
        with open(LEDGER_CSV, "w", newline="") as fh:
            csv.DictWriter(fh, fieldnames=FIELDS).writeheader()


def append_rows(rows: List[Dict]) -> None:
    ensure_ledger()
    with open(LEDGER_CSV, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        for row in rows:
            w.writerow({k: row.get(k, "") for k in FIELDS})


def read_ledger(path: str = LEDGER_CSV) -> List[Dict]:
    if not os.path.exists(path):
        return []
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


# ── triple-barrier labeler ────────────────────────────────────────────────────
def triple_barrier(direction: str, entry: float, stop: float, t1: float, t2: float,
                   bars: List[Dict], t2_first: bool = False) -> Dict:
    """
    Walk 1-min bars AFTER entry. First barrier touched wins:
      - stop hit  => outcome 'STOP', R = -1
      - T2 hit    => outcome 'T2',   R = (t2-entry)/(entry-stop) [dir-signed]
      - T1 hit    => outcome 'T1',   R = (t1-entry)/(entry-stop)
      - none      => outcome 'TIME', R = (last_close-entry)/risk (time barrier)
    Conservative tie rule: within a bar, STOP is assumed hit before targets unless the
    bar never traded through the stop. bars = [{o,h,l,c}, ...] post-entry.
    """
    risk = abs(entry - stop)
    if risk <= 0:
        return {"outcome": "INVALID", "R": None}
    sign = 1.0 if direction == "LONG" else -1.0
    last_close = entry
    for b in bars:
        hi, lo, last_close = b["h"], b["l"], b["c"]
        stop_hit = (lo <= stop) if direction == "LONG" else (hi >= stop)
        t1_hit = (hi >= t1) if direction == "LONG" else (lo <= t1)
        t2_hit = (hi >= t2) if direction == "LONG" else (lo <= t2)
        if stop_hit:
            return {"outcome": "STOP", "R": -1.0}
        if t2_hit:
            return {"outcome": "T2", "R": round(sign * (t2 - entry) / risk, 2)}
        if t1_hit:
            # half off at T1, runner to T2; if only T1 in-bar, book the T1 partial as the label
            return {"outcome": "T1", "R": round(sign * (t1 - entry) / risk, 2)}
    return {"outcome": "TIME", "R": round(sign * (last_close - entry) / risk, 2)}


def label_ledger(bars_by_key: Dict[str, List[Dict]], path: str = LEDGER_CSV) -> int:
    """
    Stamp outcome/R on qualified+taken rows that are still unlabeled, using post-entry bars
    keyed by f"{date}|{ts}|{setup}|{level}". Returns count stamped. Idempotent.
    """
    rows = read_ledger(path)
    stamped = 0
    for row in rows:
        if row.get("outcome"):  # already labeled
            continue
        if row.get("qualified") != "Y":
            continue
        key = f'{row["date"]}|{row["ts"]}|{row["setup"]}|{row["level"]}'
        bars = bars_by_key.get(key)
        if not bars:
            continue
        res = triple_barrier(row["dir"], float(row["entry"]), float(row["stop"]),
                             float(row["t1"]), float(row["t2"]), bars)
        row["outcome"] = res["outcome"]
        row["R"] = "" if res["R"] is None else res["R"]
        stamped += 1
    if stamped:
        with open(path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            for row in rows:
                w.writerow({k: row.get(k, "") for k in FIELDS})
    return stamped


# ── scorecard ─────────────────────────────────────────────────────────────────
def _expectancy(rs: List[float]) -> Dict:
    n = len(rs)
    if n == 0:
        return {"n": 0, "win_pct": None, "expectancy_R": None, "profit_factor": None}
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    gross_w, gross_l = sum(wins), -sum(losses)
    return {
        "n": n,
        "win_pct": round(100.0 * len(wins) / n, 1),
        "expectancy_R": round(sum(rs) / n, 3),
        "profit_factor": round(gross_w / gross_l, 2) if gross_l else None,
    }


def build_scorecard(path: str = LEDGER_CSV, generated_at: str = "") -> Dict:
    rows = read_ledger(path)
    fired = [r for r in rows if r.get("qualified") == "Y"]
    suppressed = [r for r in rows if r.get("qualified") == "N"]
    labeled = [r for r in fired if r.get("outcome") and r.get("R") not in (None, "")]
    rs = [float(r["R"]) for r in labeled]

    def group(key):
        out = {}
        for r in labeled:
            g = r.get(key) or "unknown"
            out.setdefault(g, []).append(float(r["R"]))
        return {g: _expectancy(v) for g, v in out.items()}

    supp_reasons: Dict[str, int] = {}
    for r in suppressed:
        supp_reasons[r["suppression_reason"]] = supp_reasons.get(r["suppression_reason"], 0) + 1

    n = len(labeled)
    overall = _expectancy(rs)
    return {
        "schema": "sentinel_scorecard/1",
        "generated_at": generated_at,
        "dispatch": 114,
        "basis": "SENTINEL qualification layer forward ledger (ledgers/sentinel_forward.csv). "
                 "SIMULATED / advisory — measures the qualifier, not actual fills.",
        "honesty": "DESCRIPTIVE (n<30)" if n < VALIDATED_N else "n>=30 — edge readable",
        "n_rows": len(rows),
        "n_fired": len(fired),
        "n_qualified": len(fired),
        "n_suppressed": len(suppressed),
        "n_labeled": n,
        "n_open_unlabeled": len(fired) - n,
        "overall": overall,
        "by_setup": group("setup"),
        "by_day_type": group("day_type"),
        "suppression_reasons": dict(sorted(supp_reasons.items(), key=lambda kv: -kv[1])),
        "status": "ACCRUING (n=0)" if n == 0 else
                  ("DESCRIPTIVE (n<30)" if n < VALIDATED_N else "READABLE (n>=30)"),
    }


def write_scorecard(generated_at: str = "", path: str = LEDGER_CSV,
                    out: str = SCORECARD_JSON) -> Dict:
    sc = build_scorecard(path, generated_at=generated_at)
    with open(out, "w") as fh:
        json.dump(sc, fh, indent=2)
    return sc


# ── self-test ────────────────────────────────────────────────────────────────
def _selftest() -> int:
    fails = 0

    def check(name, cond):
        nonlocal fails
        print(f"  {'PASS' if cond else 'FAIL'}  {name}")
        if not cond:
            fails += 1

    # triple-barrier: LONG runs to T2 (first bar stays below T1, second bar gaps to T2)
    bars_up = [{"o": 100, "h": 100.8, "l": 99.6, "c": 100.5},
               {"o": 100.5, "h": 104, "l": 100.2, "c": 103.5}]
    res = triple_barrier("LONG", 100.0, 99.0, 101.0, 103.0, bars_up)
    check("LONG T2 outcome", res["outcome"] == "T2" and res["R"] == 3.0)

    # triple-barrier: T1 touched first => labeled T1 (half-off convention)
    res = triple_barrier("LONG", 100.0, 99.0, 101.0, 103.0,
                         [{"o": 100, "h": 101.2, "l": 99.6, "c": 100.9}])
    check("LONG T1 first-touch outcome", res["outcome"] == "T1" and res["R"] == 1.0)

    # triple-barrier: SHORT hits stop first
    bars_dn = [{"o": 100, "h": 101.5, "l": 99, "c": 101}]
    res = triple_barrier("SHORT", 100.0, 101.0, 98.0, 96.0, bars_dn)
    check("SHORT STOP outcome", res["outcome"] == "STOP" and res["R"] == -1.0)

    # time barrier
    bars_flat = [{"o": 100, "h": 100.3, "l": 99.8, "c": 100.1}]
    res = triple_barrier("LONG", 100.0, 99.0, 102.0, 104.0, bars_flat)
    check("TIME barrier outcome", res["outcome"] == "TIME")

    # round-trip ledger + scorecard in a temp path
    import tempfile
    tmp = os.path.join(tempfile.mkdtemp(), "led.csv")
    with open(tmp, "w", newline="") as fh:
        csv.DictWriter(fh, fieldnames=FIELDS).writeheader()

    class C:  # tiny stand-in for a Candidate
        pass

    class D:
        pass
    rows = []
    for i, (q, out, R) in enumerate([("Y", "T2", 2.0), ("Y", "STOP", -1.0), ("N", "", "")]):
        rows.append({**{k: "" for k in FIELDS},
                     "ts": "10:0" + str(i), "date": "2026-07-16", "setup": "Cluster Fade",
                     "level": 7600 + i, "dir": "SHORT", "entry": 7600, "stop": 7610,
                     "t1": 7585, "t2": 7570, "qualified": q,
                     "suppression_reason": "" if q == "Y" else "WINDOW",
                     "taken": "Y" if q == "Y" else "N", "outcome": out, "R": R,
                     "day_type": "TREND_DOWN"})
    with open(tmp, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        for row in rows:
            w.writerow(row)
    sc = build_scorecard(tmp, generated_at="2026-08-08T00:00:00Z")
    check("scorecard n_fired=2", sc["n_fired"] == 2)
    check("scorecard n_suppressed=1", sc["n_suppressed"] == 1)
    check("scorecard n_labeled=2", sc["n_labeled"] == 2)
    check("scorecard win% = 50", sc["overall"]["win_pct"] == 50.0)
    check("scorecard expectancy = 0.5R", sc["overall"]["expectancy_R"] == 0.5)
    check("scorecard DESCRIPTIVE (n<30)", sc["status"].startswith("DESCRIPTIVE"))
    check("by_day_type has TREND_DOWN", "TREND_DOWN" in sc["by_day_type"])
    check("suppression_reasons has WINDOW", sc["suppression_reasons"].get("WINDOW") == 1)

    print(f"\nsentinel ledger self-test: {'ALL PASS' if fails == 0 else str(fails) + ' FAILED'}")
    return fails


if __name__ == "__main__":
    import sys
    sys.exit(1 if _selftest() else 0)
