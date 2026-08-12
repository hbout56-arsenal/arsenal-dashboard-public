# Arsenal feed VM — ops runbook

The dashboard JSON in this repo is generated and pushed by the **Arsenal VM**
(a Parallels guest running on the macOS host). When the guest, its feed
bridge, or its launchd pusher dies, the dashboard silently freezes — the
`feed_status` field can still read `FRESH` even though `pushed_at` is hours or
days old.

> Reference incident: the feed went dark at **2026-08-10 16:04 ET**
> (`internals_snapshot.json → pushed_at`) with no fresh commits after
> `2026-08-10 18:32 ET`.

## Quick diagnosis

Run the doctor **on the macOS host** (not in a Linux/web session — it needs
`prlctl`, `launchctl`, and a route to the guest):

```bash
ops/arsenal_vm_doctor.sh          # read-only: diagnose, change nothing
ops/arsenal_vm_doctor.sh --start  # also boot the VM if it is stopped
```

It runs every check below and prints one verdict:

- **ALL CLEAR** — VM up, port open, feed fresh.
- **DEGRADED** — a WARN needs a look.
- **DOWN** — the feed is broken; act on the FAIL lines.

Exit code equals severity (`0` / `1` / `2`), so it is cron/CI friendly.

## What it checks (the manual runbook it replaces)

| # | Check | Manual command |
|---|-------|----------------|
| 1 | VM running | `prlctl list -a` → `prlctl start <vm>` (wait ~60s for IQConnect auto-login) |
| 2 | Feed bridge port open | `nc -zv 10.211.55.3 5009` |
| 3 | launchd pusher loaded | `launchctl list \| grep -i arsenal` |
| 4 | Feed log advancing | `tail -50 ~/arsenal/logs/internals_live*.log` |
| 5 | Dashboard not stale | `pushed_at` in `internals_snapshot.json` vs. wall clock |

## Configuration

Every default is env-overridable:

| Var | Default | Meaning |
|-----|---------|---------|
| `VM_NAME` | *(auto-detect `/arsenal/i`)* | Parallels VM name |
| `VM_HOST` | `10.211.55.3` | guest IP |
| `VM_PORT` | `5009` | feed/IQFeed bridge port on the guest |
| `LOG_GLOB` | `~/arsenal/logs/internals_live*.log` | feed log(s) |
| `SNAPSHOT` | `../internals_snapshot.json` | dashboard snapshot to age-check |
| `MAX_AGE_MIN` | `15` | older than this ⇒ STALE |
| `STARTUP_WAIT` | `60` | seconds to wait after `--start` |

Example: `VM_NAME="Arsenal" VM_PORT=5010 ops/arsenal_vm_doctor.sh`

## Recovery order

1. **VM stopped** → `ops/arsenal_vm_doctor.sh --start` (or `prlctl start <vm>`).
2. **VM up but port 5009 closed** → the feed process on the guest is down;
   restart the feed bridge inside the guest.
3. **Port open but log not advancing** → IQConnect/IQFeed login or market
   data issue on the guest; check `internals_live*.log` for auth/errors.
4. **All up but dashboard stale** → the launchd pusher isn't committing;
   check the `arsenal` launchd job's last exit status (check 3).

Re-run the doctor after each step until the verdict is **ALL CLEAR**.

> Note: off-market hours, the feed legitimately stops updating, so check 5
> will read STALE overnight/weekends. That is expected — correlate with
> checks 1–4 before treating staleness as a failure.
