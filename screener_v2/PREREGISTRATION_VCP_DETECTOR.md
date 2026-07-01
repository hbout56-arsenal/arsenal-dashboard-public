# VCP contraction-detector — method pre-registration (FROZEN 2026-06-30)

Machine-readable source of truth: **`preregistration_vcp_detector.json`**
(detector id **`zigzag_vcp_prereg_2026-06-30`**). This page is the human summary.
`SHADOW — educational, forward-validating, not a live signal.`

## What this freezes (and what it does NOT)

Freezes the **contraction-DETECTION method** — the piece the D50 pre-registration
left under-specified (D50 froze only the VCP *thresholds*). It does **NOT** touch
those thresholds (`min_contractions=2`, `tightness 0.75`, `dry-up 0.85`,
`base-depth ≤35%`) — they stay owned/frozen by `screener_pro/preregistration.json`.

| method parameter | frozen value | picked by principle |
|---|---|---|
| swing reversal | **5.0%** | codebase daily-bar VCP convention (`filters.py VCP_ZZ_PCT`, "meaningful daily swing"); ≥2-contraction / ≤35%-deep base swings sit above 5%; Elliott's finer 3% would re-over-segment |
| base window | **60 bars** | ~1 quarter = min VCP base proxy; matches D50 i-60; ≥25 bars (~5wk) required before a read |
| max contractions (T) | **6** | Minervini VCP T-count is small (2–4, up to ~6); >6 swings = choppy range, not a coiling base |
| pivot / buy-point | highest swing high in base (max high over last 40 bars) | reuses existing `_base_levels`; breakout reference |
| base-low / stop | lowest low **from the pivot forward** (consolidation low under the pivot) | structural stop, not a stale multi-month low |

**Anti-look-ahead:** detector reads `bars[0..signal_index]` only.
**Haircut:** N = 4 (3 method knobs ablated individually + full method); in-sample
edge ÷N before any "survives" claim. This is a **new pre-registered decision** and
re-incurs the ÷N haircut. The reversal knob spans the {3,4,5}% codebase-plausible
range (count swings ~0–4) → any in-sample edge is further discounted for that DOF.

## Why this supersedes `zigzag_v1_prereg_2026-06-29` (the 4% doc)

The prior `vcp_method_prereg.json` was **wrong on three counts**, so it is superseded:

1. **Inconsistent with the engine.** It froze `swing_reversal_pct = 4.0`, but the
   engine (`filters.py VCP_ZZ_PCT`) has run at **5.0** since it was built and
   produced **every** forward pick (FTEC, AIRR) at 5% — while falsely stamping that
   output with the 4% detector id. The 4% value was never in effect.
2. **Post-hoc contaminated.** It embedded a result (`first_qualifier = FTEC`), so it
   was written *after* seeing the outcome — not a clean pre-registration.
3. **Incomplete.** It froze only reversal + base window, not the max-T count or the
   pivot/base_low anchoring.

This freeze **ratifies the value the engine actually computes (5%)** and **completes**
the spec. It does **not** change any realized pick's math — so prior 5%-computed
forward picks stay valid and comparable; only the pre-registration is now correct.

## Selection integrity

Values chosen by **principle**, not to hit a count. Disclosure: the funnel count at
5% is a knife-edge of ~**1** name (unflattering) — evidence the choice was **not**
tuned to manufacture picks. Reported as-is; nothing is promoted to live.

## Monitor, do NOT tune

Recent survivors (FTEC, AIRR) are correlated tech-sector ETFs; single stocks rarely
clear the VCP stage. If single stocks ~never qualify under the frozen method across
weekly runs, a loosening would be a **separate pre-registered decision** with its own
forward series — never a quiet tweak.
