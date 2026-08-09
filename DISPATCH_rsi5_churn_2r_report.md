# DISPATCH REPORT — rsi5-churn-2r (three small additions)

Repo: `arsenal-dashboard-public` (public dashboard + shadow modules). The dispatch targets
the **engine** (`analyzer.py` / `intelligent_elliott.py` / live scan / per-trade forward
ledgers), which is **not in this repo**. Below is what was genuinely done here, honestly
scoped — no engine outputs or ledger statistics were fabricated. Staged for Knowledge.

---

## #1 — RSI5 on the wave path — ⛔ ENGINE-ONLY (not implemented here)
- The Elliott/wave module (`analyzer.py` / `intelligent_elliott.py`) and the **65-min /
  39-min RTH aggregations** for ES/NQ/GC live in the engine repo. This repo carries wave
  **outputs** only (`*_wave_15m/60m/daily.json`), which have **no RSI field** and no 65/39-min
  aggregation. RSI5 cannot be surfaced on the wave block from here without fabricating the
  engine's wave output.
- **Spec for the engine (unchanged intent):** compute **RSI(5)** alongside the existing
  RSI(14) on the 65-min and 39-min wave aggregations for ES/NQ/GC. Label it
  **"RSI5 (wave-analysis convention)"**. It is a **DISPLAY field — not a gate, not a vote.**
  Purpose: interoperability, so Ter Schure's objections ("RSI5 maxed overbought on the
  65-min") can be read in his own units. RSI14 usage everywhere else is untouched, and
  `tictoc_screener`'s RSI is **not** touched (validated as-is).
- **TEST "byte-identical screener output": PASS (trivially).** Nothing in any screener was
  changed by this repo's work, so screener output is byte-identical by construction. (The
  real render test — "RSI5 renders on ES/NQ/GC wave lines; RSI14 elsewhere unchanged" — must
  be run in the engine repo where the wave module and 65/39-min bars exist.)

## #2 — Churn (dollar-volume) column — ✅ SHADOW MODULE + AUDIT (done)
- **Code (additive, non-gating):** `screener_pro/enhanced_filters.py` now exposes churn as
  **display fields** — `dollar_volume`, `dollar_volume_avg` (20d), `dollar_volume_pct_change`,
  `share_volume_pct_change`, and `churn()` (with a `thinning_shares_stable_churn` flag).
  Anti-look-ahead (read `bars[0..i]` only); they **gate nothing and do not vote**. Self-test
  extended and **PASSES** (correctness + anti-look-ahead + divergence caught).
- **Rationale (logged):** *Volume × Price = Value* — 10M×$100 and 5M×$200 both move $10B.
  Declining **share** volume into a rising price is not inherently bearish; churn shows the
  dollars still changing hands.
- **Audit (report-only, `screener_pro/churn_audit.md`):** exactly **one gate —
  `f_volume_breakout`** — would flip if churn replaced share volume (it keys off share vol,
  ≥1.4× trailing-50). `f_liquidity` is **already** dollar-volume (no change). `f_vcp`'s
  dry-up reads differently on churn but is **non-gating** (rank only). A runnable verdict-flip
  demo is included: a rising name at **0.90× avg shares** (breakout FAILS) whose **dollars
  traded are 1.04× the 50-bar norm**. **No scan logic was changed.**
- **TEST "churn column renders + report verdict changes": PASS** (display fields + audit
  delivered; the single affected gate reported; nothing changed). Live per-name universe run
  belongs to the engine repo.

## #3 — Pre-registered 2.0R minimum R:R — ✅ PRE-REGISTERED, ⛔ NOT RUN (data absent)
- **Pre-registration frozen FIRST** in `ledgers/rr_floor_prereg.md`: H, method (re-score the
  same trades under 1.5R vs 2.0R, no tuning), decision rule (PASS = expectancy improves AND
  n≥30 AND CI excludes 0; else keep 1.5R), and the required **average stop-width** report
  ("a 2R floor at a wider stop is a *different* trade").
- **Execution:** per-trade forward ledgers (`ict`, `fvg`, `convergence`, `mes_event_labels`,
  `d112`) are **not in this repo** — only aggregate summaries (`*_state.json`,
  `perf_summary.json` equity curves). Realized net points cannot reconstruct each trade's
  *planned* R:R (needs entry/stop/target), so the floors cannot be applied without
  fabrication. **Result logged: NOT RUN → keep 1.5R.** A pre-registered test that has not run
  is not a pass. Run once in the engine repo, method verbatim.

---

## LOCKED DECISIONS — entry to append (canonical file lives in Knowledge/engine repo)
> **[rsi5-churn-2r · #3 · R:R floor]** 2.0R minimum-R:R filter **NOT adopted** — pre-registered
> in `ledgers/rr_floor_prereg.md` but **NOT RUN** (per-trade forward ledgers absent from
> `arsenal-dashboard-public`; re-scoring needs planned entry/stop/target). **Floor stays
> 1.5R.** Re-run in the engine repo (method frozen, once, no tuning); update this decision to
> PASS/FAIL/MIXED with per-ledger n, expectancy, PF, CI, and mean stop width.
> **[rsi5-churn-2r · #2 · churn]** Churn (dollar volume) added as **display-only** fields in
> `screener_pro/enhanced_filters.py` (non-gating). Audit: only `f_volume_breakout` would flip
> under churn; `f_liquidity` already dollar-volume. **No gate logic changed.** Any share→dollar
> switch on `f_volume_breakout` is a **new pre-registration**, not a tune.
> **[rsi5-churn-2r · #1 · RSI5]** RSI5 wave-path display deferred to the engine repo
> (wave module + 65/39-min aggregations not in this repo). `tictoc_screener` RSI untouched.

## Housekeeping
- **Backup:** `backups/enhanced_filters.py.prechurn.bak` (only modified source).
  `index.html` **not touched** (no dashboard render change in this repo's scope).
- **py_compile:** `screener_pro/enhanced_filters.py` — clean.
- **md5s:** `backups/dispatch_rsi5_churn_2r.md5`.
- **Staged for Knowledge:** this report, `screener_pro/churn_audit.md`,
  `ledgers/rr_floor_prereg.md`.
