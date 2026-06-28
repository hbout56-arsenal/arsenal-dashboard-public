#!/usr/bin/env python3
"""
enhanced_filters.py  —  Dispatch 50, pro-grade screener filters (REFERENCE / NOT LOADED)

Pre-registered ENHANCED filter stack for the swing screener. This module is the
*specification + reference implementation* of the filters frozen in
preregistration.json. It is intentionally NOT wired into the live engine: it is
built so the engine team can apply identical, anti-look-ahead logic when TAGGING
forward picks RAW-pass vs ENHANCED-pass going forward (see raw_vs_enhanced.md).

Design rules (hard):
  * ANTI-LOOK-AHEAD. Every filter evaluated at bar index i may read bars[0..i]
    ONLY. No future bar is ever referenced. The self-test below *proves* this by
    re-evaluating each filter on a truncated series and asserting the verdict at
    index i is byte-identical with and without the future bars present.
  * PURE FUNCTIONS of (bars, i, params). No I/O, no global state, no network.
  * Dependency-free (no numpy/pandas) so it runs anywhere the engine runs.
  * Thresholds come from preregistration.json — DO NOT tune them here. Any change
    is a NEW pre-registration and counts against the divide-by-N haircut.

A "bar" is a dict: {"o","h","l","c","v"} (open/high/low/close/volume), oldest first.
A pick references a signal bar index `i` (the breakout/entry bar) and a pivot.

SIMULATED / advisory. Filters gate or rank; they are not a recommendation.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Optional


# ---- pre-registered thresholds (mirror of preregistration.json; frozen) -------
PARAMS = {
    "trend_template": {
        "ma_short": 50, "ma_mid": 150, "ma_long": 200,
        "long_rising_lookback": 21,        # ~1 month of trading days
        "rs_min_pct_off_52w_low": 30.0,    # Minervini: >=30% above 52w low
        "rs_max_pct_off_52w_high": 25.0,   # within 25% of 52w high
    },
    "vcp": {
        "min_contractions": 2,             # >=2 successive pullbacks
        "tightness_ratio_max": 0.75,       # each contraction <= 0.75 of the prior
        "vol_dryup_ratio_max": 0.85,       # vol into pivot <= 0.85 of base vol
        "max_base_depth_pct": 35.0,        # whole base no deeper than 35%
    },
    "volume_breakout": {"min_mult": 1.40, "avg_lookback": 50},  # entry vol >= 1.4x avg
    "rs_rank": {"top_decile": 0.10, "lookback": 126},           # ~6mo perf vs SPY, top 10%
    "not_extended": {
        "max_atr_above_pivot": 5.0,        # reject > 5*ATR above pivot (chasing)
        "atr_lookback": 14,
        "max_pct_above_ma_short": 12.0,    # reject > 12% above the 50-MA
        "rsi_pin_level": 80.0, "rsi_lookback": 14,
    },
    "liquidity": {"min_avg_dollar_vol": 20_000_000, "lookback": 50},  # $20M/day floor
}


@dataclass
class FilterResult:
    name: str
    passed: Optional[bool]   # None == deferred / insufficient data (NOT a pass)
    value: Optional[float]
    detail: str


# ---- primitives (all read bars[0..i] only) -----------------------------------
def _sma(bars, i, n):
    if i + 1 < n:
        return None
    return sum(b["c"] for b in bars[i - n + 1:i + 1]) / n

def _rising(bars, i, n, lookback):
    """True if the n-SMA today > the n-SMA `lookback` bars ago."""
    now, prev = _sma(bars, i, n), _sma(bars, i - lookback, n)
    if now is None or prev is None:
        return None
    return now > prev

def _atr(bars, i, n):
    if i < n:
        return None
    trs = []
    for k in range(i - n + 1, i + 1):
        h, l, pc = bars[k]["h"], bars[k]["l"], bars[k - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / n

def _rsi(bars, i, n):
    if i < n:
        return None
    gains = losses = 0.0
    for k in range(i - n + 1, i + 1):
        ch = bars[k]["c"] - bars[k - 1]["c"]
        gains += max(ch, 0.0); losses += max(-ch, 0.0)
    if losses == 0:
        return 100.0
    rs = (gains / n) / (losses / n)
    return 100.0 - 100.0 / (1.0 + rs)


# ---- the pre-registered filters ----------------------------------------------
def f_trend_template(bars, i, p=PARAMS["trend_template"]) -> FilterResult:
    """#1 HARD trend template — price>50>150>200, all rising, 200 rising >=1mo. GATE."""
    c = bars[i]["c"]
    s, m, l = _sma(bars, i, p["ma_short"]), _sma(bars, i, p["ma_mid"]), _sma(bars, i, p["ma_long"])
    if None in (s, m, l):
        return FilterResult("trend_template", None, None, "insufficient history (<200 bars)")
    l_rising = _rising(bars, i, p["ma_long"], p["long_rising_lookback"])
    s_rising = _rising(bars, i, p["ma_short"], p["long_rising_lookback"])
    stacked = c > s > m > l
    ok = bool(stacked and l_rising and s_rising)
    return FilterResult("trend_template", ok, None,
                        f"c>{s:.2f}>{m:.2f}>{l:.2f} stacked={stacked} 200_rising={l_rising}")

