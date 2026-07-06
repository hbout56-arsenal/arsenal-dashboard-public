# Watchdog Fix Spec — feed-staleness flap + internals reconnect

Ready-to-apply spec for two `[MAC-LOCAL]` watchdog fixes. Authored from the cloud
publish repo, which does **not** contain the watchdog source — apply on the Mac.

---

## 0. Scope honesty

This repo (`arsenal-dashboard-public`) is a **publish target**. It receives the built
`index.html` and the JSON state your Mac pushes (`live IQFeed snapshot…`,
`daily_audit: advisory feed refresh…`). The files these fixes touch —
`feed_watchdog.py`, `daily_audit.py`, `internals_live.py`, `inside_bar_state.py`,
`sync_check.sh` — have **never** been tracked here (verified across full history, all
branches). So this document is a **spec, not a patch to runnable code in this repo**.
Creating those `.py` files here would be dangerous: the publish/`sync_check.sh` flow
could sync phantom files back over the real Mac scripts. Everything below is written to
be pasted/adapted into the actual Mac source; anything I could not read on the Mac is
marked **`(confirm on Mac)`**.

Evidence used is what the Mac already pushed into this repo:
`internals_snapshot.json`, `daily_audit_latest.json`, and the dashboard's own
client-side freshness constants in `index.html`.

---

## 1. Inside Bar feed check — stop the flap (8 min → 15 min) + threshold audit

### 1.1 Why it flapped 6× today

The check trips because its **stale-after (~8 min = 480 s) is below `inside_bar_state`'s
recompute cadence**. Observed healthy lag today was **500–880 s** — i.e. even the *best*
healthy cycle (500 s) already exceeds the 480 s threshold, and the worst (880 s ≈
14.7 min) exceeds it by nearly double. So the check goes STALE in the gap between every
recompute and RECOVERS on the next write → 6 stale→recovered flaps, each while the feed
was actually healthy. This is a threshold bug, not a feed problem.

### 1.2 Fix

Set inside_bar's stale-after to **15 min (900 s)** as requested.

```python
# feed_watchdog.py  (confirm exact structure on Mac)
# BEFORE
"inside_bar": {"stale_after_s": 480},          # ~8 min  -> trips inside every recompute gap
# AFTER
"inside_bar": {"stale_after_s": 900},          # 15 min  -> clears the 500-880s healthy band
```

**Headroom note:** 900 s clears the worst observed lag (880 s) by only ~20 s. If flaps
persist, bump to **960 s (16 min)** — the general rule below wants a margin over the p99
lag, and 20 s is thin. 15 min is the requested value and is correct as a first move.

### 1.3 Threshold-vs-cadence audit (the general rule)

**Rule:** `stale_after ≥ (nominal cadence) + (max jitter) + margin`, and never below
`~1.5–2× nominal cadence` for jobs whose write lag is bursty. A check whose stale-after
sits *below* its own job's cadence will flap by construction.

