# SENTINEL — alert qualification layer (Dispatch 114 · SHADOW · not armed)

A **qualification** gate in front of the intraday alert senders. The engine still detects
setups (Cluster Fade, Failed Retest, Washout Reclaim, Pullback-Hold); SENTINEL decides
whether a detected setup is allowed to reach the lock screen. **No email unless ALL
Part-1 gates pass.** It never changes setup detection, the engine, or the dashboard.
`SIMULATED / advisory — not financial advice. DESCRIPTIVE until n>=30.`

## Why (the evidence)
30 days of sent alerts (~201 fires, ~6–7/day) were mostly noise:
- **8/3** fired **six** Cluster Fades in one trending session (two at the *identical* 7618.0);
  ES closed +11 pts — **0-for-6 ascending shorts into a one-way grind.**
- **~1/3** of alerts fired **outside the tradeable window** (9:30/9:32/9:38 pre-classification;
  7/28 @ 15:46 after the flat rule).
- The **washout leg** was 4-of-7 opening-rotation TRIN spikes; only 7/29 (TICK −920) was real.

The fix is qualification, not more signals.

| file | what it is |
|---|---|
| `preregistration_sentinel.json` | **FROZEN** gate constants (windows, slope v3.1, divergence floor, event completion, risk floor, debounce, daily cap, washout retune, alert format). Single source of truth. |
| `sentinel.py` | the qualifier. `qualify(candidate, session) -> Decision`. Pure, stdlib-only, self-test. |
| `ledger.py` | `ledgers/sentinel_forward.csv` writer + **triple-barrier** nightly labeler + `sentinel_scorecard.json` builder. Self-test. |
| `acceptance_tests.py` | the six required tests **A–F** (fixtures reconstructed from the sent-alert evidence). |
| `seed.py` | regenerates the forward-ledger header, the D114 replay CSV, and the scorecard. |
| `D114_report.md` | the report + **LOCKED DECISION** freeze (staged for Knowledge). |
| **pre-arm** | `D114_PREARM.md` (protocol) + `real_replay.py` (step 1: A–F on **real** archived internals) + `shadow_run.py` (step 2: live, email-off, ≥10 sessions) + `morning_compare.py` (step 3) + `pre_arm_gate.py` (step 4: the mechanical **ARM/DO-NOT-ARM** decision) + `pre_arm_events.json`. |

## The gates (Part 1 — no email unless ALL pass)
1. **Window** — 09:35–11:30 and 14:00–15:15 ET only. Hard.
2. **Slope v3.1** — 30-row LSQ on ADD/VOLD/TRIN. SHORT: `ADD_slope<0 AND (VOLD_slope<0 OR TRIN_slope>0)`;
   LONG mirrors. Magnitude must clear 10% of the series level (else FLAT=fail). `<15 rows` or
   `feed age >120s` ⇒ UNRELIABLE (log only, no email).
3. **Divergence floor** — `|ADD delta| >= max(150 issues, 10% of |ADD|)`. Kills micro-noise
   (the 8/3 11:26 fire cited ADD 1155→1140).
4. **Event completion** — Cluster Fade needs the pool TAGGED + a rejection (re-cross within 3×1-min
   bars); Failed Retest needs a 15m boundary close ≥1pt beyond, then the retest. No "approaching".
5. **Risk floor** — stop ≥ 1.5·ATR(5m) beyond the invalidating extreme AND target pays ≥ 1.5R.
6. **Debounce** — one alert per `(setup, level ±3pts)` per session. The 7618 double-fire is impossible.
7. **Daily cap** — 2 qualified alerts/day; after a taken trade is logged, suppress the rest (one loss = done).

**Washout retune (Part 2):** drop the standalone TRIN-spike trigger before 09:45; washout now
requires **all three** — `TICK ≤ −900` AND price at a named support AND a reclaim within 3×1-min bars.

**Alert format (Part 3):** `Subject: TRADE: {CARD} {LONG|SHORT} {entry}`; body = entry / stop / T1 /
T2 / half-size / level name / the three gate values / "expires 10 min if untaken".

## Run
```
python3 sentinel/sentinel.py           # gate self-test
python3 sentinel/ledger.py             # ledger + triple-barrier + scorecard self-test
python3 sentinel/acceptance_tests.py   # the six required tests A–F (exit!=0 on any fail)
python3 sentinel/seed.py               # regenerate ledger header + replay CSV + scorecard
```

## Scorecard (Part 4 — so this is never email archaeology again)
Every fire **and** every suppressed near-miss → `ledgers/sentinel_forward.csv`
(ts, setup, level, dir, entry/stop/T1/T2, gate values, qualified Y/N, suppression reason,
taken Y/N, triple-barrier outcome + R via the nightly labeler). Rolled into
`sentinel_scorecard.json` (n_fired, n_qualified, win%, expectancy, by setup, by day-type).
**DESCRIPTIVE until n≥30.** At go-live the forward ledger is empty ⇒ **ACCRUING (n=0)**.

## Engine hand-off (where the REAL qualifier runs)
This public repo archives OHLCV + an internals *flag*, not the raw ADD/VOLD/TRIN/TICK series
for July/August. In the private engine tree, at alert time:
```python
from sentinel import Candidate, Internals, SessionState, qualify
d = qualify(candidate, session_state)     # session_state persists per trading day
if d.emit_email():
    send(d.alert["subject"], d.alert["body"])   # else: log the row, no email
ledger.append_rows([ledger.row_from_decision(candidate, d, taken=..., day_type=...)])
```
Feed `Internals` real point-in-time 1-min rows (oldest first). The nightly labeler stamps
outcomes from that day's bars; `seed.py`/the publisher writes `sentinel_scorecard.json`.

## Status: SHADOW — planted, not armed
The gate logic is frozen and all six acceptance tests pass, but **nothing is wired into
`index.html` and no sender is armed.** Arming (the launchd plist) is a private-tree step taken
only after review + an explicit go. The current alert senders remain unchanged until then.

## Privacy
OHLCV, internals slopes, level names, R-multiples only. **No account $, no positions.**
Mirror-safe.
