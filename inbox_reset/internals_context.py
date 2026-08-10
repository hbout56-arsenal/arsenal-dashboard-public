#!/usr/bin/env python3
"""
inbox_reset/internals_context.py — wire two CONTEXT fields natively into
internals_snapshot.json so the 10:00 READ and the shadow alerts read them
directly instead of Claude recomputing them off Yahoo in a sandbox.

  megacap_pct = mean daily %chg of NVDA, AAPL, MSFT, AMZN, GOOGL
  rsp_spy     = RSP/SPY close ratio + 20d LSQ slope + rolling z-score

Both are CONTEXT only. megacap is NOT a gate — a 500-day study found the +2%
"no shorts" half holds (SPX +0.35% next day, 71% win) but the -2% "no longs"
half is BACKWARDS (-2% days were the best forward bucket: +0.46%, 65% win).
So we LOG megacap at entry on every trade row and revisit at n>=20; we never
suppress a long on it.

Honesty: this public/dashboard repo carries a Polygon price snapshot
(prices_stocks.json) with SPY but not RSP and not the five megacaps, and no
20-day RSP/SPY ratio history. The builder computes every field it can from
whatever source is present and marks the rest SOURCE_MISSING (awaiting the Mac
collector / Yahoo fetch) rather than inventing numbers. The math is proven by
the self-test on in-memory inputs.

Run:
  python3 inbox_reset/internals_context.py --selftest
  python3 inbox_reset/internals_context.py --build   # inject CONTEXT into internals_snapshot.json
"""
from __future__ import annotations
from typing import Dict, List, Optional
import argparse
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SNAPSHOT = os.path.join(ROOT, "internals_snapshot.json")
PRICES = os.path.join(ROOT, "prices_stocks.json")
RATIO_HIST = os.path.join(ROOT, "rsp_spy_history.json")  # optional: {"ratios":[...oldest-first...]}

MEGACAPS = ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL"]


def lsq_slope(ys: List[float]) -> float:
    """Least-squares slope over x = 0..n-1. 0.0 if <2 points."""
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


def zscore(x: float, series: List[float]) -> Optional[float]:
    """z of x vs the series (population sd). None if <2 points or zero variance."""
    n = len(series)
    if n < 2:
        return None
    mean = sum(series) / n
    var = sum((s - mean) ** 2 for s in series) / n
    if var <= 0:
        return None
    return (x - mean) / (var ** 0.5)


def load_prices(path: str = PRICES) -> Dict[str, dict]:
    try:
        with open(path) as fh:
            return json.load(fh).get("symbols", {})
    except Exception:
        return {}


def compute_megacap_pct(prices: Dict[str, dict]) -> dict:
    """mean daily %chg over the five megacaps. PARTIAL if some are missing."""
    got, missing = {}, []
    for sym in MEGACAPS:
        row = prices.get(sym)
        if row and isinstance(row.get("change_pct"), (int, float)):
            got[sym] = float(row["change_pct"])
        else:
            missing.append(sym)
    if not got:
        return {"value": None, "n": 0, "constituents": {}, "missing": MEGACAPS,
                "status": "SOURCE_MISSING", "is_gate": False,
                "note": "awaiting Mac collector / Yahoo megacap quotes"}
    value = round(sum(got.values()) / len(got), 4)
    return {"value": value, "n": len(got), "constituents": got, "missing": missing,
            "status": "OK" if not missing else "PARTIAL", "is_gate": False,
            "asymmetry_note": "+2% half holds (no shorts); -2% half is BACKWARDS (best forward bucket). LOG only; revisit n>=20."}