def f_vcp(bars, i, p=PARAMS["vcp"]) -> FilterResult:
    """#2 VCP — successive shallower pullbacks + volume dry-up into the pivot."""
    win = bars[max(0, i - 60):i + 1]
    if len(win) < 25:
        return FilterResult("vcp", None, None, "insufficient base history")
    # find swing highs/lows -> measure successive contraction depths
    depths, last_high = [], win[0]["h"]
    cur_low = win[0]["l"]
    for b in win[1:]:
        if b["h"] >= last_high:
            if cur_low < last_high:
                depths.append((last_high - cur_low) / last_high * 100.0)
            last_high, cur_low = b["h"], b["l"]
        else:
            cur_low = min(cur_low, b["l"])
    depths.append((last_high - cur_low) / last_high * 100.0)
    depths = [d for d in depths if d > 0.5]
    if len(depths) < p["min_contractions"]:
        return FilterResult("vcp", False, None, f"only {len(depths)} contractions")
    tightening = all(depths[k + 1] <= depths[k] * p["tightness_ratio_max"]
                     for k in range(len(depths) - 1))
    base_vol = sum(b["v"] for b in win[:len(win) // 2]) / max(1, len(win) // 2)
    pivot_vol = sum(b["v"] for b in win[-5:]) / 5.0
    dryup = pivot_vol <= base_vol * p["vol_dryup_ratio_max"]
    ok = bool(tightening and dryup and max(depths) <= p["max_base_depth_pct"])
    return FilterResult("vcp", ok, depths[-1],
                        f"depths={[round(d,1) for d in depths]} tighten={tightening} dryup={dryup}")

def f_volume_breakout(bars, i, p=PARAMS["volume_breakout"]) -> FilterResult:
    """#3 breakout bar volume >= 1.4x the trailing average."""
    n = p["avg_lookback"]
    if i < n:
        return FilterResult("volume_breakout", None, None, "insufficient vol history")
    avg = sum(b["v"] for b in bars[i - n:i]) / n   # strictly PRIOR bars
    if avg <= 0:
        return FilterResult("volume_breakout", None, None, "zero avg volume")
    mult = bars[i]["v"] / avg
    return FilterResult("volume_breakout", mult >= p["min_mult"], mult, f"vol {mult:.2f}x avg")

def f_rs_rank(bars, i, spy_bars=None, peer_returns=None, p=PARAMS["rs_rank"]) -> FilterResult:
    """#4 RS RANK vs SPY — top decile of the surviving universe.
    Ranking needs the cross-section (peer_returns) which the single-name series
    cannot supply -> DEFERRED here. We expose the name's own RS strength so the
    engine can rank it against peers at scan time (still anti-look-ahead: lookback
    perf uses bars[i-lookback..i] only)."""
    n = p["lookback"]
    if i < n or spy_bars is None or len(spy_bars) <= i:
        return FilterResult("rs_rank", None, None, "needs SPY series + peer cross-section to rank")
    r_stock = bars[i]["c"] / bars[i - n]["c"] - 1.0
    r_spy = spy_bars[i]["c"] / spy_bars[i - n]["c"] - 1.0
    rs = r_stock - r_spy
    if peer_returns is None:
        return FilterResult("rs_rank", None, rs, f"RS vs SPY={rs:+.3f}; peer cross-section needed for decile")
    rank = sum(1 for x in peer_returns if x <= rs) / len(peer_returns)
    return FilterResult("rs_rank", rank >= 1.0 - p["top_decile"], rank, f"RS pct-rank={rank:.2f}")

def f_not_extended(bars, i, pivot=None, p=PARAMS["not_extended"]) -> FilterResult:
    """#5 NOT-EXTENDED exclusion — reject chasing (the at_market bleed). EXCLUSION GATE."""
    atr = _atr(bars, i, p["atr_lookback"])
    sma = _sma(bars, i, 50)
    rsi = _rsi(bars, i, p["rsi_lookback"])
    if None in (atr, sma, rsi) or atr == 0:
        return FilterResult("not_extended", None, None, "insufficient history")
    c = bars[i]["c"]
    pivot = pivot if pivot is not None else sma
    atr_above = (c - pivot) / atr
    pct_above_ma = (c - sma) / sma * 100.0
    too_far_atr = atr_above > p["max_atr_above_pivot"]
    too_far_ma = pct_above_ma > p["max_pct_above_ma_short"]
    rsi_pinned = rsi >= p["rsi_pin_level"]
    ok = not (too_far_atr or too_far_ma or rsi_pinned)   # pass == NOT extended
    return FilterResult("not_extended", ok, atr_above,
                        f"{atr_above:.1f}ATR above pivot, {pct_above_ma:.1f}% above 50MA, RSI {rsi:.0f}")

def f_liquidity(bars, i, p=PARAMS["liquidity"]) -> FilterResult:
    """#7 liquidity floor — min avg dollar volume (reject thin names)."""
    n = p["lookback"]
    if i + 1 < n:
        return FilterResult("liquidity", None, None, "insufficient history")
    adv = sum(b["c"] * b["v"] for b in bars[i - n + 1:i + 1]) / n
    return FilterResult("liquidity", adv >= p["min_avg_dollar_vol"], adv, f"ADV ${adv/1e6:.1f}M")

# #6 earnings/growth (CANSLIM) is DEFERRED — not computable from OHLCV. The engine
# must supply fundamentals (Polygon/feeds). Flagged deferred, never fabricated.
def f_earnings_growth(*_args, **_kw) -> FilterResult:
    return FilterResult("earnings_growth", None, None,
                        "DEFERRED — needs fundamentals feed (accel EPS/rev + surprise); not in OHLCV")


STACK = [f_trend_template, f_vcp, f_volume_breakout, f_not_extended, f_liquidity]

def evaluate_stack(bars, i, **ctx) -> Dict[str, FilterResult]:
    out = {}
    for fn in STACK:
        out[fn.__name__] = fn(bars, i)
    out["f_rs_rank"] = f_rs_rank(bars, i, ctx.get("spy_bars"), ctx.get("peer_returns"))
    out["f_earnings_growth"] = f_earnings_growth()
    return out

def enhanced_pass(results: Dict[str, FilterResult]) -> bool:
    """ENHANCED-pass == all GATING filters pass. Deferred (None) filters do NOT
    block (they are not yet measurable) but are recorded. Gates: trend_template,
    not_extended, liquidity, volume_breakout. VCP/RS rank inform ranking."""
    gates = ["f_trend_template", "f_not_extended", "f_liquidity", "f_volume_breakout"]
    return all(results[g].passed is True for g in gates)


# ---- self-test: prove anti-look-ahead + sane behavior ------------------------
def _synth(n=320, seed=7):
    """Deterministic synthetic uptrend with a tightening base — no Math.random reliance."""
    bars, c = [], 10.0
    for t in range(n):
        # gentle uptrend + shrinking oscillation (a crude VCP-ish base near the end)
        trend = 0.06
        osc = (1.0 if (t // 7) % 2 == 0 else -1.0) * max(0.02, 1.2 - t / n) * 0.18
        c = max(1.0, c + trend + osc)
        h = c * 1.012; l = c * 0.988; o = (h + l) / 2
        v = 1_000_000 * (1.0 + 0.3 * ((t * 13) % 5) - (0.4 if t > n - 8 else 0))  # dry-up at pivot
        bars.append({"o": o, "h": h, "l": l, "c": c, "v": max(1, v)})
    return bars

def _selftest():
    bars = _synth()
    i = len(bars) - 1
    spy = _synth(seed=2)  # flat-ish proxy; stock should out-RS it
    # 1) every filter returns a FilterResult and never raises
    res = evaluate_stack(bars, i, spy_bars=spy, peer_returns=[-0.1, 0.0, 0.05, 0.2, 0.4])
    assert set(res) >= {"f_trend_template", "f_vcp", "f_volume_breakout",
                        "f_not_extended", "f_liquidity", "f_rs_rank", "f_earnings_growth"}
    # 2) ANTI-LOOK-AHEAD PROOF: verdict at index i must be identical whether or not
    #    future bars exist. Evaluate at a mid index j with full series vs truncated.
    j = 250
    full = evaluate_stack(bars, j, spy_bars=spy)
    trunc = evaluate_stack(bars[:j + 1], j, spy_bars=spy[:j + 1])
    for k in full:
        a, b = full[k], trunc[k]
        assert (a.passed, a.value) == (b.passed, b.value), \
            f"LOOK-AHEAD LEAK in {k}: full={a.passed,a.value} trunc={b.passed,b.value}"
    # 3) not_extended must FLAG a chased name (price blown far above pivot)
    chased = [dict(x) for x in bars]
    chased[i] = dict(chased[i]); chased[i]["c"] *= 1.6; chased[i]["h"] = chased[i]["c"] * 1.01
    ne = f_not_extended(chased, i)
    assert ne.passed is False, f"not_extended failed to reject a chased name: {ne.detail}"
    # 4) deferred filters return None (not a silent pass)
    assert f_earnings_growth().passed is None
    assert f_rs_rank(bars, i, spy, None).passed is None  # no peer cross-section
    print("SELF-TEST PASS — no look-ahead leak; gates behave; deferred==None (not pass)")
    print("sample verdicts @ i:", {k: v.passed for k, v in res.items()})
    print("enhanced_pass(sample):", enhanced_pass(res))

if __name__ == "__main__":
    _selftest()
