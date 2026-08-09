# PRE-REGISTRATION — minimum R:R floor 1.5R → 2.0R

**Dispatch:** rsi5-churn-2r · item #3 · **pre-register FIRST, run ONCE, no tuning.**
**Status of this document:** hypothesis + method are FROZEN below *before* any re-scoring.
**Execution status:** ⛔ **NOT RUN in this repo** — see "Execution" — no numbers fabricated.

---

## Hypothesis (H)
Raising the minimum-R:R entry filter from **1.5R** to **2.0R** improves per-trade
**expectancy** without collapsing sample size.

## Ledgers in scope
Every existing **forward** ledger: `ict`, `fvg`, `convergence`, `mes_event_labels`,
and `d112` (only if populated). RAW control tracks included where they exist.

## Method (frozen — no tuning, no re-fit)
1. For each ledger, take every trade with a recorded **planned entry, planned stop, and
   planned target** (so planned R:R = |target − entry| / |entry − stop| is defined at
   entry, anti-look-ahead). Outcome = realized R at exit under the ledger's existing
   maturation rule.
2. Score the **same** trade set under two floors:
   - **Floor A = 1.5R** (current): keep trades with planned R:R ≥ 1.5.
   - **Floor B = 2.0R** (candidate): keep trades with planned R:R ≥ 2.0.
   Nothing else changes — same entries, same stops, same outcomes; the floor only
   changes which trades **survive** the filter. No thresholds are re-tuned.
3. Per ledger, per floor, report: **n surviving · win% · expectancy · profit factor ·
   bootstrap CI** (percentile bootstrap, 1500× on real per-trade R, matching
   `perf_summary.json`'s `ci_method`).
4. **Also report average stop width under each floor** (see "Different trade" note).

## Decision rule (frozen)
- **PASS** = expectancy improves **AND** n stays ≥ 30 **AND** the expectancy CI excludes 0.
- **FAIL or MIXED** = keep **1.5R**.
- Log the result **either way**. One run. No re-running to a nicer answer.

## "Different trade" note (must be reported)
A 2.0R floor reached by accepting a **wider stop** is a **different trade**, not a stricter
version of the same one: same target with a wider stop = larger risk-per-unit, different
position size, different hold. So the average **stop width** under each floor is a required
output — if Floor B's surviving trades carry systematically wider stops, an expectancy gain
may be a composition change (trade selection), not a quality gain on identical setups.
Report stop-width distribution (mean + median) per ledger per floor alongside expectancy.

---

## Execution
**Re-scoring requires per-trade rows** — each trade's planned entry, stop, target (for the
R:R floor) and realized R (for the outcome. Those rows live in the **engine repo's forward
ledgers**, not in `arsenal-dashboard-public`.

What this repo actually carries (checked 2026-08-09):
- `ict_state.json`, `fvg_state.json` → **aggregate `tracks_summary` only** (n, win%, avg_R,
  PF, net_points) — no per-trade R:R, stop, or target.
- `perf_summary.json` → per-system tracks with **equity curves** (cumulative net_points per
  matured trade) — deltas give realized net points, but **not** each trade's *planned* R:R
  or stop, so trades cannot be sorted into the ≥1.5R vs ≥2.0R buckets.
- `convergence`, `mes_event_labels`, `d112` → **no per-trade ledger files present**.

Realized net points alone cannot reconstruct a trade's *planned* R:R (that needs the stop
and target set at entry), so the two floors cannot be applied here. Running the test on this
repo's data would require **fabricating** entry/stop/target — which the pre-registration
forbids. Therefore:

### Result logged — **NOT RUN (data not in this repo)**
- No expectancy, n, PF, CI, or stop-width numbers are reported, because none can be computed
  without fabrication.
- **Default holds: keep the 1.5R floor.** The 2.0R change is **NOT adopted** — a
  pre-registered test that has not run is not a pass.
- **To execute (engine repo, unchanged method):** load each forward ledger's per-trade rows
  (entry/stop/target/realized-R), apply steps 1–4 verbatim, then fill the results table
  below and update LOCKED DECISIONS with PASS/FAIL/MIXED. Run once.

### Results table (to fill in the engine repo — left blank on purpose)
| ledger | floor | n | win% | expectancy | PF | exp CI | mean stop | median stop |
|---|---|---|---|---|---|---|---|---|
| ict | 1.5R | | | | | | | |
| ict | 2.0R | | | | | | | |
| fvg | 1.5R | | | | | | | |
| fvg | 2.0R | | | | | | | |
| convergence | 1.5R | | | | | | | |
| convergence | 2.0R | | | | | | | |
| mes_event_labels | 1.5R | | | | | | | |
| mes_event_labels | 2.0R | | | | | | | |
| d112 (if populated) | 1.5R | | | | | | | |
| d112 (if populated) | 2.0R | | | | | | | |

_Advisory / SIMULATED. Pre-registration frozen before data; blanks are honest, not omissions._
