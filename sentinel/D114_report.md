# Dispatch 114 — SENTINEL rebuild (qualification, not arming) + scorecard

**Decision (Hany):** the intraday alert stream was over-firing noise. SENTINEL is rebuilt as
a **qualification layer** — a hard gate in front of the senders that suppresses unless every
Part-1 gate passes — plus a **washout retune**, a **lock-screen alert format**, and a
**forward scorecard** so alert quality is measured, not re-derived from the inbox.
`SHADOW — frozen + acceptance-passed, but NOT armed. SIMULATED / advisory — not financial advice.`

## What shipped (this public repo)
- `sentinel/preregistration_sentinel.json` — FROZEN gate constants (single source of truth).
- `sentinel/sentinel.py` — the qualifier (`qualify() -> Decision`), self-test PASS.
- `sentinel/ledger.py` — forward CSV ledger + triple-barrier nightly labeler + scorecard builder, self-test PASS.
- `sentinel/acceptance_tests.py` — the six required tests A–F, **6/6 PASS**.
- `sentinel/seed.py` — regenerates the ledger header, the replay CSV, and the scorecard.
- `ledgers/sentinel_forward.csv` — the live forward ledger (header only; empty at go-live).
- `sentinel/D114_replay.csv` — the acceptance replay through the ledger writer (2 fired, 10 suppressed).
- `sentinel_scorecard.json` — published to the dashboard root (forward **ACCRUING (n=0)** + replay block).

## Acceptance test results (all six required before the plist goes live)

| test | requirement | result |
|---|---|---|
| **A** | Replay 8/3 ⇒ **ZERO** alerts (all six fail the slope gates — VOLD rising, TRIN falling) | **PASS** — 0 emitted; all six also fail the slope gate when probed in-window |
| **B** | Replay 7/16 10:49 ⇒ **MUST** fire Cluster Fade SHORT (the +$150 trade) | **PASS** — `TRADE: Cluster Fade SHORT 7617.0` |
| **C** | Replay 7/22 10:37 ⇒ **MUST** fire pullback-hold LONG (ALIGNED_UP) | **PASS** — `TRADE: Pullback-Hold LONG 7502.0` |
| **D** | Replay 7/24 11:35 ⇒ must **NOT** fire (first-touch, ADD rising into a short) | **PASS** — 11:35 trips WINDOW; in-window probe (11:25) trips `SLOPE:DIRECTION` |
| **E** | Debounce: two tags of 7618 in one session ⇒ exactly **one** email | **PASS** — 1 email; second ⇒ `DEBOUNCE` |
| **F** | Window: a 9:32 / 15:46 qualifying setup ⇒ logged, **not** emailed | **PASS** — both ⇒ `WINDOW` |

Reproduce: `python3 sentinel/acceptance_tests.py` (exit code 0 ⇒ all pass).

### Honesty note on the fixtures
This public repo archives OHLCV + an internals *flag*, not the raw ADD/VOLD/TRIN/TICK series
for the July/August dates. The acceptance fixtures are **reconstructed from the 30-day
sent-alert evidence** cited in the dispatch (e.g. "8/3: VOLD rising, TRIN falling all session";
"7/16 10:49: TRIN rising, VOLD falling, TICK negative at highs"). The tests therefore validate
the **gate logic** against the documented ground-truth scenarios — which is exactly what
decides whether a fire is allowed. The private engine feeds the real point-in-time internals
into the same `qualify()`.

## LOCKED DECISIONS (append to the ledger — staged for Knowledge)

> **D114 — SENTINEL is a QUALIFICATION layer, not an arming layer (FROZEN 2026-08-08,
> `sentinel_qualification_prereg_2026-08-08`).**
> No intraday alert email is sent unless ALL Part-1 gates pass:
> **(1)** window 09:35–11:30 & 14:00–15:15 ET;
> **(2)** slope v3.1 — 30-row LSQ, SHORT `ADD<0 AND (VOLD<0 OR TRIN>0)` / LONG mirror,
> 10%-of-level FLAT floor, `<15 rows`/`>120s` ⇒ UNRELIABLE log-only;
> **(3)** divergence `|ADD delta| >= max(150, 10%|ADD|)`;
> **(4)** event completed (Cluster Fade: pool tagged + rejection ≤3 bars; Failed Retest:
> 15m close ≥1pt beyond + retest; no "approaching");
> **(5)** risk floor stop ≥ 1.5·ATR(5m) beyond invalidation AND ≥ 1.5R;
> **(6)** debounce one alert per `(setup, level ±3pts)` per session;
> **(7)** daily cap 2/day, suppress the rest after a taken trade (one loss = done).
> **Washout retune:** drop standalone TRIN spike <09:45; require `TICK≤−900` AND at named
> support AND reclaim ≤3 bars.
> **Alert format:** `TRADE: {CARD} {DIR} {entry}` + entry/stop/T1/T2/half/level/3 gate values/
> "expires 10 min".
> **Scorecard:** every fire + every suppressed near-miss → `ledgers/sentinel_forward.csv`;
> `sentinel_scorecard.json` published; **DESCRIPTIVE until n≥30.**
> **Status:** SHADOW — frozen + 6/6 acceptance-passed, **NOT armed**. Arming (the launchd
> plist) is a private-tree step taken only after review + explicit go. Any change to a gate
> constant is a NEW pre-registration with its own forward series.

## Not loaded / not armed
`index.html` is untouched (dashboard regression guard holds — no `ghFetch` source changed).
No sender is wired. The scorecard is generated to the repo root the way `risk/` and
`screener_v2/` generate their views; loading it into the Alerts tab is a later, reviewed step.
