# DISPATCH REPORT — INBOX RESET + 10:00 READ + D114 SHADOW TRAINING

**Date:** 2026-08-10 · **Branch:** `claude/dispatch-inbox-shadow-training-oa0r1v`
`SIMULATED / advisory — not financial advice. DESCRIPTIVE until n>=30.`
**Nothing deleted — every suspension is a dated reversible flag with prior state preserved.**

## Environment / scope note (honest, up front)
This is the **public dashboard/config repo** run from the cloud. It carries the alert **config**
(`alert_prefs.json` gate + `alert_registry.json`) and the **D114 code** (`sentinel/`, PR #20).
It does **not** carry the launchd **plists**, the Mac-local **senders** (`setup_sentinel`,
`candle_pattern_alert`, `feed_watchdog`, `arsenal_alerts`), or the raw ADD/VOLD/TRIN/TICK 1-min
archive (`internals_live.csv`) for historical dates. So, from here:

- **Done in-repo (verifiable, committed):** flipped the one gate we own (`orb_intraday`),
  recorded every Part-1 suspension as a dated reversible flag with prior state, wired the two
  CONTEXT fields into `internals_snapshot.json`, and built + self-tested the 10:00 READ and the
  D114 shadow-email layer (T1/T2/T3 all green).
- **Mac-local (recorded here for a mechanical reversal / next step):** `launchctl unload` of the
  sentinel/candle plists, the `WATCHDOG_EMAIL=False` flag, and — critically — the **acceptance
  A–F re-run against the REAL archived internals** and the **10 shadow sessions**. Those cannot
  run from the cloud and are **not** claimed as done.

---

## PART 1 — SILENCE

### 1.1 Jobs suspended (with prior state)

| # | job | scope | prior state | new state | mechanism | reversible |
|---|---|---|---|---|---|---|
| 1 | **setup_sentinel** (Cluster Fade / Failed Retest / Washout) | all 3 legs | LOADED / ENABLED / emailing (~201/30d) | SUSPENDED (unloaded) | Mac: `launchctl unload com.arsenal.sentinel.plist`; recorded in `alert_suspensions.json` | ✅ |
| 2 | **candle_pattern_alert** (SHADOW) | email | LOADED / SHADOW-emailing | SUSPENDED (unloaded); data still accrues via nightly labeler | Mac: `launchctl unload com.arsenal.candle_pattern.plist` | ✅ |
| 3 | **feed_watchdog** | **EMAIL only — LOG kept** | email ON + log ON | email SUSPENDED, log KEPT | Mac: `WATCHDOG_EMAIL=False` (gate left enabled so logging survives) | ✅ |
| 4 | **arsenal_alerts** = `orb_intraday` (5-min ORB) | email | `alert_prefs.orb_intraday.enabled=true` | `enabled=false` (registry `on_now=false`) | **in-repo gate** every sender reads | ✅ |

Rationale per the dispatch: setup_sentinel over-fired (8/3 six Cluster Fades incl. two at 7618.0;
~1/3 off-window; washout 4/7 opening TRIN spikes); candle is informational, never traded off;
feed_watchdog emitted 5–7 identical hourly alarms + a false RECOVERED (P2 unfixed); arsenal_alerts
fires STRONG_LONG picks whose own forward scorecard reads **exp −2.50%, PF 0.4**. The full
reversible ledger with prior state is `alert_suspensions.json`.

### 1.2 KEPT UNCHANGED (verified still live by T2)
`com.arsenal.daily` 8:00 AM + 4:30 PM briefs · `com.arsenal.breadth / bpspx / macropillars`
(nightly, no email) · all ledger + nightly-labeler jobs (data must keep accruing).

### 1.5 Every email-emitting job + state (full enumeration)

| source (registry id) | script / job | emails? | state after this dispatch |
|---|---|---|---|
| `orb_intraday` | arsenal_alerts.py / com.arsenal.alerts | yes | **SUSPENDED** (gate false) |
| `feed_watchdog` | feed_watchdog.py / com.arsenal.watchdog | yes | **EMAIL SUSPENDED, LOG kept** |
| setup_sentinel *(Mac-local, not in registry)* | com.arsenal.sentinel | yes | **SUSPENDED (unloaded)** |
| candle_pattern_alert *(Mac-local, SHADOW)* | com.arsenal.candle_pattern | yes (shadow) | **SUSPENDED (unloaded)** |
| `ema_es` | ema_alert.py / run_ema.sh | yes | OFF (pre-existing; `enabled=false` since before this dispatch) |
| `ema_gccl` | ema_gccl_alert.py | yes | **ON (kept)** |
| `ema_stocks` | ema_stocks_alert.py | yes | **ON (kept)** |
| `fvg` | fvg_alert.py | yes (DARK now ⇒ no alert) | **ON (kept)** |
| `ict_killzone` | ict_alert.py | yes | **ON (kept)** |
| `ict_offwindow` | ict_alert.py (STUDY, 4/hr cap) | yes | **ON (kept)** |
| `stocks_curated` | stock_alerts.py | yes | **ON (kept)** |
| `inside_bar` | inside_bar_alert.py | yes | **ON (kept)** |
| `verdict_threshold_ES/GC/CL` | verdict_threshold_alert.py | no | GAP: compose-only, not wired, OFF |
| `com.arsenal.daily` | daily briefs | yes | **ON (kept — 8:00 / 4:30)** |
| **10:00 READ** *(new, Part 2)* | `inbox_reset/ten_am_read.py` | yes (1/session) | **NEW — the one keeper** |
| **D114 shadow** *(Part 3, PR #20)* | `sentinel/shadow_run.py` + `shadow_email.py` | yes, `[SHADOW—NOT VALIDATED]` | **SHADOW training (emails ON, marked)** |

---

## PART 2 — 10:00 READ + CONTEXT wiring

**10:00 READ** (`ten_am_read.py`): fires 10:02 ET, market days, one email/session, state only.
Locked 4-type day rule (VD **above** DISTRIBUTION), gates on the same 30-row LSQ slope engine as
the sentinel, 10%-of-level FLAT floor, `<15 rows`/`age >120s` ⇒ UNRELIABLE stated explicitly.
Subject `10:00 READ — {DAY_TYPE} | L:{PASS|FAIL} S:{PASS|FAIL}`.

**CONTEXT wired natively** into `internals_snapshot.json` via `internals_context.py`:
- `megacap_pct` = mean daily %chg of NVDA, AAPL, MSFT, AMZN, GOOGL.
- `rsp_spy` = RSP/SPY close ratio + 20d LSQ slope + rolling z-score.

Both are **CONTEXT, not gates.** Per the 500-day study, the +2% "no shorts" half holds
(SPX +0.35% next day, 71% win) but the −2% "no longs" half is **BACKWARDS** (−2% days were the
best forward bucket: +0.46%, 65% win) — so megacap is **logged at entry**, never used to suppress
a long; revisit at n≥20. In this repo snapshot both fields resolve to `SOURCE_MISSING` (the
megacaps and RSP are absent from the Polygon snapshot; no 20d ratio history) — the plumbing +
schema are in place and the math is proven by the self-test; the Mac collector/Yahoo fetch
populates the live values.

---

## PART 3 — D114 SHADOW TRAINING MODE (emails ON, clearly marked)

`shadow_email.py` implements all five guardrails: (1) mandatory subject prefix
`[SHADOW—NOT VALIDATED] {CARD} {LONG|SHORT} @ {level}` — never `TRADE:`; (2) reasoning body
(Card / Location / Event — states *which* completion evidence / Gates / Risk with R:R / megacap +
RSP-SPY) + the `YOUR CHECK` footer; (3) one **16:15 near-miss digest** naming the SPECIFIC gate
that killed each armed-but-suppressed setup; (4) an **outcome line** (30/60-min triple-barrier)
on every fire and every near-miss; (5) still logs to `ledgers/sentinel_forward.csv`, still NOT
validated. Integration point: `sentinel/shadow_run.py` on PR #20 (documented in the README).

### STILL REQUIRED BEFORE ARMING (Mac; not before shadow emails)
- Re-run acceptance **A–F against the REAL archived internals** on the Mac (not the reconstructed
  fixtures in `D114_report.md`) via `sentinel/real_replay.py`; report each test's actual gate
  values and flag ANY divergence from the fixture run. **Not runnable from the cloud — not done here.**
- **10 shadow sessions**; arm only if ≤3 fires/day, zero off-window, zero duplicate levels, and no
  8/3-style trend-fighting shorts (`sentinel/pre_arm_gate.py` → ARM).

---

## TESTS (T1 / T2 / T3) + self-tests

`bash inbox_reset/run_all_tests.sh` → **ALL GREEN**. Summary:

- **T1 — 10:00 READ dry-run.** The renderer, driven by the 8/10 10:00 ground-truth (reconstructed
  from the dispatch, the raw rows being Mac-archived), renders exactly:
  `VOLUME_DIVERGENT_DOWN`, **LONG FAIL / SHORT PASS**, `ATR(5m) 5.40 → min stop 8.1`,
  pools **7796.25** above / price **7787.75** (7787–88) / **7771.25** below. ✅ (9/9 T1 asserts pass.)
  The live dry-run against the real single-row `internals_snapshot.json` also classifies VD_DOWN
  and **explicitly flags `UNRELIABLE:ROWS(1<15)`** — honoring "never omit silently."
- **T2 — suspended jobs inert.** `verify_suspensions.py`: `orb_intraday` gate false ⇒ no email;
  `feed_watchdog` email suspended, logging kept; `setup_sentinel` + `candle_pattern_alert`
  recorded SUSPENDED with prior state; all seven KEPT senders still enabled. ✅ (18/18 pass.)
- **T3 — shadow samples.** One shadow fire + one near-miss digest render with the mandatory prefix,
  full reasoning body, the specific killing gate per near-miss, and outcome lines. ✅ (19/19 pass.)
- Self-tests: `internals_context` 9/9 · `ten_am_read` 17/17 · `shadow_email` 19/19. `py_compile` clean.

### Rendered sample — 10:00 READ (T1)
```
Subject: 10:00 READ — VOLUME_DIVERGENT_DOWN | L:FAIL S:PASS

Day type : VOLUME_DIVERGENT_DOWN
Gates    : LONG FAIL | SHORT PASS
           ADD -574 slope -   VOLD 11592 slope -   TRIN 0.64 slope +   (30-min/30-row LSQ)
           slope magnitude must exceed 10% of series level else FLAT=fail
Risk     : ATR(5m) 5.40 -> min stop 8.1 (1.5x)
Levels   : pools above 7796.25 | price 7787.75 | pools below 7771.25
FVGs     : none near price
Context  : megacap_pct n/a (SOURCE_MISSING) | RSP/SPY n/a (SOURCE_MISSING)
Feed     : LIVE + age 45s

State only — no recommendation. SIMULATED / advisory, not financial advice.
```

### Rendered sample — D114 shadow fire + near-miss digest (T3)
```
Subject: [SHADOW—NOT VALIDATED] Cluster Fade SHORT @ 7617

Card     : Cluster Fade SHORT
Location : cluster VP-POC (Tammy 7618 shelf) @ 7617 — prior-day POC + Tammy resistance shelf; swept then rejected
Event    : sweep/pool tagged: YES; rejection ≤3 bars: YES (2 bars)
Gates    : ADD slope -8.1 | VOLD slope -4200000.0 | TRIN slope 0.03  => QUALIFIED (all Part-1 gates pass)
Risk     : ATR(5m) 4.00; min stop (1.5x beyond 7620) 7626; proposed stop 7627; entry 7617 -> T1 7601  R:R 1.6
Context  : megacap -0.42% | RSP/SPY 0.24310  (context — megacap is NOT a gate)
Outcome  : 30m T1 +1.60R | 60m T1 +1.60R (triple-barrier)

--- YOUR CHECK: location? event complete? flow agreeing? ---

Subject: [SHADOW—NOT VALIDATED] NEAR-MISS DIGEST 2026-08-11 — 3 armed & suppressed
11:26 Cluster Fade 7606.25 SHORT — SUPPRESSED: ADD delta 15 < 150-issue floor; VOLD rising.
   then: 30m STOP -1.00R | 60m TIME -0.60R (triple-barrier)
09:32 Cluster Fade 7618 SHORT — SUPPRESSED: outside window (09:35–11:30 / 14:00–15:15 ET).
   then: 30m TIME +0.20R | 60m TIME -0.10R (triple-barrier)
14:05 Failed Retest 7690 LONG — SUPPRESSED: slope disagrees (ADD -3.0, VOLD -1100000.0, TRIN 0.02).
   then: 30m STOP -1.00R | 60m STOP -1.00R (triple-barrier)
```
Full renders (incl. the live dry-run) are in `inbox_reset/samples/`.

## MD5SUMS
See `inbox_reset/MD5SUMS.txt` (regenerate: `md5sum` over the files listed there). Key entries at
commit time — the four config/context files and the four `.py` modules — are recorded in that file.

---

## LOCKED DECISIONS (staged for Knowledge)

> **D115 — INBOX RESET: silence the noise senders as DATED REVERSIBLE FLAGS (2026-08-10).**
> Suspend `setup_sentinel` (all 3 legs), `candle_pattern_alert` (shadow), `arsenal_alerts`
> (`orb_intraday`, exp −2.50%/PF 0.4), and `feed_watchdog` **email only (keep logging)**. Nothing
> deleted; prior state preserved in `alert_suspensions.json` + `alert_prefs.json`/`alert_registry.json`;
> reversal is mechanical. KEEP the 8:00/4:30 briefs, the nightly no-email jobs, and all
> ledger/labeler jobs. The `orb_intraday` gate (`alert_prefs.json enabled=false`) is authoritative
> in-repo; the plist unloads are the Mac step.

> **D115 — 10:00 READ is the one intraday keeper (2026-08-10).** 10:02 ET, market days, ONE email
> per session, **state only, no recommendation.** Locked 4-type day rule (TREND_UP/DOWN, VD_UP/DOWN,
> VD **above** DISTRIBUTION). Gates share the sentinel's 30-row LSQ slope engine (10%-of-level FLAT
> floor; `<15` rows or age `>120s` ⇒ UNRELIABLE, **stated explicitly, never omitted**). Risk =
> ATR(5m) → 1.5× min stop. Reports levels/FVGs/context/feed.

> **D115 — megacap_pct & rsp_spy are CONTEXT, wired into `internals_snapshot.json`; megacap is NOT
> a gate (2026-08-10).** 500-day study: +2% "no shorts" holds (SPX +0.35%, 71% win); −2% "no longs"
> is BACKWARDS (−2% = best forward bucket +0.46%, 65% win). Log megacap at entry on every trade row;
> revisit at n≥20. Never suppress a long on it.

> **D115 — D114 SHADOW TRAINING: emails ON but clearly marked, still NOT validated (2026-08-10).**
> Subject prefix `[SHADOW—NOT VALIDATED]` (mandatory; `TRADE:` reserved for post-validation). Body =
> reasoning (Card/Location/Event/Gates/Risk/megacap+RSP-SPY) + `YOUR CHECK` footer. One 16:15
> near-miss digest naming the SPECIFIC killing gate. Outcome (30/60-min triple-barrier) on every
> fire AND near-miss. Everything logs to `ledgers/sentinel_forward.csv`. The `[SHADOW]` tag comes
> off **only** after the real-data A–F re-run on the Mac AND 10 clean shadow sessions
> (≤3 fires/day, zero off-window, zero duplicate levels, no trend-fighting shorts).
