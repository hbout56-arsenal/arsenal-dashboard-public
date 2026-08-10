#!/usr/bin/env python3
"""
inbox_reset/ten_am_read.py — the ONE keeper: "10:00 READ".

Fires 10:02 ET, market days only, ONE email per session. State only, no
recommendation. Lock-screen readable plain text.

  Subject: 10:00 READ — {DAY_TYPE} | L:{PASS|FAIL} S:{PASS|FAIL}

Locked classifier (frozen 4-type rule, VD above DISTRIBUTION):
  breadth = sign(ADD level), volume = sign(VOLD level), price = sign(ES chg)
    all three agree            -> TREND_UP / TREND_DOWN
    breadth vs volume disagree -> VOLUME_DIVERGENT_UP / VOLUME_DIVERGENT_DOWN
    else (residual)            -> DISTRIBUTION
  VD is evaluated BEFORE the DISTRIBUTION residual ("VD above DISTRIBUTION").

Gates (same slope engine the sentinel uses, so the READ and the qualifier agree):
  30-min / 30-row LSQ on ADD/VOLD/TRIN.
    SHORT PASS: ADD_slope<0 AND (VOLD_slope<0 OR TRIN_slope>0)
    LONG  PASS: ADD_slope>0 AND (VOLD_slope>0 OR TRIN_slope<0)
  Slope magnitude must exceed 10% of the series level, else FLAT => that gate FAILs.
  <15 rows OR feed age >120s => slopes UNRELIABLE: say so explicitly, never omit.

Risk: ATR(5m) -> min stop = 1.5 x ATR.
Levels: liquidity pools above / price / pools below. FVGs: unmitigated near price.
Context: megacap_pct + RSP/SPY (from internals_snapshot.json 'context'; NOT gates).
Feed: LIVE|DARK + age.

Run:
  python3 inbox_reset/ten_am_read.py --selftest
  python3 inbox_reset/ten_am_read.py --dry-run          # live-ish: real internals_snapshot.json
  python3 inbox_reset/ten_am_read.py --t1               # T1 fixture (reconstructed from dispatch)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional
import argparse
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SNAPSHOT = os.path.join(ROOT, "internals_snapshot.json")

FLAT_FRAC = 0.10
MIN_ROWS = 15
FULL_ROWS = 30
MAX_FEED_AGE_S = 120
ATR_MULT = 1.5

TREND_UP = "TREND_UP"
TREND_DOWN = "TREND_DOWN"
VD_UP = "VOLUME_DIVERGENT_UP"
VD_DOWN = "VOLUME_DIVERGENT_DOWN"
DISTRIBUTION = "DISTRIBUTION"


def lsq_slope(ys: List[float]) -> float:
    n = len(ys)
    if n < 2:
        return 0.0
    xbar = (n - 1) / 2.0
    ybar = sum(ys) / n
    num = den = 0.0
    for i, y in enumerate(ys):
        dx = i - xbar
        num += dx * (y - ybar)
        den += dx * dx
    return num / den if den else 0.0


def is_flat(ys: List[float], slope: float) -> bool:
    n = len(ys)
    if n < 2:
        return True
    level = abs(sum(ys) / n)
    move = abs(slope * (n - 1))
    return move < FLAT_FRAC * level


def classify_day_type(add_level: float, vold_level: float, es_chg: float) -> str:
    b_up = add_level > 0
    v_up = vold_level > 0
    p_up = es_chg > 0
    if b_up == v_up == p_up:
        return TREND_UP if b_up else TREND_DOWN
    if b_up != v_up:                       # breadth vs volume divergence — VD (above DISTRIBUTION)
        return VD_UP if b_up else VD_DOWN
    return DISTRIBUTION


@dataclass
class ReadInput:
    date: str
    ts_et: str = "10:00"
    rows: List[Dict] = field(default_factory=list)  # 1-min rows oldest-first: {add,vold,trin,tick}
    price: float = 0.0
    es_chg: float = 0.0
    pools_above: List[float] = field(default_factory=list)
    pools_below: List[float] = field(default_factory=list)
    atr5m: float = 0.0
    fvgs: List[Dict] = field(default_factory=list)  # {side,lo,hi}
    context: Dict = field(default_factory=dict)     # {'megacap_pct':{...},'rsp_spy':{...}}
    feed_status: str = "LIVE"
    feed_age_s: float = 0.0


def _series(rows: List[Dict], key: str) -> List[float]:
    out = []
    for r in rows:
        v = r.get(key)
        if isinstance(v, str):
            try:
                v = float(v)
            except ValueError:
                v = None
        if isinstance(v, (int, float)):
            out.append(float(v))
    return out


def _slopes(rows: List[Dict]) -> Dict:
    add = _series(rows, "add")
    vold = _series(rows, "vold")
    trin = _series(rows, "trin")
    n = min(len(add), len(vold), len(trin))
    return {"n": n, "add": add[-n:], "vold": vold[-n:], "trin": trin[-n:],
            "sa": lsq_slope(add[-n:]) if n else 0.0,
            "sv": lsq_slope(vold[-n:]) if n else 0.0,
            "st": lsq_slope(trin[-n:]) if n else 0.0}


def _gate(direction: str, s: Dict, feed_age_s: float) -> Dict:
    """Returns {verdict:PASS|FAIL, unreliable, reason}."""
    if feed_age_s > MAX_FEED_AGE_S:
        return {"verdict": "FAIL", "unreliable": True, "reason": f"UNRELIABLE:FEED_AGE({feed_age_s:.0f}s)"}
    if s["n"] < MIN_ROWS:
        return {"verdict": "FAIL", "unreliable": True, "reason": f"UNRELIABLE:ROWS({s['n']}<15)"}
    if is_flat(s["add"], s["sa"]):
        return {"verdict": "FAIL", "unreliable": False, "reason": "ADD_FLAT"}
    if direction == "SHORT":
        ok = (s["sa"] < 0) and (s["sv"] < 0 or s["st"] > 0)
    else:
        ok = (s["sa"] > 0) and (s["sv"] > 0 or s["st"] < 0)
    return {"verdict": "PASS" if ok else "FAIL", "unreliable": False,
            "reason": "OK" if ok else "SLOPE:DIRECTION"}


def _sign(x: float) -> str:
    return "+" if x >= 0 else "-"


def _fmt_ctx(context: Dict) -> str:
    mc = (context or {}).get("megacap_pct", {})
    rs = (context or {}).get("rsp_spy", {})
    mcv = mc.get("value")
    mc_s = f"{mcv:+.2f}%" if isinstance(mcv, (int, float)) else f"n/a ({mc.get('status','?')})"
    ratio = rs.get("ratio")
    if isinstance(ratio, (int, float)):
        z = rs.get("z")
        rs_s = f"{ratio:.5f}" + (f" (z {z:+.2f})" if isinstance(z, (int, float)) else "")
    else:
        rs_s = f"n/a ({rs.get('status','?')})"
    return f"megacap_pct {mc_s} | RSP/SPY {rs_s}"


def render(inp: ReadInput) -> Dict:
    s = _slopes(inp.rows)
    add_level = s["add"][-1] if s["add"] else 0.0
    vold_level = s["vold"][-1] if s["vold"] else 0.0
    trin_level = s["trin"][-1] if s["trin"] else 0.0
    dark = inp.feed_status.upper() == "DARK"

    day_type = classify_day_type(add_level, vold_level, inp.es_chg) if s["n"] else "UNKNOWN"

    lg = _gate("LONG", s, inp.feed_age_s if not dark else 9e9)
    sg = _gate("SHORT", s, inp.feed_age_s if not dark else 9e9)
    L = lg["verdict"]
    S = sg["verdict"]

    unreliable = dark or lg["unreliable"] or sg["unreliable"]
    min_stop = round(ATR_MULT * inp.atr5m, 2)

    subject = f"10:00 READ — {day_type} | L:{L} S:{S}"

    above = " ".join(f"{p:g}" for p in inp.pools_above) or "—"
    below = " ".join(f"{p:g}" for p in inp.pools_below) or "—"
    if inp.fvgs:
        fvg_s = "; ".join(f"{f.get('side','?')} {f.get('lo')}-{f.get('hi')}" for f in inp.fvgs)
    else:
        fvg_s = "none near price"

    slope_line = (
        f"ADD {add_level:g} slope {_sign(s['sa'])}   "
        f"VOLD {vold_level:g} slope {_sign(s['sv'])}   "
        f"TRIN {trin_level:g} slope {_sign(s['st'])}   (30-min/30-row LSQ)"
    )
    if unreliable:
        why = "feed DARK" if dark else (lg["reason"] if lg["unreliable"] else sg["reason"])
        slope_line += f"\n           ⚠ SLOPES UNRELIABLE — {why}; gates report FAIL (state only)."

    feed_s = ("DARK" if dark else "LIVE") + f" + age {inp.feed_age_s:.0f}s"

    body = "\n".join([
        f"Day type : {day_type}",
        f"Gates    : LONG {L} | SHORT {S}",
        f"           {slope_line}",
        f"           slope magnitude must exceed 10% of series level else FLAT=fail",
        f"Risk     : ATR(5m) {inp.atr5m:.2f} -> min stop {min_stop} (1.5x)",
        f"Levels   : pools above {above} | price {inp.price:g} | pools below {below}",
        f"FVGs     : {fvg_s}",
        f"Context  : {_fmt_ctx(inp.context)}",
        f"Feed     : {feed_s}",
        "",
        "State only — no recommendation. SIMULATED / advisory, not financial advice.",
    ])
    return {"subject": subject, "body": body, "day_type": day_type,
            "long": L, "short": S, "unreliable": unreliable}


# ── inputs from the live snapshot (best-available; honest about fidelity) ──────
def input_from_snapshot(path: str = SNAPSHOT) -> ReadInput:
    with open(path) as fh:
        snap = json.load(fh)
    rows = snap.get("rows", [])
    last = rows[-1] if rows else {}
    def f(v, d=0.0):
        try:
            return float(v)
        except (TypeError, ValueError):
            return d
    feed_status = "DARK" if snap.get("feed_status", "").upper().startswith("DARK") else "LIVE"
    return ReadInput(
        date=(snap.get("latest_row_ts", "") or "")[:10],
        rows=rows, price=f(last.get("es_last")), es_chg=f(last.get("es_chg")),
        pools_above=[], pools_below=[], atr5m=0.0, fvgs=[],
        context=snap.get("context", {}), feed_status=feed_status, feed_age_s=0.0)


# ── T1 fixture: reconstructed from the dispatch ground-truth for 8/10 @10:00 ───
# The raw ADD/VOLD/TRIN 1-min rows for 8/10 live in the Mac collector archive
# (internals_live.csv), NOT in this public mirror. Per the dispatch T1 the archive
# reads VD_DOWN, LONG FAIL / SHORT PASS, ATR ~5.4, pools 7796.25 / 7787-88 / 7771.25.
# This fixture encodes that documented ground-truth (breadth falling, up-volume
# still positive but deteriorating, TRIN firming) so the RENDERER can be validated
# against the archive the same way D114's acceptance fixtures were.
def t1_fixture() -> ReadInput:
    def lin(a, b, n=30):
        return [round(a + (b - a) * i / (n - 1), 2) for i in range(n)]
    add = lin(-90, -574)      # breadth falling, negative  -> ADD_slope < 0
    vold = lin(38000, 11592)  # up-vol still > 0 (VD_DOWN) but falling -> VOLD_slope < 0
    trin = lin(0.58, 0.64)    # firming
    rows = [{"add": add[i], "vold": vold[i], "trin": trin[i], "tick": -48}
            for i in range(30)]
    return ReadInput(
        date="2026-08-10", ts_et="10:00", rows=rows,
        price=7787.75, es_chg=-7.25,
        pools_above=[7796.25], pools_below=[7771.25],
        atr5m=5.4, fvgs=[],
        context={"megacap_pct": {"value": None, "status": "SOURCE_MISSING"},
                 "rsp_spy": {"ratio": None, "status": "SOURCE_MISSING"}},
        feed_status="LIVE", feed_age_s=45)


def _selftest() -> int:
    fails = 0

    def check(name, cond):
        nonlocal fails
        print(f"  {'PASS' if cond else 'FAIL'}  {name}")
        if not cond:
            fails += 1

    check("classify VD_DOWN (breadth-/vol+/price-)", classify_day_type(-574, 11592, -7.25) == VD_DOWN)
    check("classify VD_UP (breadth+/vol-/price+)", classify_day_type(300, -5000, 4.0) == VD_UP)
    check("classify TREND_UP", classify_day_type(500, 6000, 8.0) == TREND_UP)
    check("classify TREND_DOWN", classify_day_type(-500, -6000, -8.0) == TREND_DOWN)
    check("classify DISTRIBUTION residual", classify_day_type(300, 5000, -1.0) == DISTRIBUTION)

    r = render(t1_fixture())
    check("T1 day_type VD_DOWN", r["day_type"] == VD_DOWN)
    check("T1 LONG FAIL", r["long"] == "FAIL")
    check("T1 SHORT PASS", r["short"] == "PASS")
    check("T1 subject exact", r["subject"] == "10:00 READ — VOLUME_DIVERGENT_DOWN | L:FAIL S:PASS")
    check("T1 ATR 5.40 -> min stop 8.1", "ATR(5m) 5.40 -> min stop 8.1" in r["body"])
    check("T1 pool above 7796.25", "7796.25" in r["body"])
    check("T1 pool below 7771.25", "7771.25" in r["body"])
    check("T1 price 7787-88 band", "7787.75" in r["body"])
    check("T1 not flagged unreliable (30 rows, age 45s)", r["unreliable"] is False)

    # UNRELIABLE path: 1-row snapshot must SAY SO, never omit silently.
    thin = ReadInput(date="2026-08-10", rows=[{"add": -574, "vold": 11592, "trin": 0.64}],
                     price=7772.5, es_chg=-7.25, atr5m=5.4, feed_status="LIVE", feed_age_s=30)
    rt = render(thin)
    check("thin-feed day_type still VD_DOWN", rt["day_type"] == VD_DOWN)
    check("thin-feed flags UNRELIABLE explicitly", "UNRELIABLE" in rt["body"] and rt["unreliable"])

    # DARK feed must say DARK.
    dk = ReadInput(date="2026-08-10", rows=[{"add": -1, "vold": 1, "trin": 1}],
                   price=1, es_chg=-1, feed_status="DARK")
    rd = render(dk)
    check("DARK feed flagged", "DARK" in rd["body"] and rd["unreliable"])

    print(f"\nten_am_read self-test: {'ALL PASS' if fails == 0 else str(fails) + ' FAILED'}")
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--t1", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(1 if _selftest() else 0)
    if a.t1:
        r = render(t1_fixture())
        print("Subject: " + r["subject"] + "\n\n" + r["body"])
        raise SystemExit(0)
    if a.dry_run:
        r = render(input_from_snapshot())
        print("Subject: " + r["subject"] + "\n\n" + r["body"])
        raise SystemExit(0)
    ap.print_help()
    raise SystemExit(2)


if __name__ == "__main__":
    main()
