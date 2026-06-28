#!/usr/bin/env python3
"""
risk_model.py  —  DISPATCH 44, Phase 1A (Risk & Survival layer)

Position sizing + risk-of-ruin for each validated setup.

WHAT THIS IS
------------
Arsenal measures "is there an edge" well (asymmetry.py / portfolio_constructor).
It does NOT yet say "how big do I size it so the inevitable drawdown doesn't
end the account." This closes that gap. ADVISORY / SIMULATED only — Hany sizes
and executes; nothing here is financial advice.

PRINCIPLE: a positive-expectancy edge still blows up if sized wrong. Size to
SURVIVE the drawdown the (in-sample) edge will inevitably have, not to maximise
the in-sample curve.

INPUTS (read-only)
------------------
- portfolio_constructor.json   per-setup n, net_expectancy, payoff, pf, $/trade
                               (the validated-candidate ranking; D40/D41).
                               Win rate is DERIVED, not re-measured:
                                   W = PF / (PF + payoff)
                               which is exact given PF = (W/(1-W))*payoff.
- account_summary.json         the SIMULATED $15,000 paper equity (already
                               public). Used as the public example equity.
- real_equity.local.json       OPTIONAL local override (gitignored, NEVER
                               mirrored). If present, sizing is computed on the
                               real number but only %s / contract counts are
                               written — no real $ ever lands in risk_model.json.

OUTPUT
------
- risk_model.json   per-setup recommended size BAND (conservative 1% / standard
                    2% / max-safe) + P(ruin) at each. Percentages and contract
                    counts only; the dollar equity used is the SIMULATED $15k
                    unless a local override is present (and even then no real $
                    is emitted).

Monte-Carlo note: this mirrors the resampling approach used by the backtest
engine's MC (fixed seed -> reproducible). In the private tree this would import
backtest_engine.monte_carlo; the public mirror carries a self-contained, seeded
copy so the computed view is reproducible here without the engine.
"""

import json
import math
import os
import random
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

PC_PATH = os.path.join(ROOT, "portfolio_constructor.json")
ACCT_PATH = os.path.join(ROOT, "account_summary.json")
LOCAL_EQUITY_PATH = os.path.join(ROOT, "real_equity.local.json")  # never mirrored
OUT_PATH = os.path.join(ROOT, "risk_model.json")

# ── Monte-Carlo config (seeded => reproducible) ──────────────────────────────
MC_SEED = 4400
MC_SIMS = 20000
DD_BANDS = [20, 25, 50]          # drawdown % levels we report P(hit) for
MAX_SAFE_DD = 25                 # "max safe size" keeps P(hit -25%) under...
MAX_SAFE_P = 0.05                # ...5%
RISK_GRID = [round(0.0025 * i, 4) for i in range(1, 41)]  # 0.25%..10% search grid


def _load(path):
    with open(path) as f:
        return json.load(f)


def derive_win_rate(pf, payoff):
    """W = PF / (PF + payoff). Exact inverse of PF = (W/(1-W))*payoff."""
    if pf is None or payoff is None or payoff <= 0 or pf <= 0:
        return None
    return pf / (pf + payoff)


def kelly_fraction(W, payoff):
    """f* = W - (1-W)/payoff  (fraction of equity to risk at full Kelly)."""
    if payoff <= 0:
        return None
    return W - (1.0 - W) / payoff


def expectancy_R(W, payoff):
    """Per-trade expectancy in R (loss = -1R, win = +payoff R)."""
    return W * payoff - (1.0 - W)


def dollars_per_R(setup, exp_R):
    """
    1R in $ per contract = avg dollar risked per losing contract-trade
    (i.e. the structural stop distance valued in $). Derived from the $ and R
    expectancies:
        $/trade = expectancy_R * ($/R)   =>   $/R = $/trade / expectancy_R
    """
    d = setup.get("dollar") or {}
    exp_dollar = d.get("exp_$_per_trade")
    if exp_dollar is None or exp_R is None or abs(exp_R) < 1e-9:
        return None
    return round(exp_dollar / exp_R, 2)


