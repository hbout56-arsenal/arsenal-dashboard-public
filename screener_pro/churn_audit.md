# Churn (dollar-volume) audit — where the scan penalizes *share* volume

**Dispatch:** rsi5-churn-2r · item #2 (audit leg) · **REPORT ONLY — no scan logic changed.**
**Scope of this repo:** `screener_pro/enhanced_filters.py` is the reference/spec
implementation of the pre-registered ENHANCED filter stack (NOT loaded into the live
engine). This audit covers that stack's volume logic. The live-engine screener and its
per-name scan output are generated in the engine repo and are not present here, so this
is a **logic-level** audit plus a runnable verdict-flip demonstration, not a universe run.

## Principle (logged)
> **Volume × Price = Value.** 10M shares × $100 and 5M shares × $200 both move $10B —
> the same dollars change hands. Declining **share** volume into a **rising** price is not
> inherently bearish; **churn** (dollar volume) is what actually measures the money moving
> through the tape. A rising, thinning-*share*-volume name should not be labeled
> "weakening" when the *dollars* traded are flat or rising.

## Every place the stack touches volume

| filter | role | volume metric today | churn-sensitive? | verdict changes under churn? |
|---|---|---|---|---|
| `f_volume_breakout` | **GATE** | **SHARE** vol: entry bar ≥ 1.40× trailing-50 avg **shares** | **YES** | **YES — this is the one gate that can flip** |
| `f_vcp` | ranking/informational (not in `enhanced_pass` gates) | **SHARE** vol dry-up: pivot 5-bar ≤ 0.85× base **shares** | YES | reads differently, but **non-gating** (informs rank only) |
| `f_liquidity` | GATE | **DOLLAR** vol: 50-bar avg `close×volume` ≥ $20M | already churn | **NO — already dollar-volume** |
| `f_trend_template`, `f_not_extended`, `f_rs_rank` | gate/gate/rank | no volume input | — | no |

**Bottom line:** exactly **one gate — `f_volume_breakout`** — would change verdicts if churn
were substituted for share volume. `f_liquidity` is *already* churn-based (no change).
`f_vcp`'s dry-up test also reads differently on churn, but it does not gate `enhanced_pass`
(it informs ranking), so it flips *rank*, not *pass/fail*.

## The mislabel case, demonstrated (runnable)

A name in a clean uptrend whose **share** volume thins into a higher price, while the
**dollars** traded hold near their norm. Reproduce with the block in
`churn_audit_demo` (values below are the actual run output):

```
entry price          : 132.89
entry SHARES         : 900,000   (50-bar avg 1,000,000)
SHARE  mult vs avg50 : 0.90x   -> f_volume_breakout PASSED=False  [vol 0.90x avg]
DOLLAR mult vs avg50 : 1.04x   (dollars traded are slightly ABOVE the 50-bar norm)
churn 20d %chg       : -2.0%   share 20d %chg: -9.5%
f_liquidity ($-vol)  : PASSED=True  [ADV $115.3M]
```

`f_volume_breakout` demotes this name ("no breakout thrust — 0.90× avg shares") while the
**dollars changing hands are 1.04× the 50-bar norm**. Under a churn reading the same bar is
at-to-above its dollar norm. That is the verdict flip: **share-volume logic says weak,
churn says normal-to-firm.**

## New display surface (added, non-gating)

`enhanced_filters.py` now exposes churn as **display fields only** (they gate nothing and
do not vote), anti-look-ahead like every primitive (read `bars[0..i]` only):

- `dollar_volume(bar)` = `close × volume`
- `dollar_volume_avg(bars, i, n=20)` — trailing 20-bar avg churn
- `dollar_volume_pct_change(bars, i, n=20)` — today's churn vs its 20d avg, %
- `share_volume_pct_change(bars, i, n=20)` — the share-volume analogue, for side-by-side
- `churn(bars, i, n=20)` — the column dict, incl. `thinning_shares_stable_churn`
  (True when share %chg < 0 ≤ dollar %chg — exactly the mislabel case)

Purpose: show churn **next to** share volume so the `f_volume_breakout` demotion above is
visible as a share-vs-dollars divergence rather than an unexplained "weak volume" tag.

## Recommendation (NOT applied — report-only per dispatch)
`f_volume_breakout` is a **pre-registered, frozen** threshold. Switching it from share to
dollar volume is a **new pre-registration** (counts against the ÷N haircut), not a tune —
do it in the engine repo under a fresh prereg, tracked forward vs the current share-volume
control. This audit changes **nothing**; it surfaces the one gate that would move and ships
the churn column beside it.
