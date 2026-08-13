#!/usr/bin/env python3
"""
engine_freshness_guard.py  —  WALL-CLOCK STALENESS ALARM FOR THE FEEDS
=====================================================================

Why this exists (collector-down-42h post-mortem)
-------------------------------------------------
``build_trade_state.py`` anchors its age math to the NEWEST published feed
timestamp (``reference_now()``). That is correct for RENDERING *relative*
lag on a snapshot mirror — the freshest feed reads ~0s and every staler feed
shows its true lag against it. But it has one blind spot: if the whole
collector / write / push chain dies, every feed freezes TOGETHER, the
"newest feed" is itself stale, every feed reads ~0s, and the board renders
LIVE. The mirror lies FRESH (the D64 "frozen mirror lied FRESH for a week"
failure). That blind spot is exactly how a 42h outage went unnoticed across
two full sessions.

This guard answers the *other* question the anchored clock cannot:
**is the newest row actually recent against the real wall clock, right now?**
It is deliberately independent of the reference-clock anchoring so a total
freeze cannot mask itself.

Contract (matches the dispatch)
-------------------------------
  * Alarm ONLY during RTH (Mon-Fri 09:30-16:00 America/New_York), optionally
    minus a holiday set. Off-hours staleness is expected, not an incident.
  * A feed whose newest row is older than its budget (default 15 min for the
    intraday tape) during RTH opens an incident and emits a P3 alert.
  * While an incident is open, emit AT MOST ONE alert per hour, escalating
    with the outage duration:  <1h => P3,  1-2h => P2,  >=2h => P1.
  * RECOVERED fires ONLY when a row arrives that is STRICTLY NEWER than the
    last-good row captured when the incident opened (the P2 predicate) — not
    merely "some feed is fresh now", and never on a re-push of the same old
    row. On first recovery the dark-gap duration is written into the state.

Reuse (apply to BOTH the collector and the ict/fvg engines)
-----------------------------------------------------------
``staleness_check()`` is a PURE function of (now, newest_row_ts, budget,
prior per-feed state). It returns the alert/recovery decision plus the next
state; it neither reads a clock nor sends mail itself. Callers wire their own
side effects:

    collector / ict / fvg  (Mac-side):  notifier = send_email
    dashboard mirror       (this repo):  sink     = record into trade_state

``run_guard()`` is the batteries-included driver: it loads a persisted
state file, runs the check for each configured feed against ``datetime.now``,
persists the new state, and calls an injected ``notifier`` for every alert /
recovery. That single driver is what both the Mac engines and the mirror
import — same predicate, different notifier.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Intraday tape budget: a live 60s collector that has gone >15 min without a
# fresh row during RTH is down, not merely slow.
DEFAULT_BUDGET_S = 15 * 60
ALERT_INTERVAL_S = 60 * 60          # at most one alert per hour per feed
ESCALATE_P2_S = 60 * 60             # >=1h open  -> P2
ESCALATE_P1_S = 2 * 60 * 60         # >=2h open  -> P1


# ----------------------------------------------------------------------------
# time helpers (all injectable so tests are deterministic)
# ----------------------------------------------------------------------------

def _parse_ts(val):
    """ISO-ish string (or datetime) -> aware UTC datetime, or None."""
    if isinstance(val, datetime):
        dt = val
    elif isinstance(val, str) and val.strip():
        s = val.strip().replace("Z", "+00:00")
        for tag in (" ET", " UTC"):
            if s.endswith(tag):
                s = s[: -len(tag)].strip()
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            try:
                dt = datetime.strptime(s.split(".")[0], "%Y-%m-%dT%H:%M:%S")
            except ValueError:
                return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def in_rth(now, holidays=frozenset()):
    """True iff `now` is inside Mon-Fri 09:30-16:00 America/New_York."""
    dt = _parse_ts(now)
    if dt is None:
        return False
    et = dt.astimezone(ET)
    if et.weekday() >= 5:                      # Sat/Sun
        return False
    if et.date().isoformat() in holidays:
        return False
    open_et = et.replace(hour=9, minute=30, second=0, microsecond=0)
    close_et = et.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_et <= et <= close_et


def severity_for_gap(gap_s):
    """Escalating severity from outage duration."""
    if gap_s >= ESCALATE_P1_S:
        return "P1"
    if gap_s >= ESCALATE_P2_S:
        return "P2"
    return "P3"


# ----------------------------------------------------------------------------
# the pure predicate — this is the guard
# ----------------------------------------------------------------------------

def staleness_check(now, feed, newest_row_ts, state, *,
                    budget_s=DEFAULT_BUDGET_S,
                    alert_interval_s=ALERT_INTERVAL_S,
                    holidays=frozenset()):
    """
    Decide the freshness action for one feed. Pure: no clock, no I/O.

    Parameters
    ----------
    now            : wall-clock instant (aware datetime or ISO string).
    feed           : feed label, e.g. "internals_snapshot".
    newest_row_ts  : timestamp of the feed's newest data row (or None).
    state          : prior per-feed state dict (``{}`` on first ever call).
    budget_s       : max tolerated row age before the feed is considered dark.

    Returns
    -------
    dict with:
      feed        : echoed label
      status      : LIVE | DARK | RECOVERED | SUPPRESSED
      age_s       : newest-row age against `now` (None if no row)
      alert       : None, or {severity, feed, gap_s, message}
      recovered   : None, or {dark_gap_wall_s, dark_gap_row_s, failure_row_ts,
                              recovered_row_ts, message}
      state       : NEXT per-feed state dict (persist this)
    """
    now_dt = _parse_ts(now)
    row_dt = _parse_ts(newest_row_ts)
    st = dict(state or {})

    age_s = None if row_dt is None else int((now_dt - row_dt).total_seconds())
    is_stale = row_dt is None or age_s > budget_s
    rth = in_rth(now_dt, holidays)

    result = {"feed": feed, "age_s": age_s, "alert": None,
              "recovered": None, "status": "LIVE"}

    incident_open = bool(st.get("incident_open"))

    if not incident_open:
        if is_stale and rth:
            # ---- open a new incident ----
            failure_row = st.get("last_good_row_ts") or (
                row_dt.isoformat() if row_dt else None)
            st["incident_open"] = True
            st["failure_row_ts"] = failure_row
            st["opened_at"] = now_dt.isoformat()
            st["last_alert_at"] = now_dt.isoformat()
            st["escalation"] = "P3"
            result["status"] = "DARK"
            result["alert"] = {
                "severity": "P3", "feed": feed, "gap_s": age_s,
                "message": (f"{feed}: no fresh row for "
                            f"{_hms(age_s)} during RTH "
                            f"(budget {budget_s // 60}m) — feed DARK"),
            }
        else:
            # healthy (or off-hours): remember the last good row
            if not is_stale and row_dt is not None:
                st["last_good_row_ts"] = row_dt.isoformat()
            result["status"] = "LIVE"
        result["state"] = st
        return result

    # ---- an incident is already open ----
    failure_row = _parse_ts(st.get("failure_row_ts"))
    opened_at = _parse_ts(st.get("opened_at")) or now_dt

    # recovery predicate: a row STRICTLY newer than the failure row.
    if row_dt is not None and (failure_row is None or row_dt > failure_row):
        dark_gap_wall = int((now_dt - opened_at).total_seconds())
        dark_gap_row = (int((row_dt - failure_row).total_seconds())
                        if failure_row else None)
        result["status"] = "RECOVERED"
        result["recovered"] = {
            "dark_gap_wall_s": dark_gap_wall,
            "dark_gap_row_s": dark_gap_row,
            "failure_row_ts": st.get("failure_row_ts"),
            "recovered_row_ts": row_dt.isoformat(),
            "message": (f"{feed}: RECOVERED — fresh row "
                        f"{row_dt.isoformat()} newer than failure "
                        f"{st.get('failure_row_ts')}; dark gap "
                        f"{_hms(dark_gap_wall)}"),
        }
        # close incident, record the gap, reset to healthy tracking
        st = {
            "incident_open": False,
            "last_good_row_ts": row_dt.isoformat(),
            "last_dark_gap_wall_s": dark_gap_wall,
            "last_dark_gap_row_s": dark_gap_row,
            "last_recovered_at": now_dt.isoformat(),
            "last_failure_row_ts": st.get("failure_row_ts"),
        }
        result["state"] = st
        return result

    # still dark. Re-alert at most once per hour during RTH, escalating.
    last_alert = _parse_ts(st.get("last_alert_at")) or opened_at
    open_gap = int((now_dt - opened_at).total_seconds())
    due = (now_dt - last_alert).total_seconds() >= alert_interval_s
    if rth and due:
        sev = severity_for_gap(open_gap)
        st["last_alert_at"] = now_dt.isoformat()
        st["escalation"] = sev
        result["status"] = "DARK"
        result["alert"] = {
            "severity": sev, "feed": feed, "gap_s": age_s,
            "message": (f"{feed}: STILL DARK for {_hms(open_gap)} "
                        f"(row age {_hms(age_s)}) — escalated {sev}"),
        }
    else:
        # in incident but not time to re-alert (or off-hours)
        result["status"] = "SUPPRESSED"
    result["state"] = st
    return result


def _hms(seconds):
    if seconds is None:
        return "unknown"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


# ----------------------------------------------------------------------------
# batteries-included driver (imported by BOTH collector and mirror)
# ----------------------------------------------------------------------------

def run_guard(feeds, *, state_path, now=None, notifier=None,
              holidays=frozenset()):
    """
    Run staleness_check for each feed, persist state, dispatch notifications.

    feeds     : iterable of dicts:
                  {"feed": str, "newest_row_ts": str|None, "budget_s": int?}
    state_path: JSON file holding per-feed guard state across runs.
    now       : wall clock (defaults to datetime.now(UTC)). Injected in tests.
    notifier  : callable(kind, payload) invoked for every "alert" and
                "recovered". kind in {"alert","recovered"}. On the Mac this
                sends email; on the mirror it records into trade_state.
    Returns the list of per-feed result dicts.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    all_state = _load_state(state_path)
    results = []
    for spec in feeds:
        feed = spec["feed"]
        res = staleness_check(
            now, feed, spec.get("newest_row_ts"),
            all_state.get(feed, {}),
            budget_s=spec.get("budget_s", DEFAULT_BUDGET_S),
            holidays=holidays,
        )
        all_state[feed] = res["state"]
        if notifier:
            if res["alert"]:
                notifier("alert", res["alert"])
            if res["recovered"]:
                notifier("recovered", res["recovered"])
        results.append(res)
    _save_state(state_path, all_state)
    return results


