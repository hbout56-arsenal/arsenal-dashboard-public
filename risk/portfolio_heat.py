#!/usr/bin/env python3
"""
portfolio_heat.py  —  DISPATCH 44, Phase 2A (Risk & Survival layer)

Live total-risk meter. Sums OPEN risk across all current positions:
  * GROSS heat  = total at risk if EVERY open stop hits at once (worst case).
  * CORRELATION-ADJUSTED heat = 3 correlated longs are ~one 3x bet, not 3
    independent bets. Warns when you stack correlated risk (e.g. long MES + 3
    long index stocks all move together).

ADVISORY / SIMULATED. Hany executes.

INPUTS (read-only)
------------------
- positions.local.json   LIVE open book. Gitignored, NEVER mirrored. Falls back
                         to positions.sample.json (synthetic) for validation.
- account_summary.json   SIMULATED $15k paper equity (public) for the % ref.

OUTPUT
------
- portfolio_heat.json    mirror-safe: %s and multiples only, NO real $ and NO
                         real position sizes.

CORRELATION MODEL
-----------------
Positions carry a correlation_group. Within a group, same-direction risks add
(rho ~ WITHIN_RHO); opposite directions offset; across groups they're treated
as independent. Two readouts:
  - correlation-adjusted heat % = sqrt(w^T Σ w), Σ = WITHIN_RHO inside a group
    (signed by direction), 0 across groups — the statistical 1-stop-sigma risk.
  - factor concentration Zx = the largest same-direction group's summed risk
    expressed as a multiple of one position's risk ("this factor = Zx bets").
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

LIVE_POS = os.path.join(ROOT, "positions.local.json")      # never mirrored
SAMPLE_POS = os.path.join(HERE, "positions.sample.json")   # synthetic
ACCT_PATH = os.path.join(ROOT, "account_summary.json")
OUT_PATH = os.path.join(ROOT, "portfolio_heat.json")

WITHIN_RHO = 0.8   # assumed correlation between same-group positions

# RAG thresholds on GROSS heat %, tied to the loss limits (daily -3% / weekly -6%)
GREEN_MAX = 3.0
AMBER_MAX = 6.0


def _load(path):
    with open(path) as f:
        return json.load(f)


def _dir(p):
    return 1 if p.get("dir", "long") == "long" else -1


def compute(positions):
    risks = [abs(p.get("risk_pct", 0.0)) for p in positions]
    gross = round(sum(risks), 3)

    # group positions by correlation_group
    groups = defaultdict(list)
    for p in positions:
        groups[p.get("correlation_group", p.get("instrument", "UNGROUPED"))].append(p)

    # statistical correlation-adjusted heat = sqrt(w^T Σ w)
    variance = 0.0
    group_breakdown = []
    factor_mult = 1.0
    for g, ps in groups.items():
        gr = [abs(x.get("risk_pct", 0.0)) for x in ps]
        gv = sum(r * r for r in gr)
        for i in range(len(ps)):
            for j in range(i + 1, len(ps)):
                gv += 2 * WITHIN_RHO * _dir(ps[i]) * _dir(ps[j]) * gr[i] * gr[j]
        gv = max(gv, 0.0)
        variance += gv
        # net same-direction additive risk (longs minus shorts)
        net_dir = sum(_dir(x) * abs(x.get("risk_pct", 0.0)) for x in ps)
        same_dir_add = abs(net_dir)
        one_pos = max(gr) if gr else 0.0
        mult = round(same_dir_add / one_pos, 2) if one_pos else 0.0
        factor_mult = max(factor_mult, mult)
        group_breakdown.append({
            "group": g,
            "n_positions": len(ps),
            "gross_risk_pct": round(sum(gr), 3),
            "net_directional_risk_pct": round(net_dir, 3),
            "factor_multiple_x": mult,
            "note": (f"{len(ps)} correlated same-direction bets ≈ {mult}x a "
                     f"single position" if mult > 1.3 else "diversified within group"),
        })
    corr_adj = round(variance ** 0.5, 3)
    independent_equiv = round(sum(r * r for r in risks) ** 0.5, 3)  # if all uncorrelated
    diversification_illusion_x = round(corr_adj / independent_equiv, 2) if independent_equiv else 1.0

    if gross <= GREEN_MAX:
        rag = "GREEN"
    elif gross <= AMBER_MAX:
        rag = "AMBER"
    else:
        rag = "RED"
    # escalate on heavy factor concentration even if gross is moderate
    if factor_mult >= 3.0 and rag == "GREEN":
        rag = "AMBER"

    group_breakdown.sort(key=lambda x: x["factor_multiple_x"], reverse=True)
    return {
        "n_open_positions": len(positions),
        "gross_heat_pct": gross,
        "correlation_adjusted_heat_pct": corr_adj,
        "independent_equivalent_heat_pct": independent_equiv,
        "factor_concentration_x": round(factor_mult, 2),
        "diversification_illusion_x": diversification_illusion_x,
        "rag": rag,
        "by_correlation_group": group_breakdown,
    }


def build():
    acct = _load(ACCT_PATH)
    if os.path.exists(LIVE_POS):
        book = _load(LIVE_POS)
        src = "LIVE (positions.local.json — not mirrored)"
    else:
        book = _load(SAMPLE_POS)
        src = "SAMPLE (synthetic — no live book present)"
    positions = book.get("positions", [])
    h = compute(positions)

    meter = (f"Open heat: {h['gross_heat_pct']}% equity · "
             f"correlation-adjusted {h['factor_concentration_x']}x · [{h['rag']}]")

    out = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "kind": "portfolio_heat_meter",
        "dispatch": "44 / Phase 2A",
        "banner": "ADVISORY / SIMULATED — live total open risk if every stop "
                  "hits. Correlated same-direction bets stack (3 index longs ≈ "
                  "one 3x bet, NOT 3 diversified bets). Hany executes.",
        "positions_source": src,
        "equity_basis": "SIMULATED_paper_15k (% reference; no real $ mirrored)",
        "within_group_rho_assumed": WITHIN_RHO,
        "rag_thresholds_pct": {"green_max": GREEN_MAX, "amber_max": AMBER_MAX,
                               "ties_to": "daily -3% / weekly -6% loss limits"},
        "meter_line": meter,
        **h,
        "privacy": "Real open positions + sizes live in positions.local.json "
                   "(never mirrored). Only %s and multiples are emitted here.",
    }
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=2)
    return out


if __name__ == "__main__":
    res = build()
    print(f"portfolio_heat.json written. source={res['positions_source']}")
    print(res["meter_line"])
    print(f"  gross={res['gross_heat_pct']}%  corr-adj(stat)={res['correlation_adjusted_heat_pct']}%  "
          f"independent-equiv={res['independent_equivalent_heat_pct']}%")
    print(f"  factor concentration={res['factor_concentration_x']}x  "
          f"diversification-illusion={res['diversification_illusion_x']}x")
    for g in res["by_correlation_group"]:
        print(f"  - {g['group']}: {g['n_positions']} pos, gross {g['gross_risk_pct']}%, "
              f"{g['factor_multiple_x']}x — {g['note']}")
