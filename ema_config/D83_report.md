# Dispatch 83 — Instrument-specific EMA primary-track (READ-FIRST + staged config)

Make the EMA raw-vs-filtered **primary/recommended** read instrument-specific (GC/CL/stocks =
FILTERED, ES = RAW intraday) instead of one-size. **Selection/default change only** — no
strategy rewrite, no threshold tuning, no new tracks; both raw+filtered stay scored for all.
`STAGED — NOT loaded. SHADOW / non-voting.`

## READ-FIRST — current selection logic
**Hardcoded ONE-SIZE: FILTERED is primary for every instrument**; RAW is the "control," shown
only under the research-detail drawer.
- **ES intraday** — `renderEMA()` (`ema_state.json`): hero "context lean" + `live_signal`
  PAPER row + header "EMA signals — FILTERED (tested-for-edge) vs RAW (control)"; RAW under
  "▸ research detail". FILTERED = cross + 15m-trend gate.
- **Stocks** — `emaLinePick()`/`emaStkResearch()` (`ema_stocks_state.json`): FILTERED
  "tested-for-edge", RAW control.
- **GC/CL** — `ema_gccl_state.json`: DELAYED, non-voting; both tracks scored.
- **No per-instrument config exists.** Both raw+filtered already scored for all (measurement intact).

## READ-FIRST — evidence-match check (⚠ the blocker)
Dispatch cites **independent-deduped** 6/30 numbers. The dashboard `tracks_summary` is
**NON-deduped**. The deduped scorecard is an **engine artifact not present in this repo**, so
the cited numbers can't be verified here. Direction check vs the non-deduped 6/30 view:

| instrument | dispatch says | dashboard (non-deduped) | match? |
|---|---|---|---|
| GC | filter helps | 9_21_60m filtered +9.82/PF1.86 (n41) vs raw −1.85/PF0.90 (n213) | ✓ direction |
| CL | filter helps | 9_21_60m filtered +0.09/PF1.22 (n59) vs raw −0.13/PF0.78 (n203) | ✓ direction |
| STOCKS | filter helps | 9_21_daily filtered +10.99/PF1.59 (n104) vs raw +4.22/PF1.22 (n223) | ✓ direction |
| **ES** | **filter HURTS** | **20_50_5m filtered +1.25/PF1.19 (n181) vs raw −1.18/PF0.84 (n493)** | **✗ CONTRADICTS (sign-level)** |

GC/CL/stocks = FILTERED is corroborated (and is already the status quo). The **only real change
— ES → RAW — is contradicted by the dashboard's visible data.** Most likely the dedup
(ES 5m raw 472→96 can flip a sign), but unverifiable from here.

**Decision (Hany, D83 read-first question):** *refresh the dashboard data first* — publish the
independent-deduped EMA tracks so the basis matches, then apply the config on matching data.

## Engine refresh spec (the prerequisite — engine-side; I can't dedup here)
The per-setup EMA trade ledger isn't in this repo (only aggregated `tracks_summary`), so the
dedup must run in the engine. Republish `ema_state.json`, `ema_stocks_state.json`,
`ema_gccl_state.json` with `tracks_summary` recomputed on **independent setups only** (D21
methodology: correlated/duplicate entries excluded, `entry_tol`/`window` dedup), and add
transparency fields per track:
```json
"<track>": { "n_matured": <independent>, "n_raw": <pre-dedup>, "dedup": "independent setups only (D21)",
             "net_points_expectancy": ..., "profit_factor": ... }
```
After refresh, the ES tracks should read filtered-loses / raw-wins (matching the 6/30 EOD read),
and GC/CL/stocks filtered-wins. Then the dashboard basis corroborates the config.

## Staged config (ready to apply post-refresh) — `ema_config/ema_primary_config.json`
`primary_by_instrument`: **GC/CL/STOCKS = filtered · ES = raw · NQ/RTY/YM = raw (ASSUMPTION,
not evidence)**. Each carries a basis/honesty tag (mechanism + the deduped numbers). ES carries
a **BLOCKING caveat** (dashboard contradicts until refreshed). `default_rule`: no n≥30 on both
→ raw + assumption. Reversible (declared map). Measurement intact; SHADOW/non-voting.

## What is NOT done yet (waits on the refresh, per Hany's choice)
- `index.html`/`renderEMA` is **unchanged** — the ES→RAW surface flip is the "apply on matching
  data" step. It loads only after the engine refresh lands and the dashboard ES tracks match.
- Next sequence: engine refresh → I verify ES tracks now match the deduped read → wire
  `renderEMA` (+ stocks) to read `ema_primary_config.json` and surface RAW primary for ES with
  the basis tag → regression guard → load on review.

## Guardrails honored
READ-FIRST reported before editing · config/selection only (no strategy/threshold change) ·
both raw+filtered still scored for all · reversible · SHADOW/non-voting · instruments without
n≥30 → RAW + assumption · **did NOT force ES on contradicting data** (stopped per guardrail) ·
nothing loaded · privacy unchanged.
