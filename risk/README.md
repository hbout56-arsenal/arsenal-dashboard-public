# Risk & Survival layer (Dispatch 44)

Closes the gap between Arsenal's edge-**discovery** (is there an edge?) and
capital-**survival** (how do I size/limit/sequence it so I don't blow up while
harvesting it?). **All ADVISORY / SIMULATED — not financial advice. Hany decides
+ executes.** Nothing here changes a signal or the engine; these are new
*computed views* + advisory alerts.

> **Not loaded.** These views are generated to the repo root but are **not** wired
> into `index.html` — load them only after review (matches the dispatch). The
> dashboard regression guard holds because `index.html` is untouched.

## Modules (`risk/`)

| Phase | Script | Output (repo root) | What it does |
|------|--------|--------------------|--------------|
| 1A | `risk_model.py` | `risk_model.json` | Kelly + ¼/½-Kelly (full Kelly flagged too-hot), 1%/2% sizing, **Monte-Carlo risk-of-ruin** at −20/−25/−50%, **max-safe size** (P(−25%)<5%). |
| 1B | `loss_limits.py` | `loss_limits.json` | Daily / consecutive-loser / weekly circuit breakers. Fires a loud alert + logs a **discipline breach** when hit (cannot force-flatten). |
| 2A | `portfolio_heat.py` | `portfolio_heat.json` | Live total open risk + **correlation-adjusted** heat (3 correlated longs ≈ one 3× bet). GREEN/AMBER/RED meter. |
| 2B | `edge_by_regime.py` | `edge_by_regime.json` | Expectancy × regime (D39) cross-tab — reveals **conditional** edge (setup × regime). |
| 3A | `pretrade_checklist.py` | `pretrade_checklist.json` | Enforced pre-trade checklist; auto-checks limits/heat/regime. Skipping = discipline ding. |
| 3B | `slippage.py` | `slippage.json` | Expected-vs-actual fills → per-trade slippage + annual execution drag. |
| 3C | `mae_mfe.py` | `mae_mfe.json` | MAE/MFE aggregates — **DEFERRED** until per-trade intraday excursion data is cached (not fabricated). |

Run all: `bash risk/run_risk_layer.sh`

## Reused inputs (read-only)
`portfolio_constructor.json` (D40/D41 validated candidates — win rate derived as
`W = PF/(PF+payoff)`), `account_summary.json` (SIMULATED $15k equity),
`regime_label.json` (D39). MC mirrors the backtest engine's resampling approach
(seeded → reproducible).

## Privacy
Real equity, real open positions, and the live trade journal stay **LOCAL** and
are **never mirrored** (`*.local.json`, gitignored):
`real_equity.local.json`, `journal.local.json`, `positions.local.json`,
`execution.local.json`, `excursions.local.json`, `trade_intent.local.json`,
`loss_limits_config.local.json`. The mirrored `*.json` views carry only
percentages, R-multiples, contract counts, and SIMULATED micro-$ — **no real
account $**. Scripts may *read* the local real-equity number to compute contract
counts, but never emit it. The committed `*.sample.json` files are synthetic.
