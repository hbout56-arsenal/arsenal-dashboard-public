# Feed Watchdog — Stale-After Threshold Audit

**Trigger:** the Inside Bar feed watchdog check flapped 6× on 2026-07-06
(stale → recovered), each time recovering healthy at ~500–700s lag. The
stale-after threshold (~8 min) is tighter than `inside_bar_state`'s actual
compute cadence, producing false feed-death alarms.

**Where the fix actually lives:** the watchdog itself (`feed_watchdog.py`,
state in `watchdog_state.json`, launched by `com.arsenal.watchdog`) is
**MAC-LOCAL** — it runs on the Mac and its source lives in the private
`hbout56-arsenal/Arsenal-Trading` repo, **not** in this published dashboard
mirror. This file is the version-controlled record of the intended change and
the cadence audit; the live edit must be applied to `feed_watchdog.py` on the
Mac (see "Deploy" below). Access to `Arsenal-Trading` could not be granted in
the authoring session (the `add_repo` approval handshake failed repeatedly
against an unstable MCP connection), so the change is documented here for
one-step application.

---

## 1. Inside Bar check — widen stale-after ~8 min → 15 min  *(the fix)*

| | value |
|---|---|
| Current stale-after | ~8 min (~480 s) |
| Observed healthy recovery lag | 500–700 s (8.3–11.7 min) |
| Flaps on 2026-07-06 | 6 (stale→recovered, each healthy) |
| **New stale-after** | **15 min (900 s)** |

`inside_bar_state.json` recomputes on a cadence looser than 8 min, so a
healthy-but-slightly-late recompute crossed the threshold and fired a
false stale alarm, then cleared on the next write — the classic flap. 15 min
sits above the observed 700 s worst-case with ~28% headroom while still
catching a genuine feed death well inside one session.

Evidence (this repo, 2026-07-06): `inside_bar_state.json` `generated_at`
`2026-07-06T09:29:49`; task-reported recovery lag 500–700 s.

---

## 2. Cadence audit of the other checks

The watchdog's job is to alarm on *feed death*, so each check's stale-after
must sit comfortably **above** the normal cadence of the thing it watches,
or it flaps. Observed cadences from this repo:

### sync_check (publish / snapshot heartbeat)
- **Observed cadence:** ~30–50 s during RTH. Consecutive `live IQFeed
  snapshot` commits on 2026-07-06: 11:01:01 → :33 → 11:02:05 → :38 →
  11:03:10 → :42 → 11:04:14 (~32 s median gap).
- **Guidance:** stale-after should be ≥5–10× the heartbeat to survive a
  single skipped push. Recommend **≥5 min**. If the current value is under
  ~3 min it is too tight and will flap on a normal gap — **verify against
  `feed_watchdog.py`.**

### backups
- **Observed cadence:** per-dispatch / per-deploy, **event-driven**, not
  clock-periodic. `.bak` snapshots exist for D51, D54, D55, and the
  D73–D84 batch; deploys are irregular (e.g. 2026-06-30, then 2026-07-06).
- **Guidance:** a wall-clock stale-after is a category mismatch here — it
  will false-alarm on any day without a dispatch. The check should assert
  **"a fresh backup exists for the latest deploy"** (event-gated), not
  "a backup was written in the last N minutes." If a time threshold is
  unavoidable, scale it to the *deploy* cadence (days), not minutes.
  **Verify how this check is currently expressed.**

### md5s
- **Observed cadence:** per-deploy integrity sidecars (`index.html.md5.deployed`,
  `dispatch44.md5`, `MD5SUMS*.txt`), written once per deploy.
- **Guidance:** this is an **integrity** check (md5 match), not a freshness
  check — it should fire on a *mismatch* against the deployed hash, not on
  elapsed time. Any staleness component should be tied to the last-deploy
  timestamp, not a fixed minute window. **Verify.**

**Summary:** only the Inside Bar check has a confirmed wrong threshold and a
confirmed fix (→15 min). `sync_check` should be confirmed ≥5 min. `backups`
and `md5s` are event-driven by nature; if either is currently implemented as
a fixed wall-clock stale-after, that is the likely source of any further
spurious flaps and should be re-expressed as event/integrity checks. These
three are flagged for confirmation against the actual `feed_watchdog.py`,
which was not reachable from the authoring session.

---

## 3. Deploy (on the Mac / `Arsenal-Trading`)

1. In `feed_watchdog.py`, find the Inside Bar check's stale-after threshold
   (likely `8` minutes or `480` seconds, or an entry in a per-check
   thresholds map keyed to `inside_bar` / `inside_bar_state`).
2. Change it to **15 min (900 s)**.
3. While there, confirm `sync_check` ≥ 5 min and review whether `backups` /
   `md5s` are wall-clock or event/integrity checks per §2.
4. Reload the launchd job: `launchctl kickstart -k gui/$UID/com.arsenal.watchdog`
   (or unload/load the plist).
5. Confirm no Inside Bar flap over the next session.
