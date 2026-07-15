# MGC inside-bar FORWARD test — pre-registration  ·  **TEMPLATE, NOT FROZEN**

> **STATUS: TEMPLATE / UNLOCKED.** This is **not** the pre-registration. The verbatim
> rule freeze (Part 1) is authored **on the Mac**, where `inside_bar_engine.py` lives —
> it is not in this public mirror, so no verbatim dump can be produced here. Fill §1
> from the real engine, change the title to `FROZEN <date>`, delete this banner, save
> as `~/arsenal/ledgers/mgc_inside_bar_prereg.md`, then commit to the private backup
> repo. **Nothing in §1 may be tuned after that commit.**
>
> Everything below §1 is transcribed straight from the dispatch and is engine-source
> independent — it is ready to lock as-is.

## Honesty header (lock verbatim)

The in-sample GC_RAW sample (**n=71 matured**, exp **+63.67 net pts**, PF **7.05**,
win **74.6%**, CI **[32.3, 102.4]**, max_dd **−220.8 pts**) lived through a **single
gold bull regime**. Raw-beats-filtered here is an inversion of the system's usual
prior. This test exists **to see if the pattern survives outside that regime** — not to
confirm it. RAW is the control track; the dashboard's own note flags "raw inside bars
are NULL." Descriptive until the gates below clear.

## §1 — FROZEN RULE DUMP  ·  **TODO on the Mac (verbatim from `inside_bar_engine.py`)**

Copy the GC_RAW rule **exactly as the engine computes it today** — no paraphrase, no
tuning. Fill every field:

- [ ] **Bar / inside-bar definition** — exact inequality (incl. equal-extreme handling).
- [ ] **Timeframe** — operator-confirmed **daily**; confirm against the engine.
- [ ] **Entry trigger** — stop-entry on break of inside-bar high (long) / low (short)?
      Confirm buffer/tick offset, if any.
- [ ] **Stop** — structure (opposite side of the inside bar)? exact rule.
- [ ] **Target(s)** — T1 / T2 rule (the sentinel currently uses a **PROVISIONAL 1R**
      placeholder — replace with the engine's real target math).
- [ ] **Session filter** — RTH / ETH? bar-close timing?
- [ ] **Exclusions** — any bars/days the engine skips.

> Until §1 is filled from source, the sentinel's coded geometry (definition, trigger,
> structural stop) mirrors the dashboard's stated setup, but the **target is a
> placeholder** and the freeze is **not valid**.

## §2 — Instrument & costs (ready to lock)

- Instrument: **MGC** (micro gold), **1 unit**, **stop-defined risk**.
- Costs: commissions **+ 1 tick (0.1 pt) slippage**, applied by the nightly labeler
  before `net_points` is written to the ledger.

## §3 — Start & direction (ready to lock)

- **Start date = first RTH after this file is committed** to the private backup repo.
- **FORWARD ONLY. No backfill.** Forward series is never blended with the in-sample.

## §4 — Gates (ready to lock)

**VALIDATED** only when **all three** hold:
1. **n ≥ 30** closed (matured) forward trades, AND
2. **bootstrap CI (1500×, net points) excludes 0**, AND
3. **forward expectancy ≥ 50% of the in-sample +63.67** → **≥ +31.835 net pts**.

Anything short of all three = **DESCRIPTIVE** — informational, **never sized**.

## §5 — Kill criteria (ready to lock; honor later)

- **Forward expectancy negative at n ≥ 30**, OR
- **max drawdown worse than 2× in-sample −220.8** → **< −441.6 net pts**.

On either: **track RETIRED**, logged as a **regime-capture confirmation** — *not*
"needs tuning."

## §6 — Regime tag per trade (ready to lock)

Record GC trend/vol state **at entry**, anti-look-ahead: **side of daily EMA50**
(above/below) **+ 20-day realized-vol bucket** (low <0.15 · mid · high ≥0.30
annualized). Lets a post-hoc read separate "edge" from "gold went up."

## §7 — Multiple-comparison honesty (ready to lock)

This is one more track in a family already flagged HIGH multiple-comparison risk
(14 inside-bar cells + the candle-pattern grid). It is **NON-VOTING** and does not get
sized on its own significance; the gates above are the only path off DESCRIPTIVE.

---
*Enforcement of §4–§6 is implemented in `sentinel/mgc_inside_bar_scorer.py`
(IN_SAMPLE_EXP=63.67, VALIDATION_EXP_FLOOR=31.835, KILL_MAXDD=−441.6, MIN_N=30,
BOOT_ITERS=1500). Detection is `sentinel/mgc_inside_bar_sentinel.py` (DISABLED).*