Fill the **current** column from the Mac config; the recommended column applies the rule.
Cadence sources: `internals_snapshot.json` note ("live IQFeed 60s; built by
price_refresh"), git push cadence, and the dashboard mirrors in `index.html`
(`FREEZE_MIN=15`, `STOCK_FREEZE_MIN=1500`, `IQF_STALE_MS=10 min`, `stale_after_hours||25`).

| check | job cadence | current stale-after | recommended | rationale |
|---|---|---|---|---|
| **inside_bar** | recompute; lag 500–880 s observed | **480 s (8 min)** ❌ flaps | **900 s (15 min)**; 960 s if it recurs | above the 880 s tail |
| internals/snapshot | 60 s (IQFeed, price_refresh) | `(confirm)` | 180–300 s **+ session-aware** | 3–5× cadence; **must not page after 16:00 cash close** — NYSE TICK/TRIN/ADD go quiet by design |
| verdict/meter | `(confirm)` — flagged STALE 99 m at 17:15 | `(confirm)` | ≥ 2× its cadence | downstream of internals; see §2.4 coalescing |
| prices (futures) | ~per snapshot; FRESH 19 m | `(confirm)` | ≥ 2× cadence | healthy today |
| ema_state (IQFeed px) | ~min; FRESH 4 m | `(confirm)` | ≥ 2× cadence | healthy today |
| ema_stocks (daily) | daily (~25 h) | `stale_after_hours or 25` (dashboard) | keep 25 h | daily cadence, matches `index.html:1139` |
| breadth | `(confirm)` — **DARK 10 days** | `(confirm)` | separate bug — not a threshold issue (no timestamp at all) |
| wave-chart bars | `(confirm)` — **STALE 7035 m / 3 days** | `(confirm)` | separate bug — genuinely stale, not a flap |
| perf / trendline / candle / wave scorecards | ~hourly/nightly; FRESH 0–83 m | `(confirm)` | ≥ 2× cadence | healthy today |

Two entries above (breadth DARK, wave-chart bars STALE 7035 m) are **real staleness, not
threshold flaps** — don't widen them; investigate the jobs. They're listed so the audit is
complete, per the task's "audit the other checks too."

---

## 2. internals_live.py — reconnect-on-drop + KeepAlive (self-heal within a cycle)

### 2.1 Diagnosis: loop/socket died, **not** a full IQConnect/VM drop

Timeline from the pushed artifacts:

| signal | last good | at audit (17:15) |
|---|---|---|
| `internals_snapshot.json` `pushed_at` | **16:04:39** (self-labels FRESH) | STALE 70 m |
| verdict/meter | ~15:36 | STALE 99 m |
| prices (futures) | — | **FRESH 19 m** ✅ |
| ema_state (IQFeed px) | — | **FRESH 4 m** ✅ |

**Tell:** futures prices and `ema_state` are *also* IQFeed-sourced and stayed **FRESH**
while internals froze at 16:04. A full IQConnect logout or VM drop would have killed
*every* IQFeed consumer, not just internals. So the fault is **inside `internals_live.py`'s
own socket/read loop** — it stopped emitting rows (silent half-open socket or a dead
`--loop`) while the rest of the IQFeed pipeline kept flowing. That is precisely the
failure reconnect-on-drop + KeepAlive is meant to auto-recover.

**Caveat:** 16:04 is 4 min after the 16:00 cash close, when NYSE internals legitimately go
quiet. The watchdog emails you can see (I can't) are the tiebreaker on whether this was a
true mid-session drop vs. an expected post-close quiet that the check mis-flagged. If the
latter, the §1.3 "session-aware, don't page after close" fix for internals also applies.

### 2.2 TCP KeepAlive on the IQFeed socket

Detects a half-open socket (VM sleep, network blip) in seconds instead of hanging silently.

```python
import socket
def _enable_keepalive(sock):
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    # macOS: TCP_KEEPALIVE is the idle time (seconds). Linux uses TCP_KEEPIDLE.
    if hasattr(socket, "TCP_KEEPALIVE"):            # macOS
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPALIVE, 15)
    if hasattr(socket, "TCP_KEEPIDLE"):             # Linux
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 15)
    if hasattr(socket, "TCP_KEEPINTVL"):
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 5)
    if hasattr(socket, "TCP_KEEPCNT"):
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
    return sock
# Call _enable_keepalive(sock) right after connect() to IQConnect (localhost:5009 Level1).
```

### 2.3 Reconnect-on-drop + in-loop stall watchdog

Two layers: reconnect when the socket errors, **and** an application-level stall detector
that forces a reconnect when no row has been written within `2× cadence` — this catches the
silent case (socket "up" but no data) that bit us at 16:04.

```python
STALL_LIMIT_S = 120          # 2x the 60s internals cadence
BACKOFF = [1, 2, 4, 8, 16, 30]

def run_loop():
    backoff_i = 0
    while True:
        try:
            sock = _enable_keepalive(connect_iqfeed())   # (confirm) your connect fn
            resend_watch_requests(sock)                  # re-subscribe TICK/TRIN/ADD/etc.
            backoff_i = 0
            last_row_at = now()
            for row in read_internals(sock):             # your existing read/parse loop
                write_internals_csv(row)                  # -> internals_live.csv
                last_row_at = now()
                # stall watchdog: no fresh row within 2x cadence -> force reconnect
                if now() - last_row_at > STALL_LIMIT_S:
                    raise ConnectionError("internals stall: no row in %ds" % STALL_LIMIT_S)
        except (OSError, ConnectionError) as e:
            log_warn("internals_live reconnect: %s" % e)
            try: sock.close()
            except Exception: pass
            time.sleep(BACKOFF[min(backoff_i, len(BACKOFF)-1)])
            backoff_i += 1
            continue                                     # self-heal, no external restart needed
```

If the read is blocking (no natural timeout to trip the stall check), set a socket read
timeout so the loop wakes to evaluate the stall: `sock.settimeout(STALL_LIMIT_S)` and treat
`socket.timeout` as a reconnect trigger.

### 2.4 Emit a heartbeat + coalesce the downstream cascade

- **Heartbeat field:** stamp `feed_status` / `last_reconnect_at` in `internals_snapshot.json`
  (mirror the existing `feed_status: FRESH` + `reader_note`) so downstream can tell
  "internals_live alive & reconnecting" from "dead."
- **Alert coalescing (fixes the 19:37 cluster):** the four downstream checks that fired
  together (breadth mirror + engine internals + verdicts + dashboard) are all *consumers* of
  internals. When internals is the known-stale **root**, suppress/dedupe the downstream
  pages so one root cause emits **one** alert, not five. Gate downstream staleness alerts on
  `internals_fresh` before paging.

### 2.5 IQConnect "Save Login + Auto-connect" (manual, recurring root cause)

`(manual GUI step — I can't reach the Mac)` In IQConnect's connection/login settings, tick
**Save Login** (save username/password) **and Auto-connect on startup**. Without both,
IQConnect will not re-authenticate after a VM restart/relogin, and every downstream IQFeed
consumer goes dark until you log in by hand — the recurring root cause behind these
cascades. Confirm both boxes are ticked.

---

## 3. Mac apply checklist (run on the Mac — cannot run from cloud)

```bash
# backups (dated)
cp feed_watchdog.py   feed_watchdog.py.$(date +%Y%m%d).bak
cp internals_live.py  internals_live.py.$(date +%Y%m%d).bak

# syntax checks
python3 -c "import py_compile,sys; py_compile.compile('feed_watchdog.py',  doraise=True)"
python3 -c "import py_compile,sys; py_compile.compile('internals_live.py', doraise=True)"
bash -n sync_check.sh

# md5s (paste the AFTER md5s back)
md5 feed_watchdog.py internals_live.py        # macOS

# re-upload the two changed .py to Project Knowledge, then:
./sync_check.sh
```

Then paste the post-change md5s.

---

## 4. What landed here vs. what's left for the Mac

- **Here (this repo):** this spec doc only. No data/engine files touched; no threshold is
  applied in the cloud (the watchdog doesn't run here).
- **Left for the Mac:** apply §1.2 threshold, fill/verify §1.3 audit against the real
  config, apply §2.2–2.4 to `internals_live.py`, confirm §2.5 IQConnect boxes, run §3.
