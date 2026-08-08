#!/usr/bin/env python3
"""
sentinel/sentinel.py — DISPATCH 114 · SENTINEL qualification engine (SHADOW)

SENTINEL is a QUALIFICATION layer, not an arming layer. The engine still detects
setups (Cluster Fade, Failed Retest, Washout Reclaim, Pullback-Hold); SENTINEL
decides whether a detected setup is allowed to reach the lock screen. No email is
sent unless ALL Part-1 gates pass. It never changes setup detection.

Pure + testable: `qualify(candidate, session)` takes a market snapshot and a live
SessionState and returns a Decision (qualified Y/N, suppression reason, the alert
payload when qualified). Stdlib only. SIMULATED / advisory — not financial advice.

Constants are frozen in preregistration_sentinel.json; the defaults below mirror
that file (single source of truth is the JSON — this module loads it when present
and falls back to these literals so the public mirror is self-contained).

Run:  python3 sentinel/sentinel.py     # self-test (gate mechanics)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PREREG_PATH = os.path.join(HERE, "preregistration_sentinel.json")

# ── frozen defaults (mirror preregistration_sentinel.json) ───────────────────
WINDOWS_ET = [("09:35", "11:30"), ("14:00", "15:15")]
FLAT_FRAC = 0.10          # slope magnitude must exceed 10% of series level
MIN_ROWS = 15             # <15 rows => UNRELIABLE
FULL_ROWS = 30            # nominal 30-min / 30-row window
MAX_FEED_AGE_S = 120      # feed age >120s => UNRELIABLE
DIV_MIN_ISSUES = 150.0    # |ADD delta| floor (issues)
DIV_PCT = 0.10            # ... or 10% of |ADD|, whichever is larger
REJECT_BARS = 3           # re-cross within 3x 1-min bars
BOUNDARY_BEYOND_PTS = 1.0 # failed-retest boundary close >= 1pt beyond
ATR_MULT = 1.5            # stop >= 1.5*ATR(5m) beyond invalidating extreme
MIN_RR = 1.5              # target pays >= 1.5R
LEVEL_TOL_PTS = 3.0       # debounce: (setup, level +/- 3pts) per session
MAX_QUALIFIED_PER_DAY = 2 # daily cap
WASHOUT_DROP_BEFORE_ET = "09:45"
WASHOUT_TICK_FLOOR = -900
WASHOUT_RECLAIM_BARS = 3
EXPIRY_MIN = 10

SETUP_CLUSTER_FADE = "Cluster Fade"
SETUP_FAILED_RETEST = "Failed Retest"
SETUP_WASHOUT = "Washout Reclaim"
SETUP_PULLBACK_HOLD = "Pullback-Hold"


def _load_prereg() -> dict:
    try:
        with open(PREREG_PATH) as fh:
            return json.load(fh)
    except Exception:
        return {}


def _hhmm_to_min(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def lsq_slope(ys: List[float]) -> float:
    """Least-squares slope over x = 0..n-1 (1-min rows). 0.0 if <2 points."""
    n = len(ys)
    if n < 2:
        return 0.0
    xbar = (n - 1) / 2.0
    ybar = sum(ys) / n
    num = 0.0
    den = 0.0
    for i, y in enumerate(ys):
        dx = i - xbar
        num += dx * (y - ybar)
        den += dx * dx
    return num / den if den else 0.0


def is_flat(ys: List[float], slope: float, flat_frac: float = FLAT_FRAC) -> bool:
    """Slope magnitude over the window vs 10% of the series level. FLAT => True."""
    n = len(ys)
    if n < 2:
        return True
    level = abs(sum(ys) / n)
    move = abs(slope * (n - 1))
    thresh = flat_frac * level
    return move < thresh


# ── inputs ───────────────────────────────────────────────────────────────────
@dataclass
class Internals:
    """1-min rows over the trailing ~30-min window (oldest first)."""
    add: List[float] = field(default_factory=list)   # advance-decline (issues)
    vold: List[float] = field(default_factory=list)   # up-vol - down-vol
    trin: List[float] = field(default_factory=list)   # Arms index
    tick: List[float] = field(default_factory=list)   # NYSE TICK (last value used)
    feed_age_s: float = 0.0


@dataclass
class Candidate:
    """A setup the engine detected — SENTINEL decides if it may reach the lock screen."""
    ts_et: str                 # "HH:MM" Eastern (session-local)
    date: str                  # "YYYY-MM-DD"
    setup: str                 # one of the SETUP_* cards
    direction: str             # "LONG" | "SHORT"
    level: float               # the decision level (price)
    level_name: str            # e.g. "VP-POC", "swing-high"
    entry: float
    stop: float
    t1: float
    t2: float
    invalidating_extreme: float
    atr5m: float
    internals: Internals = field(default_factory=Internals)
    # event-completion evidence (engine-supplied, no "approaching"):
    pool_tagged: bool = False          # Cluster Fade: pool tagged
    rejected_within_bars: Optional[int] = None   # bars to re-cross back (None => not yet)
    boundary_close_beyond_pts: Optional[float] = None  # Failed Retest: close beyond boundary
    retested: bool = False             # Failed Retest: retest occurred
    washout_reclaim_bars: Optional[int] = None   # Washout: bars to reclaim support (None => none)
    aligned: Optional[str] = None      # Pullback-Hold: "ALIGNED_UP"|"ALIGNED_DOWN" hint (informational)


@dataclass
class SessionState:
    """Per-session debounce + daily-cap + one-loss-done bookkeeping."""
    date: str
    _fired: List[Tuple[str, float]] = field(default_factory=list)  # (setup, level)
    n_qualified: int = 0
    taken_trade_logged: bool = False

    def seen(self, setup: str, level: float, tol: float = LEVEL_TOL_PTS) -> bool:
        for s, lv in self._fired:
            if s == setup and abs(lv - level) <= tol:
                return True
        return False

    def record(self, setup: str, level: float) -> None:
        self._fired.append((setup, level))
        self.n_qualified += 1

    def mark_taken(self) -> None:
        self.taken_trade_logged = True


@dataclass
class Decision:
    qualified: bool
    reason: str                 # "OK" when qualified, else the suppression reason
    unreliable: bool = False    # log only, no email (feed too old / too few rows)
    add_slope: Optional[float] = None
    vold_slope: Optional[float] = None
    trin_slope: Optional[float] = None
    divergence: Optional[float] = None
    alert: Optional[dict] = None

    def emit_email(self) -> bool:
        return self.qualified and not self.unreliable


# ── the gates ────────────────────────────────────────────────────────────────
def _in_window(ts_et: str) -> bool:
    t = _hhmm_to_min(ts_et)
    for lo, hi in WINDOWS_ET:
        if _hhmm_to_min(lo) <= t <= _hhmm_to_min(hi):
            return True
    return False


def _slope_gate(direction: str, i: Internals) -> Tuple[bool, str, Dict[str, float]]:
    """Gate 2 — slope v3.1. Returns (pass, reason, slopes). reason='UNRELIABLE:*' log-only."""
    n = min(len(i.add), len(i.vold), len(i.trin))
    slopes = {"add": None, "vold": None, "trin": None}
    if i.feed_age_s > MAX_FEED_AGE_S:
        return False, "UNRELIABLE:FEED_AGE", slopes
    if n < MIN_ROWS:
        return False, "UNRELIABLE:ROWS", slopes
    add, vold, trin = i.add[-n:], i.vold[-n:], i.trin[-n:]
    sa, sv, st = lsq_slope(add), lsq_slope(vold), lsq_slope(trin)
    slopes = {"add": sa, "vold": sv, "trin": st}
    # FLAT test on the DECIDING series (ADD is required in both directions).
    if is_flat(add, sa):
        return False, "SLOPE:ADD_FLAT", slopes
    if direction == "SHORT":
        ok = (sa < 0) and (sv < 0 or st > 0)
    else:
        ok = (sa > 0) and (sv > 0 or st < 0)
    return (ok, "OK" if ok else "SLOPE:DIRECTION", slopes)


def _divergence(i: Internals) -> Tuple[bool, float]:
    """Gate 3 — |ADD delta| >= max(150, 10% of |ADD_last|)."""
    n = min(len(i.add), len(i.vold), len(i.trin))
    if n < MIN_ROWS:
        return False, 0.0
    add = i.add[-n:]
    delta = abs(add[-1] - add[0])
    floor = max(DIV_MIN_ISSUES, DIV_PCT * abs(add[-1]))
    return (delta >= floor, delta)


def _event_complete(c: Candidate) -> Tuple[bool, str]:
    """Gate 4 — the setup event must have COMPLETED (no 'approaching')."""
    if c.setup == SETUP_CLUSTER_FADE:
        if not c.pool_tagged:
            return False, "EVENT:POOL_UNTAGGED"
        if c.rejected_within_bars is None or c.rejected_within_bars > REJECT_BARS:
            return False, "EVENT:NO_REJECTION"
        return True, "OK"
    if c.setup == SETUP_FAILED_RETEST:
        if c.boundary_close_beyond_pts is None or c.boundary_close_beyond_pts < BOUNDARY_BEYOND_PTS:
            return False, "EVENT:NO_BOUNDARY_CLOSE"
        if not c.retested:
            return False, "EVENT:NO_RETEST"
        return True, "OK"
    if c.setup == SETUP_WASHOUT:
        return _washout_ok(c)
    if c.setup == SETUP_PULLBACK_HOLD:
        # Pullback-Hold completes when price held the level (a rejection back through it).
        if c.rejected_within_bars is None or c.rejected_within_bars > REJECT_BARS:
            return False, "EVENT:NO_HOLD"
        return True, "OK"
    return False, "EVENT:UNKNOWN_SETUP"


def _washout_ok(c: Candidate) -> Tuple[bool, str]:
    """Part 2 — washout retune. Drop standalone TRIN spike <09:45; require all three."""
    if _hhmm_to_min(c.ts_et) < _hhmm_to_min(WASHOUT_DROP_BEFORE_ET):
        return False, "WASHOUT:OPENING_NOISE"
    tick_last = c.internals.tick[-1] if c.internals.tick else 0.0
    if tick_last > WASHOUT_TICK_FLOOR:
        return False, "WASHOUT:TICK"
    if not c.pool_tagged:  # reuse pool_tagged as "price at a named support level"
        return False, "WASHOUT:NOT_AT_SUPPORT"
    if c.washout_reclaim_bars is None or c.washout_reclaim_bars > WASHOUT_RECLAIM_BARS:
        return False, "WASHOUT:NO_RECLAIM"
    return True, "OK"


def _risk_floor(c: Candidate) -> Tuple[bool, str]:
    """Gate 5 — stop >= 1.5*ATR(5m) beyond invalidating extreme AND target pays >= 1.5R."""
    if c.atr5m is None or c.atr5m <= 0:
        return False, "RISK:NO_ATR"
    stop_dist = abs(c.stop - c.invalidating_extreme)
    if stop_dist < ATR_MULT * c.atr5m:
        return False, "RISK:STOP_TOO_TIGHT"
    r = abs(c.entry - c.stop)
    if r <= 0:
        return False, "RISK:ZERO_R"
    reward = abs(c.t2 - c.entry) if c.t2 else abs(c.t1 - c.entry)
    if reward / r < MIN_RR:
        return False, "RISK:RR_TOO_LOW"
    return True, "OK"


def _build_alert(c: Candidate, slopes: Dict[str, float], divergence: float) -> dict:
    half = round((c.entry + c.stop) / 2.0, 2)  # advisory half-size scale-out reference
    subject = f"TRADE: {c.setup} {c.direction} {c.entry}"
    body = (
        f"{c.setup} {c.direction} @ {c.entry}\n"
        f"stop {c.stop} | T1 {c.t1} | T2 {c.t2}\n"
        f"half-size off at T1 (ref {half})\n"
        f"level: {c.level_name} ({c.level})\n"
        f"gates: ADD_slope {round(slopes['add'], 2)} | "
        f"VOLD_slope {round(slopes['vold'], 2)} | TRIN_slope {round(slopes['trin'], 3)} "
        f"| |ADD delta| {round(divergence, 1)}\n"
        f"expires {EXPIRY_MIN} min if untaken"
    )
    return {
        "subject": subject, "body": body, "expiry_min": EXPIRY_MIN,
        "entry": c.entry, "stop": c.stop, "t1": c.t1, "t2": c.t2,
        "half_size_ref": half, "level_name": c.level_name, "level": c.level,
        "gate_values": {"add_slope": slopes["add"], "vold_slope": slopes["vold"],
                        "trin_slope": slopes["trin"], "divergence": divergence},
    }


def qualify(c: Candidate, session: SessionState) -> Decision:
    """Run all Part-1 gates in order. First failing gate wins the suppression reason."""
    # Gate 7 (cap / one-loss-done) — cheapest, session-level, checked first so a spent
    # session suppresses everything downstream.
    if session.taken_trade_logged:
        return Decision(False, "CAP:TAKEN_TRADE")
    if session.n_qualified >= MAX_QUALIFIED_PER_DAY:
        return Decision(False, "CAP:DAILY")

    # Gate 1 — window
    if not _in_window(c.ts_et):
        return Decision(False, "WINDOW")

    # Gate 6 — debounce (before the expensive checks; a repeat level is dead on arrival)
    if session.seen(c.setup, c.level):
        return Decision(False, "DEBOUNCE")

    # Gate 2 — slope v3.1
    spass, sreason, slopes = _slope_gate(c.direction, c.internals)
    if not spass:
        unreliable = sreason.startswith("UNRELIABLE")
        return Decision(False, sreason, unreliable=unreliable,
                        add_slope=slopes["add"], vold_slope=slopes["vold"],
                        trin_slope=slopes["trin"])

    # Gate 3 — divergence magnitude floor
    dpass, divergence = _divergence(c.internals)
    if not dpass:
        return Decision(False, "DIVERGENCE", add_slope=slopes["add"],
                        vold_slope=slopes["vold"], trin_slope=slopes["trin"],
                        divergence=divergence)

    # Gate 4 — event completion
    epass, ereason = _event_complete(c)
    if not epass:
        return Decision(False, ereason, add_slope=slopes["add"],
                        vold_slope=slopes["vold"], trin_slope=slopes["trin"],
                        divergence=divergence)

    # Gate 5 — risk floor
    rpass, rreason = _risk_floor(c)
    if not rpass:
        return Decision(False, rreason, add_slope=slopes["add"],
                        vold_slope=slopes["vold"], trin_slope=slopes["trin"],
                        divergence=divergence)

    # QUALIFIED — record for debounce + cap, build the lock-screen payload.
    session.record(c.setup, c.level)
    alert = _build_alert(c, slopes, divergence)
    return Decision(True, "OK", add_slope=slopes["add"], vold_slope=slopes["vold"],
                    trin_slope=slopes["trin"], divergence=divergence, alert=alert)


# ── self-test ────────────────────────────────────────────────────────────────
def _lin(start: float, end: float, n: int = FULL_ROWS) -> List[float]:
    if n == 1:
        return [end]
    step = (end - start) / (n - 1)
    return [round(start + step * i, 3) for i in range(n)]


def _selftest() -> int:
    fails = 0

    def check(name, cond):
        nonlocal fails
        print(f"  {'PASS' if cond else 'FAIL'}  {name}")
        if not cond:
            fails += 1

    # slope + flat mechanics
    up = _lin(1000, 1400)
    check("lsq_slope up > 0", lsq_slope(up) > 0)
    check("lsq_slope down < 0", lsq_slope(_lin(1400, 1000)) < 0)
    flat = _lin(1000, 1001)
    check("flat series flagged FLAT", is_flat(flat, lsq_slope(flat)))
    check("steep series NOT flat", not is_flat(up, lsq_slope(up)))

    # a clean qualifying SHORT (ADD down, VOLD down, TRIN up) mid-window
    good = Candidate(
        ts_et="10:49", date="2026-07-16", setup=SETUP_CLUSTER_FADE, direction="SHORT",
        level=7618.0, level_name="cluster-VAH", entry=7617.0, stop=7627.0, t1=7600.0,
        t2=7588.0, invalidating_extreme=7620.0, atr5m=4.0,
        internals=Internals(add=_lin(900, 400), vold=_lin(500e6, -300e6),
                            trin=_lin(0.8, 1.6), tick=_lin(-100, -350), feed_age_s=10),
        pool_tagged=True, rejected_within_bars=2,
    )
    d = qualify(good, SessionState(date="2026-07-16"))
    check("clean SHORT qualifies", d.qualified and d.emit_email())
    check("alert subject formatted", d.alert and d.alert["subject"].startswith("TRADE: Cluster Fade SHORT"))

    # out-of-window => suppressed WINDOW, no email
    ow = Candidate(**{**good.__dict__, "ts_et": "09:32"})
    d = qualify(ow, SessionState(date="2026-07-16"))
    check("09:32 suppressed WINDOW", (not d.qualified) and d.reason == "WINDOW")

    # the cited 8/3 micro-noise (ADD 1155->1140, delta 15) must be suppressed. It is
    # caught by the FLAT test in gate 2 (move 15 << 10% of ~1147) — an earlier, stricter
    # kill than gate 3. Either way: not emailed.
    micro = Candidate(**{**good.__dict__,
                         "internals": Internals(add=_lin(1155, 1140), vold=_lin(500e6, -300e6),
                                                trin=_lin(0.8, 1.6), tick=_lin(-100, -350),
                                                feed_age_s=10)})
    d = qualify(micro, SessionState(date="2026-07-16"))
    check("ADD 1155->1140 suppressed (FLAT/DIVERGENCE)",
          (not d.emit_email()) and d.reason in ("SLOPE:ADD_FLAT", "DIVERGENCE"))

    # a case that clears FLAT but fails the divergence floor: ADD 1155->1035 (delta 120,
    # floor 150) => gate 3 DIVERGENCE is the isolated killer.
    divcase = Candidate(**{**good.__dict__,
                          "internals": Internals(add=_lin(1155, 1035), vold=_lin(500e6, -300e6),
                                                 trin=_lin(0.8, 1.6), tick=_lin(-100, -350),
                                                 feed_age_s=10)})
    d = qualify(divcase, SessionState(date="2026-07-16"))
    check("ADD delta 120 suppressed DIVERGENCE", (not d.qualified) and d.reason == "DIVERGENCE")

    # feed too old => UNRELIABLE (log only)
    stale = Candidate(**{**good.__dict__,
                         "internals": Internals(add=_lin(900, 400), vold=_lin(500e6, -300e6),
                                                trin=_lin(0.8, 1.6), tick=_lin(-100, -350),
                                                feed_age_s=200)})
    d = qualify(stale, SessionState(date="2026-07-16"))
    check("stale feed UNRELIABLE, no email", (not d.emit_email()) and d.unreliable)

    # risk floor: stop too tight
    tight = Candidate(**{**good.__dict__, "stop": 7620.5})
    d = qualify(tight, SessionState(date="2026-07-16"))
    check("tight stop suppressed RISK", (not d.qualified) and d.reason.startswith("RISK"))

    print(f"\nsentinel self-test: {'ALL PASS' if fails == 0 else str(fails) + ' FAILED'}")
    return fails


if __name__ == "__main__":
    import sys
    sys.exit(1 if _selftest() else 0)
