#!/usr/bin/env python3
"""
edge_by_regime.py  —  DISPATCH 44, Phase 2B (Risk & Survival layer)

Cross every setup/bucket's expectancy with the COINCIDENT regime label at the
trade's ENTRY time (TRENDING / CHOP / TRANSITIONAL — D39 regime_label). This
often reveals the real edge is CONDITIONAL: a setup that looks flat overall can
be "+0.6R in TRENDING, -0.2R in CHOP" — i.e. it works in one regime and bleeds
in another. Tells you WHEN to take each setup.

ADVISORY / SIMULATED. n<30 per cell = DESCRIPTIVE (not validated).

INPUTS (read-only)
------------------
- per-trade log tagged with regime_at_entry. In production this is the real log
  emitted by asymmetry.py (each entry stamped with the D39 regime_label). The
  public mirror has no real per-trade log, so this falls back to
  trades_with_regime.sample.json (synthetic) to validate the cross-tab.
- regime_label.json   only for the thresholds/labels reference.

OUTPUT
------
- edge_by_regime.json   per-setup × regime cell: n, win rate, expectancy_R,
                        descriptive flag, plus a one-line brief per setup.
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

LIVE_TRADES = os.path.join(ROOT, "trades_with_regime.local.json")   # never mirrored
SAMPLE_TRADES = os.path.join(HERE, "trades_with_regime.sample.json")
REGIME_PATH = os.path.join(ROOT, "regime_label.json")
OUT_PATH = os.path.join(ROOT, "edge_by_regime.json")

REGIMES = ["TRENDING", "TRANSITIONAL", "CHOP"]
MIN_N = 30


def _load(path):
    with open(path) as f:
        return json.load(f)


def cross_tab(trades):
    cells = defaultdict(lambda: defaultdict(list))
    for t in trades:
        cells[t["setup"]][t.get("regime_at_entry", "UNKNOWN")].append(t.get("pnl_R", 0.0))
    result = {}
    for setup, by_reg in cells.items():
        row = {}
        brief_parts = []
        for reg in REGIMES + [k for k in by_reg if k not in REGIMES]:
            rs = by_reg.get(reg)
            if not rs:
                continue
            n = len(rs)
            wins = sum(1 for r in rs if r > 0)
            exp = round(sum(rs) / n, 3)
            row[reg] = {
                "n": n,
                "win_rate": round(wins / n, 3),
                "expectancy_R": exp,
                "status": "DESCRIPTIVE (n<30)" if n < MIN_N else "n>=30",
            }
            brief_parts.append(f"{exp:+.2f}R in {reg} (n={n})")
        # conditional-edge call-out: best vs worst regime
        ranked = sorted(row.items(), key=lambda kv: kv[1]["expectancy_R"], reverse=True)
        conditional = None
        if len(ranked) >= 2:
            best, worst = ranked[0], ranked[-1]
            if best[1]["expectancy_R"] > 0 >= worst[1]["expectancy_R"]:
                conditional = (f"CONDITIONAL EDGE — works in {best[0]} "
                               f"({best[1]['expectancy_R']:+.2f}R), bleeds in "
                               f"{worst[0]} ({worst[1]['expectancy_R']:+.2f}R). "
                               f"Take it in {best[0]}; stand down in {worst[0]}.")
        result[setup] = {
            "by_regime": row,
            "brief": "; ".join(brief_parts),
            "conditional_edge": conditional,
            "all_cells_descriptive": all(c["n"] < MIN_N for c in row.values()),
        }
    return result


def build():
    if os.path.exists(LIVE_TRADES):
        data = _load(LIVE_TRADES)
        src = "LIVE (trades_with_regime.local.json — not mirrored)"
    else:
        data = _load(SAMPLE_TRADES)
        src = "SAMPLE (synthetic — no real per-trade regime log in mirror)"
    reg = _load(REGIME_PATH)
    result = cross_tab(data.get("trades", []))

    out = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "kind": "edge_by_regime_crosstab",
        "dispatch": "44 / Phase 2B",
        "banner": "ADVISORY / SIMULATED — expectancy per setup CROSSED with the "
                  "coincident regime (D39) at entry. Reveals when the edge is "
                  "CONDITIONAL (setup x regime), not the setup alone. n<30 per "
                  "cell = DESCRIPTIVE.",
        "trades_source": src,
        "regime_thresholds": reg.get("locked_thresholds"),
        "regimes": REGIMES,
        "min_n_for_validation": MIN_N,
        "setups": result,
    }
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=2)
    return out


if __name__ == "__main__":
    res = build()
    print(f"edge_by_regime.json written. source={res['trades_source']}")
    for setup, r in res["setups"].items():
        print(f"\n{setup}")
        print(f"  {r['brief']}")
        if r["conditional_edge"]:
            print(f"  >> {r['conditional_edge']}")