def _load_state(path):
    try:
        with open(path) as fh:
            data = json.load(fh)
        return data.get("feeds", {}) if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(path, feeds_state):
    payload = {
        "schema": "freshness_guard_state/1",
        "note": "wall-clock staleness incidents per feed; managed by "
                "engine_freshness_guard.run_guard",
        "feeds": feeds_state,
    }
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh, indent=2, default=str)
        fh.write("\n")
    os.replace(tmp, path)


if __name__ == "__main__":
    # Smoke run against internals_snapshot.json in the same dir, wall clock.
    here = os.path.dirname(os.path.abspath(__file__))
    snap_path = os.path.join(here, "internals_snapshot.json")
    try:
        with open(snap_path) as fh:
            snap = json.load(fh)
        newest = snap.get("latest_row_ts") or snap.get("pushed_at")
    except (OSError, ValueError):
        newest = None

    def _print_notifier(kind, payload):
        print(f"[{kind.upper()}] {payload.get('message')}")

    out = run_guard(
        [{"feed": "internals_snapshot", "newest_row_ts": newest}],
        state_path=os.path.join(here, "freshness_guard_state.json"),
        notifier=_print_notifier,
    )
    for r in out:
        print(json.dumps({k: v for k, v in r.items() if k != "state"},
                         indent=2, default=str))
