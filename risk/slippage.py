#!/usr/bin/env python3
"""
slippage.py  —  DISPATCH 44, Phase 3B (Risk & Survival layer)

Execution-quality tracking. For each trade, compare the EXPECTED entry/exit
(from the alert/plan) with the ACTUAL fill (Hany enters) -> slippage per trade,
then aggregate the execution drag ("avg slippage 0.3pt/trade = $X/yr drag").

Slippage is signed so it always means COST: a worse-than-planned entry or exit
is positive slippage (drag). ADVISORY / SIMULATED.

INPUTS (read-only): execution log with exp_/act_ entry & exit. LIVE log is
execution.local.json (gitignored); falls back to execution.sample.json.

OUTPUT: slippage.json — per-trade + aggregate drag. Points / $ are SIMULATED
(micro point-values); no real account $.
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

LIVE_EXEC = os.path.join(ROOT, "execution.local.json")     # never mirrored
SAMPLE_EXEC = os.path.join(HERE, "execution.sample.json")
OUT_PATH = os.path.join(ROOT, "slippage.json")


def _load(path):
    with open(path) as f:
        return json.load(f)


def slip_points(t):
    """
    Cost-positive slippage. Entry: long fills HIGHER than planned = worse;
    short fills LOWER than planned = worse. Exit: long sells LOWER than planned
    = worse; short covers HIGHER = worse. Total drag in points = entry + exit.
    """
    d = 1 if t.get("dir", "long") == "long" else -1
    entry_cost = (t["act_entry"] - t["exp_entry"]) * d
    exit_cost = (t["exp_exit"] - t["act_exit"]) * d
    return round(entry_cost, 4), round(exit_cost, 4), round(entry_cost + exit_cost, 4)


def build(trades_per_year_assumption=80):
    if os.path.exists(LIVE_EXEC):
        data = _load(LIVE_EXEC)
        src = "LIVE (execution.local.json — not mirrored)"
    else:
        data = _load(SAMPLE_EXEC)
        src = "SAMPLE (synthetic)"
    pv = data.get("point_value", {})
    per_trade = []
    by_instr = defaultdict(lambda: {"n": 0, "pts": 0.0, "dollars": 0.0})
    total_pts = total_dollars = 0.0
    for t in data.get("trades", []):
        e, x, tot = slip_points(t)
        dollars = round(tot * pv.get(t["instrument"], 1.0), 2)
        per_trade.append({"id": t.get("id"), "instrument": t["instrument"],
                          "dir": t.get("dir"), "entry_slip_pts": e,
                          "exit_slip_pts": x, "total_slip_pts": tot,
                          "slip_$": dollars})
        total_pts += tot
        total_dollars += dollars
        bi = by_instr[t["instrument"]]
        bi["n"] += 1
        bi["pts"] += tot
        bi["dollars"] += dollars

    n = len(per_trade)
    avg_pts = round(total_pts / n, 4) if n else 0.0
    avg_dollars = round(total_dollars / n, 2) if n else 0.0
    annual_drag = round(avg_dollars * trades_per_year_assumption, 2)

    for k, v in by_instr.items():
        v["avg_pts"] = round(v["pts"] / v["n"], 4)
        v["pts"] = round(v["pts"], 4)
        v["dollars"] = round(v["dollars"], 2)

    out = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "kind": "slippage_execution_drag",
        "dispatch": "44 / Phase 3B",
        "banner": "ADVISORY / SIMULATED — expected (plan) vs actual (fill). "
                  "Positive = cost/drag. Aggregate drag estimates the annual "
                  "cost of execution quality. Micro $; no real account $.",
        "execution_source": src,
        "n_trades": n,
        "avg_slip_pts_per_trade": avg_pts,
        "avg_slip_$_per_trade": avg_dollars,
        "trades_per_year_assumption": trades_per_year_assumption,
        "estimated_annual_drag_$": annual_drag,
        "headline": f"avg slippage {avg_pts} pt/trade = ${annual_drag}/yr drag "
                    f"(at {trades_per_year_assumption} trades/yr, SIMULATED)",
        "by_instrument": by_instr,
        "per_trade": per_trade,
        "privacy": "Real fills live in execution.local.json (never mirrored).",
    }
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=2)
    return out


if __name__ == "__main__":
    res = build()
    print(f"slippage.json written. source={res['execution_source']}")
    print(f"  {res['headline']}")
    for t in res["per_trade"]:
        print(f"  {t['id']} {t['instrument']} {t['dir']}: entry {t['entry_slip_pts']} "
              f"exit {t['exit_slip_pts']} = {t['total_slip_pts']}pt (${t['slip_$']})")
