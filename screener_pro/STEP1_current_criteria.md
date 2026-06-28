# Dispatch 50 — STEP 1: current screener criteria + pro-filter gap analysis (READ-FIRST)

**Status: REPORT ONLY. Nothing changed. Nothing loaded.** `SIMULATED / advisory.`

---

## 0. Scope honesty — what this repo actually contains

The dispatch asks me to "read `tictoc_screener.py` + `minervini_scanner.py` +
`universe_scan.py`." **Those source files are not in this repository.** This repo
(`arsenal-dashboard-public`) is the *public dashboard mirror* — it carries the
JSON artifacts the engine emits plus the `risk/` modules, not the screener engine
itself. I will not pretend to quote code I cannot see.

What I *can* do honestly: reconstruct the screener's **observable** behaviour from
the artifacts it writes (`stock_dashboard.json`, `pick_asymmetry.json`,
`scorecard_summary.json`, the section taxonomy, the pillar/score/note fields). That
reconstruction is below, labelled as inference where it is inference.

> **If you want the literal code-level criteria audited, point me at the repo/path
> that holds `minervini_scanner.py` et al. and I'll redo STEP 1 against the source.**

---

## 1. What the current screener gates / scores on (observed)

The engine emits **five sections**, each with an `engine_top5` (raw engine output)
and a `curated` list (Claude-curated subset):

| section | what it surfaces (observed) |
|---|---|
| `convergence` | multi-pillar agreement (`pillars: "tictoc+elliott"`). Top-5 all `score 90`, `conviction HIGH`. |
| `minervini` | trend-template names. Notes carry a **`Minervini ***93%`** match score. |
| `top_setups` | engine's highest-scored discretionary setups |
| `tic_toc_watchlist` | tictoc-pillar levels (often "nothing actionable" when names sit between triggers) |
| `universe_scan` | wide-universe scan (empty in the current snapshot) |

**Scoring / gating actually observed:**

- **Composite score 0–100** on `engine_top5` (`score`), with **conviction tiers**
  and scorecard **thresholds at `70 / 85 / 100`** (`scorecard_summary.json`).
- **Pillar tags** drive the sections: `tictoc`, `elliott`, `tictoc+elliott`
  (convergence = ≥2 pillars).
- **Minervini match is a *percentage score*** (`***93%`), **not a hard binary
  gate** — a 93% means something in the template is failing yet the name still
  surfaces. (Inference from the note string; this is the key STEP-2 target.)
- **Entry-type split**: every pick is later bucketed `at_market` vs
  `pullback_limit` (the anti-chase entry already exists as an *alternative*, but
  extended names are **not rejected** — 105 `at_market` forward picks exist).
- **Maturation / honesty gates**: `MIN_TRIGGERED = 20`, `MIN_MATURED = 30`; stats
  on **independent setups only** (dedup `entry_tol 0.25 pts`, `window 2 bars`).
- **Profit lens**: expectancy / PF / payoff lead; win% is a footnote
  (`pick_asymmetry.json`). RAW STRONG_LONG forward = **exp −2.40%, PF 0.43, n=396**.

---

## 2. Pro-filter gap matrix — already-present vs MISSING

The seven candidate filters vs what the screener demonstrably already does:

| # | Pro filter (Minervini/O'Neil/Zanger/CANSLIM) | Status | Evidence / note |
|---|---|---|---|
| 1 | **Hard trend template** (px>50>150>200, all rising, 200 rising ≥1mo) — *gate* | **PARTIAL** | Minervini section exists but match is a **score (93%), not a hard gate**. Harden to binary. |
| 2 | **VCP** (successive shallower pullbacks + volume dry-up) | **MISSING** | No contraction/dry-up field anywhere. Highest-value add. |
| 3 | **Volume breakout confirmation** (entry vol ≥ 1.4× avg) | **MISSING** | No breakout-volume field surfaced. |
| 4 | **RS *ranking*** (top decile vs SPY, not just "strong enough") | **MISSING / PARTIAL** | Minervini implies an RS line, but **decile ranking of the survivor set is not evidenced** — it filters, doesn't rank-and-cut. |
| 5 | **NOT-EXTENDED exclusion** (no chasing: ATR-above-pivot / RSI-pinned / far from 50MA) | **PARTIAL → key gap** | Pullback *entry* exists, but extended/`at_market` names are **not rejected**. The exclusion itself is MISSING. |
| 6 | **Earnings/growth overlay** (CANSLIM: accel EPS/rev + surprise) | **MISSING → DEFER** | No fundamentals in artifacts; needs a feed. **Flagged deferred, not fabricated.** |
| 7 | **Liquidity floor** (min avg-dollar-volume) | **MISSING / unknown** | No ADV floor evidenced. |

**Headline:** the screener already has composite scoring, pillar convergence, a
Minervini *score*, and an alternative pullback entry. It is **missing every
purpose-built exclusion/quality filter** (VCP, volume-confirm, RS-rank-to-decile,
not-extended *rejection*, liquidity floor), and its trend template is a soft score
rather than a hard gate. Per the dispatch thesis, the **exclusion filters (5, 7)
are the most likely to carry lift** — and §STEP 3 shows the existing forward ledger
already supports that for filter 5.

→ Proceed to **PREREGISTRATION.md** (filters frozen before any results).
