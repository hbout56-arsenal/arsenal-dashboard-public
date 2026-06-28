# Dispatch 50 — Screener pro-filters R&D (REVIEW BUNDLE · NOT LOADED)

Build-don't-load bundle. Nothing here is wired into the live dashboard or engine.
`SIMULATED / advisory.`

| file | what it is |
|---|---|
| `STEP1_current_criteria.md` | READ-FIRST report: current screener criteria (observed) + pro-filter gap matrix (present vs MISSING). Notes the engine source files aren't in this repo. |
| `PREREGISTRATION.md` / `preregistration.json` | STEP 2: the 7 enhanced filters frozen with thresholds, ÷N=8 haircut, ship rule. |
| `enhanced_filters.py` | Reference implementation (pure-Python, anti-look-ahead). Run `python3 screener_pro/enhanced_filters.py` → self-test proves no look-ahead leak. NOT loaded. |
| `raw_vs_enhanced.md` | STEP 3/4: RAW vs ENHANCED ablation, the one real forward finding (no-chase), survivorship/forward caveats, ship/don't-ship verdict. |
| `MD5SUMS.txt` | checksums of the bundle. |

## Bottom line
- **Verdict: ship one, defer the rest, load nothing.** Filter 5 (NOT-EXTENDED /
  no-chase) is the only filter with real forward evidence — `at_market` (−8.92%,
  n=105) vs `pullback` (−0.04%, n=291) = **+8.88 pts/trade, survives ÷8 haircut**.
  Its mechanism already exists in the engine; harden it to an exclusion gate.
- Filters 1–4, 7 + full stack: **DEFERRED** — no per-pick feature ledger exists to
  tag RAW vs ENHANCED; verdict waits for n≥30 ENHANCED-pass forward picks.
- Filter 6 (earnings): **DEFERRED — no fundamentals feed.** Not fabricated.
- A day-0 forward-OOS verdict for the deferred filters is impossible by
  construction — pre-register now, tag forward, decide at n≥30. That null is valid.
