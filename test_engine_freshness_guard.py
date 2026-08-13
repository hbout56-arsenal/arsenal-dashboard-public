#!/usr/bin/env python3
"""
test_engine_freshness_guard.py  —  7 unit tests for the staleness guard.

Run:  python3 test_engine_freshness_guard.py        (no pytest dependency)

The seven cases map 1:1 to the dispatch contract:
  1. healthy feed within budget during RTH        -> LIVE, no alert
  2. feed goes stale during RTH                    -> incident opens, P3
  3. still dark 30 min later                       -> SUPPRESSED (<1h)
  4. still dark >1h / >2h later                    -> escalates P2 then P1
  5. stale OUTSIDE RTH (overnight)                 -> no incident, no alert
  6. genuinely newer row lands                     -> RECOVERED, gap logged
  7. same old row re-pushed (not newer)            -> NOT recovered (P2 guard)
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from engine_freshness_guard import staleness_check, in_rth

ET = ZoneInfo("America/New_York")


def et(y, m, d, hh, mm, ss=0):
    """A wall-clock instant expressed in Eastern, returned as aware UTC."""
    return datetime(y, m, d, hh, mm, ss, tzinfo=ET).astimezone(timezone.utc)


PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}")


# 2026-08-11 (Tue) and 2026-08-12 (Wed) are weekdays -> valid RTH sessions.

def test_1_healthy_within_budget():
    now = et(2026, 8, 12, 9, 45)           # RTH
    row = (now - timedelta(seconds=60)).isoformat()
    r = staleness_check(now, "internals_snapshot", row, {})
    check("1 healthy: status LIVE", r["status"] == "LIVE")
    check("1 healthy: no alert", r["alert"] is None)
    check("1 healthy: last_good_row recorded",
          r["state"].get("last_good_row_ts") is not None)


def test_2_open_incident_p3():
    now = et(2026, 8, 12, 9, 50)           # RTH, ~staleness discovery time
    # last fresh row was at 09:34, i.e. 16 min ago (> 15m budget)
    row = et(2026, 8, 12, 9, 34).isoformat()
    prior = {"last_good_row_ts": row}
    r = staleness_check(now, "internals_snapshot", row, prior)
    check("2 open: status DARK", r["status"] == "DARK")
    check("2 open: alert present", r["alert"] is not None)
    check("2 open: severity P3", r["alert"]["severity"] == "P3")
    check("2 open: incident_open persisted",
          r["state"].get("incident_open") is True)
    check("2 open: failure_row_ts captured",
          r["state"].get("failure_row_ts") == row)


def test_3_suppressed_within_hour():
    open_now = et(2026, 8, 12, 9, 50)
    row = et(2026, 8, 12, 9, 34).isoformat()
    opened = staleness_check(open_now, "internals_snapshot", row,
                             {"last_good_row_ts": row})
    # 30 minutes later, still the same stale row
    later = et(2026, 8, 12, 10, 20)
    r = staleness_check(later, "internals_snapshot", row, opened["state"])
    check("3 suppress: status SUPPRESSED", r["status"] == "SUPPRESSED")
    check("3 suppress: no new alert", r["alert"] is None)
    check("3 suppress: still incident_open",
          r["state"].get("incident_open") is True)


def test_4_escalation_p2_then_p1():
    open_now = et(2026, 8, 12, 9, 50)
    row = et(2026, 8, 12, 9, 34).isoformat()
    st = staleness_check(open_now, "internals_snapshot", row,
                         {"last_good_row_ts": row})["state"]
    # +1h05 -> still dark, hourly re-alert due, gap ~1h -> P2
    t2 = et(2026, 8, 12, 10, 55)
    r2 = staleness_check(t2, "internals_snapshot", row, st)
    check("4 escalate: P2 fires at ~1h", r2["alert"] and
          r2["alert"]["severity"] == "P2")
    st = r2["state"]
    # +2h05 from open -> gap >=2h -> P1
    t3 = et(2026, 8, 12, 11, 55)
    r3 = staleness_check(t3, "internals_snapshot", row, st)
    check("4 escalate: P1 fires at >=2h", r3["alert"] and
          r3["alert"]["severity"] == "P1")


def test_5_offhours_no_alarm():
    now = et(2026, 8, 11, 20, 30)          # 8:30pm ET, market closed
    check("5 offhours: in_rth False", in_rth(now) is False)
    # last row from the 16:00 close, hours old, but off-hours => no incident
    row = et(2026, 8, 11, 16, 0).isoformat()
    r = staleness_check(now, "internals_snapshot", row, {})
    check("5 offhours: no incident opened",
          not r["state"].get("incident_open"))
    check("5 offhours: no alert", r["alert"] is None)


def test_6_recovered_on_newer_row():
    open_now = et(2026, 8, 12, 9, 50)
    failure_row = et(2026, 8, 12, 9, 34).isoformat()
    st = staleness_check(open_now, "internals_snapshot", failure_row,
                         {"last_good_row_ts": failure_row})["state"]
    # collector restarts; a genuinely newer row lands at 10:05
    recov_now = et(2026, 8, 12, 10, 5)
    newer = et(2026, 8, 12, 10, 5).isoformat()
    r = staleness_check(recov_now, "internals_snapshot", newer, st)
    check("6 recover: status RECOVERED", r["status"] == "RECOVERED")
    check("6 recover: recovered payload present", r["recovered"] is not None)
    check("6 recover: dark gap logged into state",
          r["state"].get("last_dark_gap_wall_s") is not None)
    check("6 recover: incident closed",
          r["state"].get("incident_open") is False)
    check("6 recover: recovered row newer than failure",
          r["recovered"]["recovered_row_ts"] > r["recovered"]["failure_row_ts"])


def test_7_no_recovery_on_stale_repush():
    open_now = et(2026, 8, 12, 9, 50)
    failure_row = et(2026, 8, 12, 9, 34).isoformat()
    st = staleness_check(open_now, "internals_snapshot", failure_row,
                         {"last_good_row_ts": failure_row})["state"]
    # push machinery flaps and re-pushes the SAME old row (not newer)
    later = et(2026, 8, 12, 10, 55)        # >1h so a re-alert is due
    r = staleness_check(later, "internals_snapshot", failure_row, st)
    check("7 no-recovery: NOT marked RECOVERED", r["status"] != "RECOVERED")
    check("7 no-recovery: recovered payload absent", r["recovered"] is None)
    check("7 no-recovery: incident stays open",
          r["state"].get("incident_open") is True)


if __name__ == "__main__":
    for fn in (test_1_healthy_within_budget, test_2_open_incident_p3,
               test_3_suppressed_within_hour, test_4_escalation_p2_then_p1,
               test_5_offhours_no_alarm, test_6_recovered_on_newer_row,
               test_7_no_recovery_on_stale_repush):
        print(fn.__name__)
        fn()
    total = PASS + FAIL
    print(f"\n{PASS}/{total} checks passed across 7 test cases")
    raise SystemExit(1 if FAIL else 0)
