#!/usr/bin/env python3
"""
sentinel/seed.py — DISPATCH 114 · regenerate the SENTINEL artifacts

Produces, deterministically (no wall-clock in the content):
  1. ledgers/sentinel_forward.csv       header only — the LIVE forward ledger, empty at
                                        go-live (day-0 ACCRUING). The live qualifier + the
                                        nightly labeler append to this.
  2. sentinel/D114_replay.csv           the D114 acceptance replay written THROUGH the same
                                        ledger writer — every fire AND every suppressed
                                        near-miss — proving the logging path end-to-end.
  3. sentinel_scorecard.json            published to the dashboard root: forward stats
                                        (n=0 ACCRUING) + a d114_acceptance_replay block.

Usage:  python3 sentinel/seed.py [--asof YYYY-MM-DDTHH:MM:SSZ]
The asof stamp is passed in (never Date.now()) so the artifact is reproducible.
"""
from __future__ import annotations
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sentinel import qualify, SessionState  # noqa: E402
import ledger as L  # noqa: E402
import acceptance_tests as AT  # noqa: E402

REPLAY_CSV = os.path.join(L.HERE, "D114_replay.csv")

# day-type tags for the replay dates (from the replay-bundle heuristic tagger vocabulary)
DAY_TYPE = {
    "2026-08-03": "TREND_UP",   # the one-way grind — 0-for-6 shorts
    "2026-07-16": "TREND_DOWN",
    "2026-07-22": "TREND_UP",
    "2026-07-24": "TREND_UP",
    "2026-07-30": "CHOP",
    "2026-07-28": "CHOP",
}


def _replay_candidates():
    """Every candidate the six acceptance tests drive, in order (fired + near-misses)."""
    out = []
    # A — the six 8/3 ascending fades (all suppressed)
    for ts, lvl in [("09:32", 7566.0), ("11:05", 7618.0), ("11:26", 7614.0),
                    ("12:13", 7603.0), ("12:54", 7606.0), ("13:21", 7618.0)]:
        out.append(AT.fx_8_3_cluster_fade(ts, lvl))
    # B, C — the two that must fire
    out.append(AT.fx_7_16_cluster_fade())
    out.append(AT.fx_7_22_pullback_hold())
    # D — first-touch short (suppressed)
    out.append(AT.fx_7_24_first_touch())
    # E — the debounce second-tag (handled per-session below)
    # F — the two off-window near-misses
    early = AT.fx_7_16_cluster_fade(); early.ts_et = "09:32"; early.date = "2026-07-30"
    late = AT.fx_7_16_cluster_fade(); late.ts_et = "15:46"; late.date = "2026-07-28"
    out.append(early)
    out.append(late)
    return out


def write_forward_header():
    L.ensure_ledger()  # header-only if absent; leaves any existing forward rows intact


def write_replay():
    rows = []
    sessions = {}
    for c in _replay_candidates():
        sess = sessions.setdefault(c.date, SessionState(date=c.date))
        d = qualify(c, sess)
        rows.append(L.row_from_decision(c, d, taken=False, day_type=DAY_TYPE.get(c.date, "")))
    # E — debounce: a second 7618 tag in the 7/16 session (must suppress DEBOUNCE)
    second = AT.fx_7_16_cluster_fade(); second.ts_et = "11:05"
    d2 = qualify(second, sessions["2026-07-16"])
    rows.append(L.row_from_decision(second, d2, taken=False, day_type=DAY_TYPE["2026-07-16"]))

    with open(REPLAY_CSV, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=L.FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in L.FIELDS})
    return rows


def build_scorecard(asof: str, replay_rows):
    # forward stats over the (empty) forward ledger
    sc = L.build_scorecard(L.LEDGER_CSV, generated_at=asof)
    # d114 acceptance replay summary (separate from forward — demonstrative)
    fired = [r for r in replay_rows if r["qualified"] == "Y"]
    supp = [r for r in replay_rows if r["qualified"] == "N"]
    reasons = {}
    for r in supp:
        reasons[r["suppression_reason"]] = reasons.get(r["suppression_reason"], 0) + 1
    sc["d114_acceptance_replay"] = {
        "note": "REPLAY of the D114 acceptance fixtures through the live qualifier — NOT "
                "forward trades. Fixtures reconstructed from the 30-day sent-alert evidence.",
        "n_candidates": len(replay_rows),
        "n_fired": len(fired),
        "n_suppressed": len(supp),
        "fired": [f"{r['date']} {r['ts']} {r['setup']} {r['dir']} @ {r['entry']}" for r in fired],
        "suppression_reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
        "tests": {"A": "6 fades suppressed", "B": "7/16 fired", "C": "7/22 fired",
                  "D": "7/24 suppressed", "E": "7618 debounced", "F": "9:32/15:46 windowed"},
    }
    with open(L.SCORECARD_JSON, "w") as fh:
        json.dump(sc, fh, indent=2)
    return sc


def main():
    asof = "2026-08-08T00:00:00Z"
    if "--asof" in sys.argv:
        asof = sys.argv[sys.argv.index("--asof") + 1]
    write_forward_header()
    replay_rows = write_replay()
    sc = build_scorecard(asof, replay_rows)
    print(f"forward ledger : {L.LEDGER_CSV}  (rows={len(L.read_ledger())})")
    print(f"replay ledger  : {REPLAY_CSV}  (rows={len(replay_rows)})")
    print(f"scorecard      : {L.SCORECARD_JSON}")
    print(f"  forward status: {sc['status']}")
    print(f"  replay fired  : {sc['d114_acceptance_replay']['n_fired']} / "
          f"{sc['d114_acceptance_replay']['n_candidates']}")
    print(f"  replay supp   : {sc['d114_acceptance_replay']['suppression_reasons']}")


if __name__ == "__main__":
    main()
