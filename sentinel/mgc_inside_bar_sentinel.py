#!/usr/bin/env python3
"""
sentinel/mgc_inside_bar_sentinel.py — MGC inside-bar DETECTION-ONLY leg (SHADOW)

Adds an MGC (micro gold) inside-bar leg to the sentinel family. Its ONLY job is to
raise "SETUP ARMED: MGC INSIDE BAR @ <price>" when the last COMPLETED daily GC bar
is an inside bar, and to log that armed alert to the forward ledger. It does NOT:
  - emit any order / execution text (no BUY/SELL/FILL/ORDER),
  - place, size, or route anything,
  - log the alert as a TAKEN trade.
It is DESCRIPTIVE and NON-VOTING. The trigger the strategy would ultimately use is
PRICE breaking the inside bar; this module only ARMS the watch.

STATUS: DISABLED. `ENABLED = False` below is the module's own guard (same discipline
as the D111b leg). The launchd plist ships `Disabled=true`. Nothing fires until the
operator flips both, on the Mac, after confirming the frozen rule.

PROVENANCE / DEFERRED FREEZE (read this before trusting the geometry):
  The verbatim GC_RAW rule lives in `inside_bar_engine.py` on the Mac and is NOT in
  this public mirror. Per operator decision, the Part-1 pre-registration is authored
  on the Mac (see mgc_inside_bar_prereg.TEMPLATE.md). The inside-bar definition,
  break trigger, and structural stop coded here match the dashboard's stated setup
  (index.html: "stop-entry on the break of the inside bar's high (long) / low (short)
  ... stop the opposite side"). The TARGET rule is a PROVISIONAL 1R placeholder
  (PROVISIONAL_TARGET_R) pending the verbatim freeze. Reconcile all four against
  inside_bar_engine.py on the Mac before the freeze is locked.

Timeframe: DAILY GC bars (operator-confirmed). Instrument reported/ledgered: MGC.
Anti-look-ahead: every read uses bars[0..signal_index] only.

Self-tested (`python3 mgc_inside_bar_sentinel.py --selftest`) against a fixture of
REAL daily GC rows pulled verbatim from gc_bars_daily.json — production-shaped
(epoch-ms t, o/h/l/c/v), tz-aware datetimes — NOT synthesized. Not loaded by any
live path.
"""
from __future__ import annotations
from typing import List, Dict, Optional
import json, math, os, datetime as dt

# ------------------------------------------------------------------ config / guard
ENABLED = False                 # OWN GUARD — DISABLED until operator confirm (Mac)
DETECTOR_ID = "mgc_inside_bar_sentinel_v0_daily"
INSTRUMENT = "MGC"              # micro gold; 1 unit, stop-defined risk
TIMEFRAME = "daily"            # operator-confirmed
DEBOUNCE_SECS = 600             # 10-minute debounce
MGC_TICK = 0.1                  # MGC tick = 0.1 pt ($1). Slippage handled in scorer.
PROVISIONAL_TARGET_R = 1.0      # PLACEHOLDER 1R target — pending verbatim freeze (Mac)
N_LAST_BARS_IN_ALERT = 4        # "the last few bars"
LEDGER_PATH = os.environ.get(   # ~/arsenal/ledgers/... on the Mac; local default here
    "MGC_IB_LEDGER",
    os.path.join(os.path.dirname(__file__), "mgc_inside_bar_forward.csv"),
)

# Ledger row shape — triple-barrier-compatible so the scorer can share the D110 shape.
# (Reconcile column names against the D110 labeler on the Mac before first real fill.)
LEDGER_FIELDS = [
    "timestamp", "detector_id", "instrument", "timeframe", "armed_bar_ts",
    "price", "direction", "entry_trigger", "long_trigger", "short_trigger",
    "stop", "target", "regime_ema50_side", "regime_vol_bucket", "ann_vol_20d",
    "outcome", "exit_price", "net_points", "R", "note",
]


# ------------------------------------------------------------------ small helpers
def _dt_utc(ms: int) -> dt.datetime:
    """Epoch-ms -> tz-AWARE UTC datetime. (tz-bug lesson: never a naive datetime.)"""
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc)


def is_inside_bar(mother: Dict, bar: Dict) -> bool:
    """`bar` is inside `mother`: high<=mother.high AND low>=mother.low, excluding the
    degenerate case where both extremes are equal (identical range = not a coil)."""
    return (bar["h"] <= mother["h"] and bar["l"] >= mother["l"]
            and not (bar["h"] == mother["h"] and bar["l"] == mother["l"]))


def _ema(vals: List[float], n: int) -> Optional[float]:
    if len(vals) < 1:
        return None
    k = 2 / (n + 1)
    e = vals[0]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
    return e


