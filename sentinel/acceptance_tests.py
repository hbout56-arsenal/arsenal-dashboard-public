#!/usr/bin/env python3
"""
sentinel/acceptance_tests.py — DISPATCH 114 · the six required acceptance tests

All six MUST pass before the plist goes live. Each test drives the frozen SENTINEL
qualifier (sentinel.qualify) with a fixture that encodes the internals + event state
for the cited session. The fixtures are reconstructed from the 30-day sent-alert
EVIDENCE in the dispatch (this public repo archives OHLCV + an internals *flag*, not
the raw ADD/VOLD/TRIN/TICK series for July/August), so the tests validate the GATE
LOGIC against the documented ground-truth scenarios — which is exactly what decides
whether a fire is allowed.

  A) Replay 8/3        => ZERO alerts (all six fail slope gates)
  B) Replay 7/16 10:49 => MUST fire Cluster Fade SHORT (the +$150 trade)
  C) Replay 7/22 10:37 => MUST fire pullback-hold LONG (ALIGNED_UP)
  D) Replay 7/24 11:35 => must NOT fire (first-touch, ADD rising into a short)
  E) Debounce          => two tags of 7618 => exactly one email
  F) Window            => a 9:32 / 15:46 qualifying setup => logged, not emailed

Run:  python3 sentinel/acceptance_tests.py     # prints all six results, exit!=0 on any fail
"""
from __future__ import annotations
from typing import List
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sentinel import (  # noqa: E402
    Candidate, Internals, SessionState, qualify,
    SETUP_CLUSTER_FADE, SETUP_PULLBACK_HOLD, FULL_ROWS,
)


def _lin(start: float, end: float, n: int = FULL_ROWS) -> List[float]:
    step = (end - start) / (n - 1)
    return [round(start + step * i, 3) for i in range(n)]


def _flat(v: float, n: int = FULL_ROWS) -> List[float]:
    return [v] * n


# ── fixtures (reconstructed from the dispatch evidence) ───────────────────────
def fx_8_3_cluster_fade(ts: str, level: float) -> Candidate:
    """8/3 trending grind: ADD rising, VOLD rising, TRIN falling all session — a SHORT
    here fails the slope gate (the OR-clause is false). One of the six ascending fades."""
    return Candidate(
        ts_et=ts, date="2026-08-03", setup=SETUP_CLUSTER_FADE, direction="SHORT",
        level=level, level_name="cluster", entry=level - 1, stop=level + 9,
        t1=level - 16, t2=level - 28, invalidating_extreme=level + 1, atr5m=4.0,
        internals=Internals(add=_lin(300, 1200), vold=_lin(-200e6, 600e6),
                            trin=_lin(1.5, 0.7), tick=_lin(-50, 400), feed_age_s=10),
        pool_tagged=True, rejected_within_bars=2,
    )


def fx_7_16_cluster_fade() -> Candidate:
    """7/16 10:49: TRIN rising, VOLD falling, TICK negative at the highs — the +$150 short."""
    return Candidate(
        ts_et="10:49", date="2026-07-16", setup=SETUP_CLUSTER_FADE, direction="SHORT",
        level=7618.0, level_name="cluster-VAH", entry=7617.0, stop=7627.0, t1=7601.0,
        t2=7589.0, invalidating_extreme=7620.0, atr5m=4.0,
        internals=Internals(add=_lin(950, 350), vold=_lin(450e6, -350e6),
                            trin=_lin(0.85, 1.7), tick=_lin(-120, -380), feed_age_s=12),
        pool_tagged=True, rejected_within_bars=2,
    )


def fx_7_22_pullback_hold() -> Candidate:
    """7/22 10:37: ALIGNED_UP — ADD rising, VOLD rising, TRIN falling; price held support."""
    return Candidate(
        ts_et="10:37", date="2026-07-22", setup=SETUP_PULLBACK_HOLD, direction="LONG",
        level=7500.0, level_name="pullback-VAL", entry=7502.0, stop=7492.0, t1=7518.0,
        t2=7530.0, invalidating_extreme=7499.0, atr5m=4.0,
        internals=Internals(add=_lin(300, 1050), vold=_lin(-200e6, 550e6),
                            trin=_lin(1.5, 0.75), tick=_lin(-50, 320), feed_age_s=11),
        pool_tagged=True, rejected_within_bars=2, aligned="ALIGNED_UP",
    )


def fx_7_24_first_touch() -> Candidate:
    """7/24 11:35: first-touch short with ADD RISING — must not fire (slope gate + no rejection)."""
    return Candidate(
        ts_et="11:35", date="2026-07-24", setup=SETUP_CLUSTER_FADE, direction="SHORT",
        level=7660.0, level_name="cluster", entry=7659.0, stop=7669.0, t1=7643.0,
        t2=7631.0, invalidating_extreme=7661.0, atr5m=4.0,
        internals=Internals(add=_lin(400, 1150), vold=_lin(-100e6, 500e6),
                            trin=_lin(1.4, 0.8), tick=_lin(-40, 300), feed_age_s=10),
        pool_tagged=False, rejected_within_bars=None,  # first-touch: no rejection yet
    )


