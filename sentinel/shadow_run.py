#!/usr/bin/env python3
"""
sentinel/shadow_run.py — DISPATCH 114 PRE-ARM · shadow mode (run live, EMAIL NOTHING)

[MAC-LOCAL] Step 2. Wraps the frozen qualifier for a live session with the email path
HARD-OFF. For each engine-detected candidate it runs qualify(), logs EVERY would-fire and
EVERY suppression (with full gate values) to ledgers/sentinel_forward.csv, and never sends.
Call publish_scorecard() at end-of-day to refresh sentinel_scorecard.json.

The engine's setup DETECTION lives in the private tree; this is the qualify+log+suppress
seam around it. Drive it either in-process (feed Candidate objects) or via the CLI
(candidates JSON + internals CSV) so a plist can call it.

  EMAIL_ENABLED = False   # the shadow guarantee — this module never emits an email.

Usage (CLI, Mac):
  python3 sentinel/shadow_run.py --candidates day.json --csv internals_live.csv --date 2026-08-11
  python3 sentinel/shadow_run.py --publish --asof 2026-08-11T16:30:00Z
  python3 sentinel/shadow_run.py --selftest
"""
from __future__ import annotations
from typing import List, Dict, Optional
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sentinel import Candidate, Internals, SessionState, qualify  # noqa: E402
import ledger as L  # noqa: E402
import real_replay as RR  # noqa: E402

EMAIL_ENABLED = False  # SHADOW: never send. Arming flips this in the private sender, not here.


def process_session(candidates: List[Candidate], date: str,
                    day_type: str = "", taken_levels: Optional[List[float]] = None) -> Dict:
    """Run a day's detected candidates through the qualifier; log all; email none.
    Returns a per-session summary. taken_levels: levels the trader actually took (marks
    'taken' rows + trips the one-loss-done cap the way the live session would)."""
    sess = SessionState(date=date)
    rows = []
    would_fire = []
    for c in candidates:
        d = qualify(c, sess)
        taken = bool(taken_levels and any(abs(c.level - lv) <= 3.0 for lv in taken_levels))
        rows.append(L.row_from_decision(c, d, taken=taken, day_type=day_type))
        if d.emit_email():
            would_fire.append(c)
            assert not EMAIL_ENABLED, "SHADOW invariant violated: email path is off"
        if taken:
            sess.mark_taken()  # honor one-loss-done for the rest of the session
    L.append_rows(rows)
    return {"date": date, "n_candidates": len(candidates),
            "n_would_fire": len(would_fire), "n_logged": len(rows),
            "emailed": 0}


def process_cli(candidates_json: str, csv_path: str, date: str, day_type: str = "") -> Dict:
    """Build Candidates from an engine candidates-JSON, joining REAL internals from the CSV."""
    with open(candidates_json) as fh:
        specs = json.load(fh)
    rows = RR.load_rows(csv_path)
    cands = []
    for ev in specs:
        win = RR.window_slice(rows, date, ev["ts_et"])
        intern = RR.internals_from_rows(win) if len(win) >= 2 else Internals()
        cands.append(Candidate(
            ts_et=ev["ts_et"], date=date, setup=ev["setup"], direction=ev["direction"],
            level=ev["level"], level_name=ev.get("level_name", ""), entry=ev["entry"],
            stop=ev["stop"], t1=ev["t1"], t2=ev["t2"],
            invalidating_extreme=ev["invalidating_extreme"], atr5m=ev["atr5m"],
            internals=intern, pool_tagged=ev.get("pool_tagged", False),
            rejected_within_bars=ev.get("rejected_within_bars"),
            boundary_close_beyond_pts=ev.get("boundary_close_beyond_pts"),
            retested=ev.get("retested", False),
            washout_reclaim_bars=ev.get("washout_reclaim_bars"),
            aligned=ev.get("aligned")))
    return process_session(cands, date, day_type=day_type,
                           taken_levels=specs and None)


def publish_scorecard(asof: str) -> Dict:
    return L.write_scorecard(generated_at=asof)


# ── self-test ────────────────────────────────────────────────────────────────
def _selftest() -> int:
    import tempfile
    fails = 0

    def check(name, cond):
        nonlocal fails
        print(f"  {'PASS' if cond else 'FAIL'}  {name}")
        if not cond:
            fails += 1

    # redirect the ledger to a temp file for the test
    tmpdir = tempfile.mkdtemp()
    orig_csv, orig_dir = L.LEDGER_CSV, L.LEDGER_DIR
    L.LEDGER_DIR = tmpdir
    L.LEDGER_CSV = os.path.join(tmpdir, "sentinel_forward.csv")
    try:
        def _lin(a, b, n=30):
            return [round(a + (b - a) * i / (n - 1), 3) for i in range(n)]
        good = Candidate(ts_et="10:49", date="2026-08-11", setup="Cluster Fade",
                         direction="SHORT", level=7618.0, level_name="cluster", entry=7617.0,
                         stop=7627.0, t1=7601.0, t2=7589.0, invalidating_extreme=7620.0,
                         atr5m=4.0, internals=Internals(add=_lin(950, 350), vold=_lin(4e8, -3e8),
                         trin=_lin(0.85, 1.7), tick=_lin(-120, -380), feed_age_s=10),
                         pool_tagged=True, rejected_within_bars=2)
        offwin = Candidate(**{**good.__dict__, "ts_et": "09:32"})
        summ = process_session([good, offwin], "2026-08-11", day_type="TREND_DOWN")
        check("2 candidates logged", summ["n_logged"] == 2)
        check("1 would-fire", summ["n_would_fire"] == 1)
        check("emailed 0 (shadow)", summ["emailed"] == 0)
        led = L.read_ledger(L.LEDGER_CSV)
        check("ledger has 2 rows", len(led) == 2)
        check("one qualified Y", sum(1 for r in led if r["qualified"] == "Y") == 1)
        check("off-window row reason WINDOW",
              any(r["suppression_reason"] == "WINDOW" for r in led))
        sc = L.build_scorecard(L.LEDGER_CSV, generated_at="2026-08-11T16:30:00Z")
        check("scorecard n_fired=1", sc["n_fired"] == 1)
        check("EMAIL_ENABLED is False", EMAIL_ENABLED is False)
    finally:
        L.LEDGER_CSV, L.LEDGER_DIR = orig_csv, orig_dir

    print(f"\nshadow_run self-test: {'ALL PASS' if fails == 0 else str(fails) + ' FAILED'}")
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates")
    ap.add_argument("--csv")
    ap.add_argument("--date")
    ap.add_argument("--day-type", default="")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--asof", default="")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(1 if _selftest() else 0)
    if a.publish:
        sc = publish_scorecard(a.asof)
        print(f"published sentinel_scorecard.json  status={sc['status']}")
        sys.exit(0)
    if a.candidates and a.csv and a.date:
        summ = process_cli(a.candidates, a.csv, a.date, day_type=a.day_type)
        print(json.dumps(summ, indent=2))
        print("SHADOW: emailed 0 (email path is hard-off).")
        sys.exit(0)
    ap.print_help()
    sys.exit(2)


if __name__ == "__main__":
    main()
