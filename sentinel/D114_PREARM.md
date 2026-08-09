# Dispatch 114 — PRE-ARM validation protocol (before merge/enable)

The gates are frozen and the reconstructed-fixture acceptance run is 6/6. Before arming,
the qualifier is validated against **real archived internals** and run in **shadow mode**
for ≥10 sessions, and the arming call is made **mechanically** by a gate — not by eye.

> **Environment note (honest):** steps 1–3 execute **on the Mac**, where `internals_live.csv`
> (the collector archive) and the live tape are. This public/cloud repo mirrors only OHLCV +
> a per-date internals *flag* — it does **not** carry the raw ADD/VOLD/TRIN/TICK rows for
> July/August, so it **cannot** compute real gate values. The tooling below is built and
> self-tested here; the real-data runs happen on the Mac. Nothing was run against real
> internals from the cloud, and this doc does not claim otherwise.

## Step 1 — re-run A–F on REAL rows  (`sentinel/real_replay.py`)
Reads `internals_live.csv` (schema = `internals_snapshot.json`: `ts, add, vold, trin, tick, …`),
slices the trailing 30×1-min window at each event time, builds `Internals` from **real rows**,
re-runs the frozen `qualify()`, and reports pass/fail per test **with the actual computed gate
values** — and **flags any divergence** (real slope signs vs the documented evidence signs).
```
python3 sentinel/real_replay.py --csv /path/to/internals_live.csv
```
Event params (levels/risk/expected verdict) live in `sentinel/pre_arm_events.json`; edit them
to the collector's exact archived values if they differ, then re-run. **Report the per-test
table + any ⚠ divergence.** A slope-sign divergence is a stop-and-investigate, not a pass.

## Step 2 — shadow mode, ≥10 sessions, EMAIL NOTHING  (`sentinel/shadow_run.py`)
Runs live around the engine's detected candidates with the email path **hard-off**
(`EMAIL_ENABLED = False`; a runtime assert trips if a fire ever reaches the send path). Logs
**every would-fire and every suppression** with full gate values to `ledgers/sentinel_forward.csv`,
and publishes `sentinel_scorecard.json` daily.
```
# each session (a plist can call this):
python3 sentinel/shadow_run.py --candidates day_candidates.json --csv internals_live.csv --date YYYY-MM-DD --day-type TREND_UP
# end of day:
python3 sentinel/shadow_run.py --publish --asof YYYY-MM-DDT16:30:00Z
```
`day_candidates.json` is the engine's detected setups for the day (ts/setup/dir/level/entry/
stop/T1/T2/invalidating_extreme/atr5m + event-completion evidence); internals are joined from
the CSV. **The sender is never armed in this step.**

## Step 3 — the morning comparison  (`sentinel/morning_compare.py`)
Each morning, three columns for the prior session: **D114 would-fire** vs **old sentinel
spammed** (`old_sentinel_fires.csv`, if exported) vs **tape** (day-type + close). Projects the
monthly fire count (~200/mo baseline → D114 projection) and lists each would-fire with its
ADD-slope so the "right 15?" question is answerable at a glance.
```
python3 sentinel/morning_compare.py --date YYYY-MM-DD
```

## Step 4 — the ARM decision, mechanical  (`sentinel/pre_arm_gate.py`)
After ≥10 shadow sessions, this reads the ledger and returns **ARM / DO-NOT-ARM / NOT-READY**.
**ARM only if ALL four hold:**
1. shadow fires **≤ 3/day** every session;
2. **zero** fires outside the window;
3. **zero** duplicate levels (debounce held, ±3pts);
4. **no** 8/3-style trend-fighting shorts — a qualified SHORT with `ADD_slope ≥ 0`, a qualified
   SHORT on a `TREND_UP` day, or ≥2 qualified SHORTs at ascending levels in one session.

`< 10` sessions ⇒ NOT-READY (keep accruing). Any criterion fail ⇒ DO-NOT-ARM (a blocker: fix
the gate or the setup, re-shadow, re-evaluate).
```
python3 sentinel/pre_arm_gate.py        # -> sentinel_prearm_verdict.json
```

## LOCKED DECISIONS — addendum (staged for Knowledge)

> **D114 PRE-ARM — SENTINEL arms only on a mechanical, four-criteria gate after ≥10 shadow
> sessions (FROZEN 2026-08-08).**
> Before merge/enable: (1) re-run acceptance A–F on the **real** archived internals
> (`real_replay.py`) — report actual gate values, flag any slope-sign divergence; (2) run
> **shadow, email-off**, ≥10 sessions, logging every fire + suppression (`shadow_run.py`,
> `EMAIL_ENABLED=False`); (3) morning-compare D114 vs old-sentinel vs tape
> (`morning_compare.py`); (4) **ARM ONLY IF** shadow fires ≤3/day AND zero off-window AND zero
> duplicate levels AND zero trend-fighting shorts (`pre_arm_gate.py` → ARM). Arming (the
> launchd plist) stays a private-tree step even on an ARM verdict. Every tool is stdlib-only,
> self-tested, and reads the frozen constants — no gate constant changes in the pre-arm layer.

## What ran where
- **Cloud (this repo):** all five tools written + self-tested (mechanics proven on synthetic
  data). `real_replay.py --selftest`, `shadow_run.py --selftest`, `pre_arm_gate.py --selftest`,
  `morning_compare.py --selftest` — all PASS. `py_compile` clean.
- **Mac (yours):** the real-data runs (steps 1–3) and the arming verdict (step 4).