def regime_tag(bars: List[Dict], idx: int) -> Dict:
    """GC trend/vol state at the signal bar, anti-look-ahead (bars[0..idx] only):
    side of daily EMA50 + a 20d realized-vol bucket. Lets a post-hoc read separate
    'edge' from 'gold went up.'"""
    closes = [b["c"] for b in bars[: idx + 1]]
    e50 = _ema(closes, 50)
    side = None
    if e50 is not None:
        side = "above" if closes[-1] > e50 else "below"
    ann_vol = None
    if len(closes) >= 21:
        rets = [math.log(closes[t] / closes[t - 1]) for t in range(len(closes) - 20, len(closes))]
        ann_vol = math.sqrt(sum(r * r for r in rets) / len(rets)) * math.sqrt(252)
    bucket = None
    if ann_vol is not None:
        bucket = "low" if ann_vol < 0.15 else ("high" if ann_vol >= 0.30 else "mid")
    return {"ema50_side": side, "ann_vol_20d": (round(ann_vol, 4) if ann_vol is not None else None),
            "vol_bucket": bucket}


# ------------------------------------------------------------------ the detector
def detect(bars: List[Dict]) -> Optional[Dict]:
    """Pure geometry: is the LAST COMPLETED bar an inside bar? Returns a setup
    descriptor (no order text, no side chosen) or None. bars = chronological
    daily rows with keys t(ms),o,h,l,c,v; the last element is the completed bar."""
    if len(bars) < 2:
        return None
    idx = len(bars) - 1
    mother, bar = bars[idx - 1], bars[idx]
    if not is_inside_bar(mother, bar):
        return None
    long_trigger = bar["h"]                 # stop-entry on break of inside high (long)
    short_trigger = bar["l"]                # stop-entry on break of inside low  (short)
    ib_range = bar["h"] - bar["l"]
    return {
        "armed_bar_ts": _dt_utc(bar["t"]).isoformat(),
        "price": bar["c"],                  # reference price = inside-bar close
        "long_trigger": long_trigger,
        "short_trigger": short_trigger,
        "stop_long": short_trigger,         # structure: opposite side of the inside bar
        "stop_short": long_trigger,
        "target_long": round(long_trigger + PROVISIONAL_TARGET_R * ib_range, 4),   # PROVISIONAL
        "target_short": round(short_trigger - PROVISIONAL_TARGET_R * ib_range, 4), # PROVISIONAL
        "target_basis": f"PROVISIONAL {PROVISIONAL_TARGET_R:g}R (inside-bar range) — pending freeze",
        "regime": regime_tag(bars, idx),
        "last_bars": [{k: b[k] for k in ("t", "o", "h", "l", "c", "v")}
                      for b in bars[-N_LAST_BARS_IN_ALERT:]],
    }


def arm(bars: List[Dict], now_epoch: float, state: Optional[Dict] = None,
        enabled: Optional[bool] = None) -> Optional[Dict]:
    """Guarded, debounced entry point. Returns an ARMED-ALERT dict or None.
      - own guard: `enabled` (defaults to module ENABLED) must be True;
      - 10-min debounce vs state['last_fire_ts'] (explicit `now_epoch`, testable);
      - detection-only: message is an armed WATCH, never an order.
    `state` is mutated in place with the new last_fire_ts on a real fire."""
    if enabled is None:
        enabled = ENABLED
    if not enabled:
        return None
    setup = detect(bars)
    if setup is None:
        return None
    state = state if state is not None else {}
    last = state.get("last_fire_ts")
    if last is not None and (now_epoch - last) < DEBOUNCE_SECS:
        return None
    state["last_fire_ts"] = now_epoch
    alert = {
        "headline": f"SETUP ARMED: MGC INSIDE BAR @ {setup['price']:g}",
        "detector_id": DETECTOR_ID,
        "instrument": INSTRUMENT,
        "timeframe": TIMEFRAME,
        "kind": "detection_only",           # explicitly not an order
        "direction": "pending",             # resolved by which side breaks (nightly)
        **setup,
    }
    return alert


def to_ledger_row(alert: Dict, now_iso: str) -> Dict:
    """Map an armed alert to a forward-ledger row (outcome unset — stamped nightly by
    the triple-barrier labeler). Records the setup as ARMED, NOT as a taken trade."""
    reg = alert.get("regime", {})
    return {
        "timestamp": now_iso, "detector_id": alert["detector_id"],
        "instrument": alert["instrument"], "timeframe": alert["timeframe"],
        "armed_bar_ts": alert["armed_bar_ts"], "price": alert["price"],
        "direction": "pending", "entry_trigger": "break of inside-bar high(long)/low(short)",
        "long_trigger": alert["long_trigger"], "short_trigger": alert["short_trigger"],
        "stop": "", "target": "", "regime_ema50_side": reg.get("ema50_side"),
        "regime_vol_bucket": reg.get("vol_bucket"), "ann_vol_20d": reg.get("ann_vol_20d"),
        "outcome": "", "exit_price": "", "net_points": "", "R": "",
        "note": "ARMED (detection-only, NON-VOTING); direction/stop/target/outcome "
                "stamped nightly by triple-barrier labeler; target rule PROVISIONAL.",
    }


