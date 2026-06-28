#!/usr/bin/env python3
"""
mae_mfe.py  —  DISPATCH 44, Phase 3C (Risk & Survival layer)

Maximum Adverse Excursion (worst drawdown before exit) + Maximum Favorable
Excursion (best unrealized before exit) for closed trades. Aggregates tell you
whether stops are too wide ("winners rarely went >1.2R against you -> tighten")
or targets too tight ("you gave back avg 0.8R from peak -> trail further").

REQUIRES per-trade intraday excursion data (mae_R / mfe_R, derived from bar data
at the trade's timeframe). If that data isn't cached per trade, this DOES NOT
fabricate — it FLAGS the analysis as DEFERRED and reports what's missing.

INPUTS (read-only): a per-trade log carrying mae_R / mfe_R. LIVE log is
excursions.local.json (gitignored); falls back to execution.sample.json (which
intentionally OMITS excursion fields, so the deferral path is exercised).

OUTPUT: mae_mfe.json — either the aggregate analysis or a DEFERRED status.
"""

import json
import os
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

LIVE_EXC = os.path.join(ROOT, "excursions.local.json")     # never mirrored
SAMPLE_EXC = os.path.join(HERE, "execution.sample.json")   # no excursion fields
OUT_PATH = os.path.join(ROOT, "mae_mfe.json")


def _load(path):
    with open(path) as f:
        return json.load(f)


def build():
    if os.path.exists(LIVE_EXC):
        data = _load(LIVE_EXC)
        src = "LIVE (excursions.local.json — not mirrored)"
    else:
        data = _load(SAMPLE_EXC)
        src = "SAMPLE (execution.sample.json — no excursion fields)"

    trades = data.get("trades", [])
    with_exc = [t for t in trades if "mae_R" in t and "mfe_R" in t]

    base = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "kind": "mae_mfe_analysis",
        "dispatch": "44 / Phase 3C",
        "data_source": src,
        "n_trades_seen": len(trades),
        "n_trades_with_excursion": len(with_exc),
    }

    if not with_exc:
        base.update({
            "status": "DEFERRED",
            "banner": "DEFERRED — no per-trade intraday excursion (MAE/MFE) data "
                      "cached. Not fabricated. To enable: cache mae_R/mfe_R per "
                      "closed trade from bar data at the trade's timeframe, then "
                      "re-run. This is the only Phase-3 piece gated on data.",
            "what_is_needed": "per-trade mae_R (worst R against before exit) and "
                              "mfe_R (best R in favour before exit), from cached "
                              "intraday bars.",
        })
        with open(OUT_PATH, "w") as f:
            json.dump(base, f, indent=2)
        return base

    # aggregate (runs only when excursion data exists)
    wins = [t for t in with_exc if t.get("pnl_R", 0) > 0]
    losses = [t for t in with_exc if t.get("pnl_R", 0) <= 0]

    def avg(xs, k):
        return round(sum(x[k] for x in xs) / len(xs), 3) if xs else None

    def pctl(xs, k, q):
        if not xs:
            return None
        v = sorted(x[k] for x in xs)
        return round(v[min(len(v) - 1, int(len(v) * q))], 3)

    base.update({
        "status": "OK",
        "banner": "ADVISORY / SIMULATED — MAE/MFE aggregates. n<30 = descriptive.",
        "winners": {
            "n": len(wins),
            "avg_mae_R": avg(wins, "mae_R"),
            "p90_mae_R": pctl(wins, "mae_R", 0.9),
            "avg_mfe_R": avg(wins, "mfe_R"),
            "avg_giveback_R": round((avg(wins, "mfe_R") or 0) - avg(wins, "pnl_R") or 0, 3)
            if wins else None,
        },
        "losers": {
            "n": len(losses),
            "avg_mae_R": avg(losses, "mae_R"),
            "avg_mfe_R": avg(losses, "mfe_R"),
        },
        "insights": [],
    })
    w = base["winners"]
    if w["p90_mae_R"] is not None and w["p90_mae_R"] > -1.2:
        base["insights"].append(
            f"winners rarely went >{abs(w['p90_mae_R'])}R against you -> stop "
            f"could tighten")
    if w["avg_giveback_R"] and w["avg_giveback_R"] > 0.5:
        base["insights"].append(
            f"you gave back avg {w['avg_giveback_R']}R from peak -> target/trail "
            f"could improve")
    with open(OUT_PATH, "w") as f:
        json.dump(base, f, indent=2)
    return base


if __name__ == "__main__":
    res = build()
    print(f"mae_mfe.json written. status={res['status']} source={res['data_source']}")
    print(f"  {res['banner']}")