# ── the six tests ─────────────────────────────────────────────────────────────
def test_A() -> bool:
    """8/3: replay all six ascending Cluster Fades => ZERO emails. Some of the original fire
    times are off-window (they trip WINDOW), so to honor the dispatch's mechanism claim
    ("all six fail the slope gates — VOLD rising, TRIN falling all session") each fire is
    ALSO evaluated at an in-window time (11:00): every one must fail the slope gate."""
    sess = SessionState(date="2026-08-03")
    fires = [("09:32", 7566.0), ("11:05", 7618.0), ("11:26", 7614.0),
             ("12:13", 7603.0), ("12:54", 7606.0), ("13:21", 7618.0)]
    emitted = 0
    reasons = []
    all_slope_fail = True
    for ts, lvl in fires:
        d = qualify(fx_8_3_cluster_fade(ts, lvl), sess)
        reasons.append(f"{ts}@{lvl}->{d.reason}")
        if d.emit_email():
            emitted += 1
        # in-window probe (fresh session so debounce/cap don't mask the slope verdict)
        probe = fx_8_3_cluster_fade("11:00", lvl)
        dp = qualify(probe, SessionState(date="2026-08-03"))
        if not dp.reason.startswith("SLOPE"):
            all_slope_fail = False
    ok = emitted == 0 and all_slope_fail
    print(f"  A) 8/3 zero alerts: emitted={emitted}  all_fail_slope_in_window={all_slope_fail}  "
          f"[{'PASS' if ok else 'FAIL'}]")
    print(f"       {'; '.join(reasons)}")
    return ok


def test_B() -> bool:
    d = qualify(fx_7_16_cluster_fade(), SessionState(date="2026-07-16"))
    ok = d.emit_email() and d.alert["subject"] == "TRADE: Cluster Fade SHORT 7617.0"
    print(f"  B) 7/16 10:49 fires SHORT: qualified={d.qualified} reason={d.reason}  "
          f"[{'PASS' if ok else 'FAIL'}]")
    if d.alert:
        print(f"       subject: {d.alert['subject']}")
    return ok


def test_C() -> bool:
    d = qualify(fx_7_22_pullback_hold(), SessionState(date="2026-07-22"))
    ok = d.emit_email() and d.alert["subject"].startswith("TRADE: Pullback-Hold LONG")
    print(f"  C) 7/22 10:37 fires LONG: qualified={d.qualified} reason={d.reason}  "
          f"[{'PASS' if ok else 'FAIL'}]")
    if d.alert:
        print(f"       subject: {d.alert['subject']}")
    return ok


def test_D() -> bool:
    """7/24 11:35 must NOT fire. At 11:35 the window (closes 11:30) also trips, so to prove
    the INTENDED disqualifier (first-touch, ADD rising into a short) we re-check the SAME
    setup moved to an in-window time: it must still be suppressed, on the slope or event
    gate — never emitted."""
    d = qualify(fx_7_24_first_touch(), SessionState(date="2026-07-24"))
    at_1135_ok = not d.emit_email()

    inwin = fx_7_24_first_touch()
    inwin.ts_et = "11:25"  # inside the morning window — isolates the slope/event gate
    d2 = qualify(inwin, SessionState(date="2026-07-24"))
    gate_ok = (not d2.emit_email()) and (d2.reason.startswith("SLOPE") or d2.reason.startswith("EVENT"))

    ok = at_1135_ok and gate_ok
    print(f"  D) 7/24 first-touch short does NOT fire: 11:35->{d.reason}, "
          f"in-window(11:25)->{d2.reason}  [{'PASS' if ok else 'FAIL'}]")
    return ok


def test_E() -> bool:
    """Two tags of 7618 in one session => exactly one email (debounce)."""
    sess = SessionState(date="2026-07-16")
    first = fx_7_16_cluster_fade()               # 10:49 @ 7618
    second = fx_7_16_cluster_fade()
    second.ts_et = "11:05"                        # later, same level 7618
    d1 = qualify(first, sess)
    d2 = qualify(second, sess)
    emails = int(d1.emit_email()) + int(d2.emit_email())
    ok = emails == 1 and d1.emit_email() and (not d2.emit_email()) and d2.reason == "DEBOUNCE"
    print(f"  E) debounce 7618 x2: emails={emails} second_reason={d2.reason}  "
          f"[{'PASS' if ok else 'FAIL'}]")
    return ok


def test_F() -> bool:
    """A qualifying setup at 9:32 and at 15:46 => logged, not emailed (window)."""
    early = fx_7_16_cluster_fade()
    early.ts_et = "09:32"
    early.date = "2026-07-30"
    late = fx_7_16_cluster_fade()
    late.ts_et = "15:46"
    late.date = "2026-07-28"
    d_early = qualify(early, SessionState(date="2026-07-30"))
    d_late = qualify(late, SessionState(date="2026-07-28"))
    ok = ((not d_early.emit_email()) and d_early.reason == "WINDOW"
          and (not d_late.emit_email()) and d_late.reason == "WINDOW")
    print(f"  F) window 9:32 & 15:46: early={d_early.reason} late={d_late.reason}  "
          f"[{'PASS' if ok else 'FAIL'}]")
    return ok


def run_all() -> int:
    print("SENTINEL D114 acceptance tests")
    print("=" * 60)
    results = {
        "A": test_A(), "B": test_B(), "C": test_C(),
        "D": test_D(), "E": test_E(), "F": test_F(),
    }
    print("=" * 60)
    passed = sum(1 for v in results.values() if v)
    for k, v in results.items():
        print(f"  {k}: {'PASS' if v else 'FAIL'}")
    print(f"\n{passed}/6 passed — "
          f"{'ALL PASS — plist may go live' if passed == 6 else 'DO NOT ENABLE'}")
    return 0 if passed == 6 else 1


if __name__ == "__main__":
    sys.exit(run_all())