def append_armed_row(alert: Dict, now_iso: str, path: str = LEDGER_PATH) -> Dict:
    """Append one ARMED row to the forward CSV (header written if absent). Explicit,
    separate from any 'taken trade' path — this NEVER records a fill."""
    import csv
    row = to_ledger_row(alert, now_iso)
    exists = os.path.exists(path) and os.path.getsize(path) > 0
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=LEDGER_FIELDS)
        if not exists:
            w.writeheader()
        w.writerow(row)
    return row


# ------------------------------------------------------------------ selftest
def _load_fixture() -> Dict:
    p = os.path.join(os.path.dirname(__file__), "fixtures", "gc_daily_inside_bar_fixture.json")
    return json.load(open(p))


def _selftest() -> None:
    fx = _load_fixture()
    rows = fx["rows"]
    assert fx["timeframe"] == "daily" and fx["symbol"] == "GC"

    # (1) production-shaped rows -> tz-AWARE datetimes (the tz-bug lesson)
    d0 = _dt_utc(rows[0]["t"])
    assert d0.tzinfo is not None and d0.utcoffset() == dt.timedelta(0), "datetime must be tz-aware UTC"
    for r in rows:  # real production row schema
        assert set(("t", "o", "h", "l", "c", "v")).issubset(r), "row not production-shaped"

    # (2) POSITIVE: window ending on the real 2026-07-09 inside bar -> arms
    pos = rows[:-1]
    st = {}
    a = arm(pos, now_epoch=1_000_000.0, state=st, enabled=True)
    assert a is not None, "expected an armed alert on the real inside bar"
    assert a["headline"] == "SETUP ARMED: MGC INSIDE BAR @ 4090.6", a["headline"]
    assert a["long_trigger"] == 4125.8 and a["short_trigger"] == 4090.6
    assert a["stop_long"] == 4090.6 and a["stop_short"] == 4125.8      # structure = opposite side
    assert a["direction"] == "pending" and a["kind"] == "detection_only"
    assert a["regime"]["ema50_side"] == "below", a["regime"]
    assert a["regime"]["vol_bucket"] == "mid", a["regime"]
    assert abs(a["regime"]["ann_vol_20d"] - 0.2335) < 1e-3, a["regime"]  # real 20d vol
    assert len(a["last_bars"]) == N_LAST_BARS_IN_ALERT

    # (3) DETECTION-ONLY: no order/execution text anywhere in the serialized alert
    blob = json.dumps(a).upper()
    for banned in ("BUY", "SELL", "ORDER", "FILL", "EXECUTE", "LONG NOW", "SHORT NOW"):
        assert banned not in blob, f"order-ish text leaked: {banned}"

    # (4) NEGATIVE: full window ends on a NON-inside bar (2026-07-13) -> no arm
    assert arm(rows, now_epoch=2_000_000.0, state={}, enabled=True) is None

    # (5) GUARD: disabled -> never fires even on the inside bar
    assert arm(pos, now_epoch=3_000_000.0, state={}, enabled=False) is None

    # (6) DEBOUNCE: second call inside 600s is suppressed; after 600s it re-arms
    st2 = {}
    assert arm(pos, now_epoch=5_000.0, state=st2, enabled=True) is not None
    assert arm(pos, now_epoch=5_000.0 + 300, state=st2, enabled=True) is None      # within 10 min
    assert arm(pos, now_epoch=5_000.0 + 601, state=st2, enabled=True) is not None  # after 10 min

    # (7) ANTI-LOOK-AHEAD: regime tag at the inside bar is identical with/without a future bar
    idx = len(pos) - 1
    assert regime_tag(pos, idx) == regime_tag(rows, idx), "regime tag leaked future data"

    # (8) LEDGER: armed row maps to the triple-barrier-compatible shape, outcome unset
    row = to_ledger_row(a, "2026-07-09T20:00:00+00:00")
    assert set(row.keys()) == set(LEDGER_FIELDS)
    assert row["outcome"] == "" and row["direction"] == "pending"

    print("mgc_inside_bar_sentinel selftest: OK (8 checks, real fixture "
          f"{fx['_provenance']['extracted_from']})")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print("MGC inside-bar sentinel — DETECTION ONLY, DISABLED "
              f"(ENABLED={ENABLED}). Run with --selftest.")
