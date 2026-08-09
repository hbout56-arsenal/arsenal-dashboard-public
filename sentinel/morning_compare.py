#!/usr/bin/env python3
"""
sentinel/morning_compare.py — DISPATCH 114 PRE-ARM · the daily morning comparison

Step 3. Each morning, compare three columns for the prior session:
  - D114 WOULD-FIRE : what the qualified SENTINEL wanted to fire (shadow ledger)
  - OLD SENTINEL    : what the old sentinel actually spammed (old_sentinel_fires.csv, if present)
  - TAPE            : what the session's day-type/close did (from the ledger's day_type +
                      an optional tape note file)

Answers the two questions from the dispatch: does ~200/month become ~15, and are those
the RIGHT 15 (no 8/3-style trend-fighting)? Writes sentinel_morning_compare.json and prints
a compact table. Old-sentinel + tape inputs are optional; when absent the D114 column still
stands and the file says so (never fabricated).

Usage:
  python3 sentinel/morning_compare.py --date 2026-08-11
  python3 sentinel/morning_compare.py                     # all sessions in the ledger
  python3 sentinel/morning_compare.py --selftest
"""
from __future__ import annotations
from typing import List, Dict, Optional
import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ledger as L  # noqa: E402

OLD_FIRES_CSV = os.path.join(L.ROOT, "old_sentinel_fires.csv")   # optional (Mac)
OUT_JSON = os.path.join(L.ROOT, "sentinel_morning_compare.json")
PROJECTION_PER_MONTH_OLD = 200  # the ~200/month baseline from the evidence


def _load_old_fires(path: str = OLD_FIRES_CSV) -> Optional[List[Dict]]:
    if not os.path.exists(path):
        return None
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def compare(rows: List[Dict], dates: Optional[List[str]] = None,
            old_fires: Optional[List[Dict]] = None) -> Dict:
    all_dates = sorted({r["date"] for r in rows})
    use = [d for d in all_dates if (not dates or d in dates)]
    old_by_date: Dict[str, int] = {}
    if old_fires:
        for r in old_fires:
            d = (r.get("date") or r.get("ts", "")[:10])
            old_by_date[d] = old_by_date.get(d, 0) + 1

    per_session = []
    tot_d114 = tot_supp = 0
    for d in use:
        day = [r for r in rows if r["date"] == d]
        fired = [r for r in day if r["qualified"] == "Y"]
        supp = [r for r in day if r["qualified"] == "N"]
        tot_d114 += len(fired)
        tot_supp += len(supp)
        day_type = next((r.get("day_type") for r in day if r.get("day_type")), "")
        per_session.append({
            "date": d, "day_type": day_type,
            "d114_would_fire": len(fired),
            "d114_suppressed": len(supp),
            "old_sentinel_fired": old_by_date.get(d) if old_fires else None,
            "d114_fires": [f'{r["ts"]} {r["setup"]} {r["dir"]} @ {r["entry"]} '
                           f'(ADD_slope {r.get("add_slope")})' for r in fired],
            "top_suppression_reasons": _top_reasons(supp),
        })

    n_sessions = len(use)
    avg_per_day = round(tot_d114 / n_sessions, 2) if n_sessions else None
    projected_month = round(avg_per_day * 21, 1) if avg_per_day is not None else None
    return {
        "schema": "sentinel_morning_compare/1",
        "dispatch": 114,
        "n_sessions": n_sessions,
        "d114_total_would_fire": tot_d114,
        "d114_total_suppressed": tot_supp,
        "d114_avg_fires_per_day": avg_per_day,
        "d114_projected_per_month_21d": projected_month,
        "old_sentinel_baseline_per_month": PROJECTION_PER_MONTH_OLD,
        "old_sentinel_data_present": old_fires is not None,
        "reduction_note": (f"~{PROJECTION_PER_MONTH_OLD}/mo -> ~{projected_month}/mo projected"
                           if projected_month is not None else "n=0"),
        "right_15_check": "run pre_arm_gate.py for the arming verdict (trend-fighting audit)",
        "per_session": per_session,
    }


def _top_reasons(supp: List[Dict], k: int = 4) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for r in supp:
        counts[r["suppression_reason"]] = counts.get(r["suppression_reason"], 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1])[:k])


def run(dates, ledger_path, out_path) -> int:
    rows = L.read_ledger(ledger_path)
    res = compare(rows, dates=dates, old_fires=_load_old_fires())
    with open(out_path, "w") as fh:
        json.dump(res, fh, indent=2)
    print("SENTINEL D114 morning comparison")
    print(f"  sessions {res['n_sessions']}   D114 would-fire {res['d114_total_would_fire']} "
          f"(avg {res['d114_avg_fires_per_day']}/day)   {res['reduction_note']}")
    print(f"  old-sentinel data present: {res['old_sentinel_data_present']}")
    for s in res["per_session"]:
        old = s["old_sentinel_fired"]
        old_s = str(old) if old is not None else "n/a"
        print(f"  {s['date']} [{s['day_type'] or '?':10}]  D114={s['d114_would_fire']} "
              f"(supp {s['d114_suppressed']})  OLD={old_s}")
        for f in s["d114_fires"]:
            print(f"        + {f}")
    print(f"  written -> {out_path}")
    return 0


def _selftest() -> int:
    fails = 0

    def check(name, cond):
        nonlocal fails
        print(f"  {'PASS' if cond else 'FAIL'}  {name}")
        if not cond:
            fails += 1

    def row(d, ts, q, dirn="SHORT", lvl=7600, dt="TREND_DOWN"):
        return {**{k: "" for k in L.FIELDS}, "date": d, "ts": ts, "qualified": q,
                "dir": dirn, "level": lvl, "entry": lvl, "setup": "Cluster Fade",
                "add_slope": "-15.0", "day_type": dt,
                "suppression_reason": "" if q == "Y" else "WINDOW"}
    rows = [row("2026-08-11", "10:30", "Y"), row("2026-08-11", "09:32", "N"),
            row("2026-08-12", "10:40", "Y"), row("2026-08-12", "14:10", "N")]
    res = compare(rows)
    check("2 sessions", res["n_sessions"] == 2)
    check("2 total would-fire", res["d114_total_would_fire"] == 2)
    check("avg 1.0/day", res["d114_avg_fires_per_day"] == 1.0)
    check("projected ~21/mo", res["d114_projected_per_month_21d"] == 21.0)
    check("old data absent flagged", res["old_sentinel_data_present"] is False)
    # with old fires present
    res2 = compare(rows, old_fires=[{"date": "2026-08-11"}] * 7 + [{"date": "2026-08-12"}] * 6)
    check("old counts joined", res2["per_session"][0]["old_sentinel_fired"] == 7)
    print(f"\nmorning_compare self-test: {'ALL PASS' if fails == 0 else str(fails) + ' FAILED'}")
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", action="append", help="limit to date(s); repeatable")
    ap.add_argument("--ledger", default=L.LEDGER_CSV)
    ap.add_argument("--out", default=OUT_JSON)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(1 if _selftest() else 0)
    sys.exit(run(a.date, a.ledger, a.out))


if __name__ == "__main__":
    main()
