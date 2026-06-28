# Dispatch 50 — STEP 3/4: RAW vs ENHANCED ablation + the honest verdict

`SIMULATED / advisory · expectancy-led (win% is a footnote) · FORWARD never blended
with HISTORICAL · n<30 DESCRIPTIVE · nothing loaded.`

---

## 0. The data-availability wall (read this first)

A real RAW-vs-ENHANCED ablation needs a **per-pick ledger with the underlying
features** (per name: MA structure, RS-vs-SPY, VCP contraction, breakout volume,
ATR-extension, dollar-volume) so each forward pick can be tagged RAW-pass vs
ENHANCED-pass. **That ledger does not exist in this repo.** What exists:

- `pick_asymmetry.json` — forward stats **aggregated by bucket/sub-bucket** only.
- `swing_account_sim.json` — equity curves (`date, balance`), no per-name features.
- No OHLCV, no per-pick feature rows anywhere.

So I **cannot fabricate** a 7-filter ablation table with invented per-pick numbers —
that would violate every guardrail in this dispatch. What I *can* do honestly:

1. Read the **one filter the existing forward ledger already speaks to** (filter 5,
   not-extended) — real n≥30 forward evidence.
2. Pre-register the rest and build the anti-look-ahead logic, then **defer** their
   verdict until forward tagging accumulates n≥30. A forward-OOS verdict on day 0
   is impossible by construction — you pre-register, then you *wait*.

---

## 1. Filter 5 (NOT-EXTENDED) — REAL forward evidence, already in the ledger

The forward STRONG_LONG book is already split by entry type. `at_market` ≈ chasing
an extended name; `pullback_limit` ≈ the not-extended cohort. **Both are n≥30
FORWARD** (not historical, not survivorship-rescued):

| cohort | n | expectancy | PF | payoff | win% |
|---|---:|---:|---:|---:|---:|
| **RAW** STRONG_LONG (blended) | 396 | **−2.40%** | 0.43 | 0.8 | 35.1 |
| └ `at_market` (chase / extended) | 105 | **−8.92%** | 0.09 | 0.48 | 15.2 |
| └ `pullback_limit` (not-extended) | 291 | **−0.04%** | 0.98 | 1.34 | 42.3 |

- **Forward expectancy gap = +8.88 pts/trade** for avoiding the chase (both n≥30).
- **÷N haircut (N=8): +8.88 → +1.11 pts/trade — still strongly positive. Survives.**
- Excluding the `at_market` cohort lifts the **blended RAW expectancy −2.40% →
  −0.04% (+2.35 pts)** — i.e. the entire net bleed of the swing book is the chase.
  Not quite positive, but at breakeven instead of deeply negative.

This is the dispatch's own thesis confirmed by real forward data: **the quality of
*rejection* carries the lift.** Filter 5 is the carrier.

> Caveat — this is the *entry-type* proxy for "extended," not the full pre-registered
> rule (ATR-above-pivot / RSI-pin / %-above-50MA). The proxy and the rule are
> correlated but not identical; the precise-rule verdict still needs forward tagging.
> But directionally, n≥30 forward, haircut-survived: **strong.**

---

## 2. The other six filters — per-filter ablation status

| # | filter | forward data to tag RAW vs ENHANCED? | verdict now |
|---|---|---|---|
| 1 | trend_template (hard gate) | none (no per-pick MA structure) | **DEFERRED** — tag forward |
| 2 | vcp | none (no per-pick base geometry) | **DEFERRED** — tag forward |
| 3 | volume_breakout | none (no per-pick entry volume) | **DEFERRED** — tag forward |
| 4 | rs_rank (top decile) | none (no per-pick RS cross-section) | **DEFERRED** — tag forward |
| 5 | **not_extended** | **YES — at_market vs pullback, n≥30** | **POSITIVE (carrier)** |
| 6 | earnings_growth | n/a — no fundamentals feed | **DEFERRED (no data)** — never fabricated |
| 7 | liquidity | none (no per-pick ADV) | **DEFERRED** — tag forward |

**Full stack:** cannot be measured forward yet (depends on 1–4, 7). DEFERRED.

I will not present an in-sample/historical lift table for 1–4/7: the Minervini
universe has **no point-in-time membership**, so any wide historical stock backtest
is **survivorship-biased** and the dispatch forbids presenting it as proof. The
HISTORICAL_BASELINE buckets (e.g. STRONG_LONG +2.76%) are tagged DESCRIPTIVE and are
**not** used here as evidence for ENHANCED.

---

## 3. Anti-look-ahead proof

`enhanced_filters.py` self-test (run it: `python3 screener_pro/enhanced_filters.py`):

```
SELF-TEST PASS — no look-ahead leak; gates behave; deferred==None (not pass)
```

It evaluates every filter at a mid index `j` on the **full** series and again on the
series **truncated to `j+1` bars**, and asserts identical `(passed, value)`. Any
future-bar reference would change the truncated verdict and fail the assert. It also
confirms `not_extended` rejects a chased name and that deferred filters return
`None` (never a silent pass).

---

## 4. VERDICT — ship / don't-ship

**Does ENHANCED beat RAW forward? — Partly, and only one filter is decided today.**

- ✅ **Filter 5 (not-extended / no-chase): SHIP-WORTHY on forward evidence.**
  +8.88 pts/trade forward gap, n≥30 both cohorts, survives the ÷8 haircut (+1.11).
  **But** the live engine already exposes the pullback entry — the honest action is
  to **harden it into an exclusion *gate* (reject extended/`at_market` names),** not
  to claim a brand-new discovery. This is the at_market bleed we already proved.
- ⏸️ **Filters 1, 2, 3, 4, 7 + full stack: DEFERRED, not shipped.** No per-pick
  feature ledger exists to tag them RAW vs ENHANCED. They are pre-registered and the
  anti-look-ahead logic is built (`enhanced_filters.py`). Verdict waits for **n≥30
  ENHANCED-pass forward picks** once the engine emits the per-pick feature tags.
- 🚫 **Filter 6 (earnings/growth): DEFERRED — no fundamentals feed.** Not fabricated.
- 🚫 **Nothing loaded into the live dashboard/engine.** STEP 4 promotion does not
  trigger for the deferred filters (no forward win yet), and filter 5's mechanism
  already exists.

**Null-finding honesty:** for five of seven filters this dispatch produces *no*
forward result yet — that is the correct, expected state of a pre-registered
forward-OOS test on day 0, **not** a failure. Dead stays dead; undecided stays
undecided. The single real win (no-chase exclusion) was already in the ledger.

### To actually decide the deferred filters (hand-off to the engine)
1. At scan time, run each forward pick through `enhanced_filters.evaluate_stack(...)`
   and store the per-filter `(passed, value)` + `enhanced_pass` flag on the pick row.
2. Accumulate the tagged forward ledger. At **n≥30 ENHANCED-pass**, compute
   ENHANCED vs RAW expectancy per filter and full-stack, apply the ÷8 haircut.
3. Promote only filters that clear RAW forward after the haircut. Keep RAW running
   as the permanent control.