def monte_carlo_ruin(W, payoff, risk_frac, n_trades, sims=MC_SIMS, seed=MC_SEED,
                     dd_bands=DD_BANDS):
    """
    Fixed-fractional Monte-Carlo. Each trade risks `risk_frac` of CURRENT equity;
    win (prob W) -> +payoff*risk, loss -> -risk. Track running peak and the worst
    drawdown from peak. Report P(worst DD >= band) over n_trades, plus the median
    and 5th-percentile terminal return. Seeded -> reproducible.
    """
    rng = random.Random(seed)
    band_hits = {b: 0 for b in dd_bands}
    terminals = []
    for _ in range(sims):
        eq = 1.0
        peak = 1.0
        worst_dd = 0.0
        for _ in range(n_trades):
            if rng.random() < W:
                eq *= (1.0 + payoff * risk_frac)
            else:
                eq *= (1.0 - risk_frac)
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak
            if dd > worst_dd:
                worst_dd = dd
        for b in dd_bands:
            if worst_dd >= b / 100.0:
                band_hits[b] += 1
        terminals.append(eq)
    terminals.sort()
    p = {f"p_hit_-{b}pct": round(band_hits[b] / sims, 4) for b in dd_bands}
    median_ret = round((terminals[sims // 2] - 1.0) * 100, 2)
    p5_ret = round((terminals[int(sims * 0.05)] - 1.0) * 100, 2)
    return p, median_ret, p5_ret


def max_safe_risk(W, payoff, n_trades):
    """Largest risk-per-trade keeping P(hit -MAX_SAFE_DD%) < MAX_SAFE_P."""
    best = 0.0
    best_p = None
    for r in RISK_GRID:
        p, _, _ = monte_carlo_ruin(W, payoff, r, n_trades, sims=6000,
                                   dd_bands=[MAX_SAFE_DD])
        ph = p[f"p_hit_-{MAX_SAFE_DD}pct"]
        if ph < MAX_SAFE_P:
            best = r
            best_p = ph
        else:
            break
    return best, best_p


def contracts_for(risk_frac, equity, dollars_R):
    """Implied position size given risk%, equity, and $/R per contract."""
    if not dollars_R or dollars_R <= 0:
        return None
    risk_dollars = equity * risk_frac
    return round(risk_dollars / dollars_R, 2)


def build():
    pc = _load(PC_PATH)
    acct = _load(ACCT_PATH)

    sim_equity = float(acct.get("rules", {}).get("start_balance", 15000.0))

    # LOCAL real-equity override (never mirrored). Only the *number* is used for
    # contract counts; no real $ is ever written to the output.
    equity_basis = "SIMULATED_paper_15k"
    equity = sim_equity
    if os.path.exists(LOCAL_EQUITY_PATH):
        try:
            loc = _load(LOCAL_EQUITY_PATH)
            if isinstance(loc.get("real_equity"), (int, float)):
                equity = float(loc["real_equity"])
                equity_basis = "LOCAL_real_equity (number used; $ NOT mirrored)"
        except Exception:
            pass

    setups = []
    for key, s in pc.get("eligibility", {}).items():
        pf = s.get("pf")
        payoff = s.get("payoff")
        n = s.get("n")
        W = derive_win_rate(pf, payoff)
        if W is None:
            continue
        exp_R = expectancy_R(W, payoff)
        kelly = kelly_fraction(W, payoff)
        dollars_R = dollars_per_R(s, exp_R)
        d = s.get("dollar") or {}
        tpw = d.get("trades_per_week") or 0
        n_year = max(50, min(500, round(tpw * 52))) if tpw else 100

        # P(ruin) at the 1% and 2% rules + at max-safe
        sizings = {}
        for label, frac in (("conservative_1pct", 0.01), ("standard_2pct", 0.02)):
            p, med, p5 = monte_carlo_ruin(W, payoff, frac, n_year)
            sizings[label] = {
                "risk_per_trade_pct": round(frac * 100, 2),
                "implied_contracts": contracts_for(frac, equity, dollars_R),
                "p_ruin": p,
                "median_year_return_pct": med,
                "worst_5pct_year_return_pct": p5,
            }
        ms_frac, ms_p = max_safe_risk(W, payoff, n_year)
        p, med, p5 = monte_carlo_ruin(W, payoff, ms_frac, n_year) if ms_frac > 0 \
            else ({f"p_hit_-{b}pct": 0.0 for b in DD_BANDS}, 0.0, 0.0)
        sizings["max_safe"] = {
            "risk_per_trade_pct": round(ms_frac * 100, 2),
            "implied_contracts": contracts_for(ms_frac, equity, dollars_R),
            "p_ruin": p,
            "median_year_return_pct": med,
            "worst_5pct_year_return_pct": p5,
            "note": f"largest risk-per-trade keeping P(hit -{MAX_SAFE_DD}%) < "
                    f"{int(MAX_SAFE_P*100)}% over ~{n_year} trades/yr",
        }

        # Kelly band — full Kelly flagged too-hot by policy
        kelly_band = None
        if kelly is not None:
            kelly_band = {
                "full_kelly_pct": round(kelly * 100, 2),
                "full_kelly_flag": "TOO VOLATILE — do not use full Kelly; "
                                   "drawdowns are brutal. Use 1/4-Kelly.",
                "half_kelly_pct": round(kelly * 50, 2),
                "quarter_kelly_pct": round(kelly * 25, 2),
                "recommended": "quarter_kelly",
            }

        setups.append({
            "setup": key,
            "instrument": d.get("instrument"),
            "n": n,
            "n_status": "DESCRIPTIVE (n<30, not validated)" if (n or 0) < 30
                        else "n>=30",
            "win_rate_derived": round(W, 4),
            "win_rate_source": "DERIVED W = PF/(PF+payoff)",
            "payoff": payoff,
            "pf": pf,
            "expectancy_R": round(exp_R, 4),
            "positive_edge": exp_R > 0,
            "dollars_per_R_per_contract": dollars_R,
            "trades_per_week": tpw,
            "mc_horizon_trades": n_year,
            "kelly": kelly_band,
            "size_band": sizings,
            "eligible_in_constructor": s.get("eligible", False),
        })

    # sort: eligible + positive edge first, then by expectancy_R
    setups.sort(key=lambda x: (x["eligible_in_constructor"], x["positive_edge"],
                               x["expectancy_R"]), reverse=True)

    out = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "kind": "risk_model_sizing_and_ruin",
        "dispatch": "44 / Phase 1A",
        "banner": "ADVISORY / SIMULATED — not financial advice. The edge is "
                  "IN-SAMPLE; size to SURVIVE the drawdown it will inevitably "
                  "have, not to maximise the backtest. Full Kelly is flagged "
                  "too-hot by policy — use 1/4-Kelly. Hany sizes + executes.",
        "equity_basis": equity_basis,
        "equity_used_is_simulated": equity_basis.startswith("SIMULATED"),
        "method": {
            "win_rate": "DERIVED W = PF/(PF+payoff) (no re-measure)",
            "kelly": "f* = W - (1-W)/payoff; fractional = 1/4 & 1/2 f*",
            "sizing": "risk_per_trade% x equity / ($/R per contract) = contracts",
            "risk_of_ruin": f"seeded Monte-Carlo ({MC_SIMS} sims, seed {MC_SEED}), "
                            f"fixed-fractional, P(worst drawdown >= band) over a "
                            f"year of trades",
            "max_safe": f"largest risk% with P(hit -{MAX_SAFE_DD}%) < "
                        f"{int(MAX_SAFE_P*100)}%",
        },
        "n_setups": len(setups),
        "setups": setups,
        "privacy": "Real equity (if set via real_equity.local.json) is used only "
                   "to compute contract counts; NO real $ is written here. The "
                   "equity shown/used by default is the SIMULATED $15k paper "
                   "account, already public.",
    }

    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=2)
    return out


if __name__ == "__main__":
    res = build()
    # console summary for validation
    print(f"risk_model.json written: {res['n_setups']} setups, "
          f"equity_basis={res['equity_basis']}")
    for s in res["setups"][:3]:
        k = s["kelly"] or {}
        ms = s["size_band"]["max_safe"]
        print(f"\n{s['setup']}  n={s['n']} ({s['n_status']})")
        print(f"  W(derived)={s['win_rate_derived']}  payoff={s['payoff']}  "
              f"expR={s['expectancy_R']}")
        print(f"  full Kelly={k.get('full_kelly_pct')}% [FLAGGED] · "
              f"1/4-Kelly={k.get('quarter_kelly_pct')}%")
        for lab in ("conservative_1pct", "standard_2pct", "max_safe"):
            b = s["size_band"][lab]
            print(f"  {lab:18s} risk {b['risk_per_trade_pct']}%  "
                  f"~{b['implied_contracts']} contr  "
                  f"P(-20%)={b['p_ruin']['p_hit_-20pct']} "
                  f"P(-50%)={b['p_ruin']['p_hit_-50pct']}")