def compute_rsp_spy(prices: Dict[str, dict], ratio_hist: List[float]) -> dict:
    """RSP/SPY ratio + 20d LSQ slope + rolling z-score."""
    spy = prices.get("SPY", {})
    rsp = prices.get("RSP", {})
    spy_px = spy.get("price")
    rsp_px = rsp.get("price")
    if not (isinstance(spy_px, (int, float)) and isinstance(rsp_px, (int, float)) and spy_px):
        return {"ratio": None, "slope20d": None, "z": None, "status": "SOURCE_MISSING",
                "have": {"SPY": bool(spy_px), "RSP": bool(rsp_px)},
                "note": "need both RSP and SPY closes (RSP absent in this repo snapshot)"}
    ratio = round(rsp_px / spy_px, 5)
    hist = list(ratio_hist or [])[-20:]
    slope = round(lsq_slope(hist + [ratio]), 8) if len(hist) >= 1 else None
    z = zscore(ratio, hist) if len(hist) >= 2 else None
    return {"ratio": ratio, "slope20d": slope,
            "z": round(z, 3) if z is not None else None,
            "n_hist": len(hist),
            "status": "OK" if len(hist) >= 2 else "PARTIAL_NO_HISTORY",
            "note": "breadth proxy: RSP/SPY rising = equal-weight leading (broad); falling = megacap-led (narrow)"}


def build_context(prices: Dict[str, dict], ratio_hist: List[float]) -> dict:
    return {
        "_schema": "internals_context/1",
        "megacap_pct": compute_megacap_pct(prices),
        "rsp_spy": compute_rsp_spy(prices, ratio_hist),
    }


def inject(snapshot_path: str = SNAPSHOT, prices_path: str = PRICES,
           ratio_hist_path: str = RATIO_HIST) -> dict:
    with open(snapshot_path) as fh:
        snap = json.load(fh)
    prices = load_prices(prices_path)
    hist = []
    if os.path.exists(ratio_hist_path):
        try:
            hist = json.load(open(ratio_hist_path)).get("ratios", [])
        except Exception:
            hist = []
    ctx = build_context(prices, hist)
    snap["context"] = ctx
    with open(snapshot_path, "w") as fh:
        json.dump(snap, fh, indent=1)
        fh.write("\n")
    return ctx


# ── self-test (math proven on in-memory inputs) ───────────────────────────────
def _selftest() -> int:
    fails = 0

    def check(name, cond):
        nonlocal fails
        print(f"  {'PASS' if cond else 'FAIL'}  {name}")
        if not cond:
            fails += 1

    prices = {
        "NVDA": {"change_pct": 2.0, "price": 100},
        "AAPL": {"change_pct": 1.0, "price": 200},
        "MSFT": {"change_pct": -1.0, "price": 400},
        "AMZN": {"change_pct": 0.0, "price": 180},
        "GOOGL": {"change_pct": 3.0, "price": 190},
        "SPY": {"price": 772.4575}, "RSP": {"price": 187.79},
    }
    mc = compute_megacap_pct(prices)
    check("megacap mean == 1.0", mc["value"] == 1.0 and mc["n"] == 5 and mc["status"] == "OK")
    check("megacap is NOT a gate", mc["is_gate"] is False)

    mc_partial = compute_megacap_pct({k: v for k, v in prices.items() if k != "NVDA"})
    check("megacap PARTIAL drops missing", mc_partial["status"] == "PARTIAL"
          and mc_partial["missing"] == ["NVDA"] and mc_partial["n"] == 4)

    mc_none = compute_megacap_pct({"SPY": {"price": 1}})
    check("megacap SOURCE_MISSING when none present",
          mc_none["value"] is None and mc_none["status"] == "SOURCE_MISSING")

    hist = [0.2420, 0.2422, 0.2425, 0.2428, 0.2430]
    rs = compute_rsp_spy(prices, hist)
    check("rsp_spy ratio computed", abs(rs["ratio"] - round(187.79 / 772.4575, 5)) < 1e-9)
    check("rsp_spy slope present with history", rs["slope20d"] is not None and rs["z"] is not None)

    rs_missing = compute_rsp_spy({"SPY": {"price": 772}}, hist)
    check("rsp_spy SOURCE_MISSING without RSP", rs_missing["status"] == "SOURCE_MISSING")

    check("lsq_slope rising positive", lsq_slope([1, 2, 3, 4]) > 0)
    check("zscore of mean is 0", abs(zscore(2.0, [1.0, 2.0, 3.0])) < 1e-9)

    print(f"\ninternals_context self-test: {'ALL PASS' if fails == 0 else str(fails) + ' FAILED'}")
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--build", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(1 if _selftest() else 0)
    if a.build:
        ctx = inject()
        print(json.dumps(ctx, indent=2))
        raise SystemExit(0)
    ap.print_help()
    raise SystemExit(2)


if __name__ == "__main__":
    main()
