# inbox_reset — INBOX RESET + 10:00 READ + D114 SHADOW TRAINING

One dispatch, three parts. **Nothing deleted — all suspensions are dated reversible flags.**
`SIMULATED / advisory — not financial advice. DESCRIPTIVE until n>=30.`

## Scope (honest)
This public/dashboard repo carries the alert **config** (`alert_prefs.json` gate +
`alert_registry.json`) and the **D114 code** (`sentinel/`, PR #20). The launchd **plists** and
the Mac-local **senders** (`setup_sentinel`, `candle_pattern_alert`, `feed_watchdog`,
`arsenal_alerts`) live in the private engine tree. So here we flip the gate we own, record every
Mac-local suspension as a dated reversible flag with prior state, wire the two CONTEXT fields,
and build + self-test the 10:00 READ and the D114 shadow-email layer. The real-data acceptance
re-run and the ≥10 shadow sessions execute **on the Mac** (see PR #20's `sentinel/D114_PREARM.md`).

| file | part | what it is |
|---|---|---|
| `../alert_suspensions.json` | 1 | dated reversible suspension ledger (prior state + reversal per job) |
| `../alert_prefs.json` (edit) | 1 | `orb_intraday.enabled=false` — the in-repo gate every sender reads |
| `../alert_registry.json` (edit) | 1 | dated suspension annotations for `orb_intraday` + `feed_watchdog` |
| `internals_context.py` | 2 | wires `megacap_pct` + `rsp_spy` CONTEXT into `../internals_snapshot.json` |
| `ten_am_read.py` | 2 | the **10:00 READ** — locked 4-type day rule + slope gates + risk/levels/context |
| `shadow_email.py` | 3 | D114 shadow-email formatter: `[SHADOW—NOT VALIDATED]` subject, reasoning body, near-miss digest, outcome line |
| `verify_suspensions.py` | T2 | asserts every suspended job is inert and every KEPT job untouched |
| `run_all_tests.sh` | — | py_compile + every self-test + T1/T2/T3 |
| `samples/` | — | rendered 10:00 READ (T1 + live dry-run) and D114 shadow fire + digest (T3) |

## Run
```
bash inbox_reset/run_all_tests.sh          # everything
python3 inbox_reset/ten_am_read.py --t1    # render the 10:00 READ (T1 fixture)
python3 inbox_reset/ten_am_read.py --dry-run   # against the live internals_snapshot.json
python3 inbox_reset/shadow_email.py --sample   # one shadow fire + one near-miss digest
python3 inbox_reset/internals_context.py --build   # (re)inject the CONTEXT fields
```

## 10:00 READ — the one keeper
Fires 10:02 ET, market days only, **one email per session, state only, no recommendation.**
Locked 4-type classifier (VD **above** DISTRIBUTION): breadth=sign(ADD), volume=sign(VOLD),
price=sign(ES chg) — all agree ⇒ TREND_UP/DOWN; breadth vs volume disagree ⇒ VD_UP/VD_DOWN;
else DISTRIBUTION. Gates use the **same** 30-row LSQ slope engine as the sentinel, so the READ
and the qualifier never disagree. If feeds are DARK or slopes UNRELIABLE (`<15` rows or age
`>120s`) it **says so explicitly** and reports the gates as FAIL — never omits silently.

## D114 shadow training — emails ON, clearly marked, still NOT validated
`shadow_email.py` is the presentation seam that wraps the frozen `qualify()` Decision. It is
decoupled (takes a plain decision-record dict) so it self-tests without the `sentinel/` package.
**Integration:** in `sentinel/shadow_run.py`, keep the ledger write, and for a qualified decision
call `render_fire()`; collect suppressed rows for the 16:15 `near_miss_digest()`. The `[SHADOW]`
tag comes off **only after the real-data re-run** on the Mac.
