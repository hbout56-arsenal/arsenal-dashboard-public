# Dispatch 54 — Pro Screener (v2) education tab (SHADOW · build, don't load)

A dashboard tab that shows screener_v2's **real** funnel + qualified setups as a teaching
surface, in the **same** entry/stop/target/R:R/size format as the other system panels —
while staying **SHADOW** (educational, never a live signal). `SIMULATED / advisory.`

## 0. PREREQ status — has run_real() run? **NO.**
There is **no real funnel feed** (`screener_v2_funnel.json`) in the repo — `run_real()`
has not been run on the live universe. So **the live tab renders the honest empty state**,
never a synthetic pick. Running `run_funnel.run_real(universe, spy_bars)` in the engine repo
is **step one** before this tab shows anything real.

## 1. What shipped (additive, in `index.html`)
- New top-level tab **"Pro Screener"** (`data-v="proscreen"`) + `#proscreen` panel + `ProScreen`
  module + `proscreen` HELP entry + funnel/setup CSS.
- Reads `screener_v2_funnel.json` via `ghFetch` (its own feed; degrades gracefully if absent).
- **HARD GUARD (real data only):** picks render **only if `source` starts with `REAL`**.
  Absent feed, synthetic feed, or 0 qualified → honest state. The `_smoke()` pick is never shown.

## 2. Render states — all proven headlessly (node, against the real module source)
| state | result |
|---|---|
| **Absent feed** | "Pro screener funnel not yet run on the live universe — no real setups to show." + SHADOW banner. No smoke. |
| **Synthetic feed** (`source:SYNTHETIC_SMOKE`, `VCP_C`/293.11) | **REFUSED** → empty state; `VCP_C`/293.11 **absent** from output. |
| **REAL-schema fixture** | funnel viz + "2 of 1840 qualified" + setup cards (entry/stop/target/R:R/RS/regime/size) + education callouts + not-extended chip + ACCRUING head-to-head + SHADOW banner. |

> Validation fixture: `screener_v2/_render_fixture.json` — clearly labelled NOT-LIVE,
> placeholder tickers (PRO_A/PRO_B), **never** fetched by the dashboard (different filename),
> **not** `_smoke()` data. Used only by the headless render test.

## 3. The feed schema the engine must write (`screener_v2_funnel.json`)
Map `run_funnel.run_real()` output → this feed (enrich qualified picks with entry/R:R/regime/size/education):
```json
{
  "generated_at": "ISO", "source": "REAL", "date": "YYYY-MM-DD",
  "funnel": {"universe":N,"stage1":..,"stage2":..,"stage3_vcp":..,"stage4_top":..,"watch":..},
  "qualified": [{
     "ticker":"…", "setup":"VCP base (3 contractions 24->14->8%)",
     "entry":<pivot breakout>, "stop":<below base>, "target":<measured move>,
     "rr":"1.5", "rs_rank":0.97, "not_extended":true,
     "regime_at_signal":"TRENDING", "size_band":"1-2% risk (sim)",
     "education":["…why it's a pro setup…"]
  }],
  "head_to_head": {"review_line":"…","verdict":"ACCRUING …","v2_n":0,"current_n":0},
  "disclaimer":"SHADOW — educational, not live recommendations."
}
```
`source` MUST be `REAL` (anything else is refused). `size_band` is %/R only (mirror rule).

## 4. Guardrails honored
- **REAL DATA ONLY** — hard guard refuses non-`REAL` source; absent feed → honest empty state.
  The synthetic `_smoke()` pick can never reach the dashboard (proven).
- **SHADOW** — prominent banner; does not feed any actionable list/email; current engine stays
  the sole live source of truth.
- **Additive / regression (D29)** — `node --check` clean, 0 conflict markers, all prior panels
  + toptabs intact, no existing `ghFetch` changed (new fetch via variable). Backup
  `backups/index.html.D54.bak`.
- **Privacy** — setup cards show market levels (entry/stop/target), RS rank, regime, and a
  size **band** ("1-2% risk (sim)"). **No real $ and no positions** anywhere.
- **n<30 DESCRIPTIVE** — head-to-head shows **ACCRUING** until real forward n accumulates.

## 5. Status
Built, validated, **NOT loaded** (draft PR; live tab currently shows the honest empty state
because `run_real()` hasn't run). Step one to populate: run `run_real()` in the engine and
publish `screener_v2_funnel.json` with `source:"REAL"`.
