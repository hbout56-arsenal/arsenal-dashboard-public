# Dispatch 50 — STEP 2: pre-registered ENHANCED filters (FROZEN)

Machine-readable source of truth: **`preregistration.json`**. Reference
implementation (anti-look-ahead, self-tested, **not loaded**):
**`enhanced_filters.py`**. This page is the human summary.

**Frozen 2026-06-28, before any backtest result.** Changing any threshold is a
*new* pre-registration and re-incurs the ÷N haircut. `SIMULATED / advisory.`

| # | filter | role | frozen threshold | prior status |
|---|---|---|---|---|
| 1 | trend_template | GATE | px>50>150>200, 50&200 rising 21d, ≥30% off 52w-low, ≤25% off 52w-high | PARTIAL (soft score) |
| 2 | vcp | RANK+GATE | ≥2 contractions, each ≤0.75× prior, pivot vol ≤0.85× base, base ≤35% deep | MISSING |
| 3 | volume_breakout | GATE | entry vol ≥ **1.40×** 50-bar avg | MISSING |
| 4 | rs_rank | RANK | 126-bar return − SPY, keep **top decile** | MISSING/PARTIAL |
| 5 | not_extended | EXCL GATE | reject >5×ATR14 above pivot **OR** >12% above 50MA **OR** RSI14 ≥ 80 | PARTIAL (key gap) |
| 6 | earnings_growth | DEFERRED | accel EPS/rev + surprise (CANSLIM) | MISSING — needs feed |
| 7 | liquidity | EXCL GATE | 50-bar avg dollar-volume ≥ **$20M** | MISSING |

**ENHANCED-pass** = all four GATES (1, 3, 5, 7) pass. VCP + RS-rank inform
*ranking* of survivors. Earnings (6) is **deferred** — `None`, and `None` never
counts as a pass (proven in the self-test).

**Haircut:** N = 8 (7 filters ablated individually + 1 full stack). In-sample edge
is divided by N before any "survives" claim.

**Anti-look-ahead:** every filter reads `bars[0..signal_index]` only. The self-test
in `enhanced_filters.py` re-evaluates each filter on a *truncated* series and
asserts the verdict at index `i` is byte-identical with/without future bars — it
passes (no leak).

**Ship rule:** promote a filter to live **only** if ENHANCED beats RAW on FORWARD
expectancy after the ÷N haircut at **n ≥ 30 ENHANCED-pass forward picks**.
Otherwise ship nothing; log the null. → see `raw_vs_enhanced.md`.
