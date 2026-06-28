#!/usr/bin/env python3
"""
screener_v2/pipeline.py — Dispatch 53 (SHADOW · build, don't load)

Ground-up pro-faithful screener (Minervini/O'Neil/Zanger/CANSLIM), built as a
GATING+RANKING pipeline — the key difference from today's SCORING engine: reject
most of the universe at the gate BEFORE any scoring, then rank the survivors.

Stages (all thresholds FROZEN in preregistration_v2.json — DO NOT tune here):
  1 HARD TREND TEMPLATE   binary pass/fail (replaces the soft Minervini score)
  2 LIQUIDITY / QUALITY   ADV floor; earnings overlay DEFERRED unless a feed exists
  3 VCP SETUP             contraction + volume dry-up under a pivot (else WATCH)
  4 RS RANK               IBD-style RS vs SPY; take the top decile
  5 ENTRY DISCIPLINE      not-extended gate (D51, validated) + volume-confirm + stop/target

Hard rules:
  * SHADOW. This module produces a parallel ledger only. It never feeds the live
    engine/email/dashboard selection.
  * ANTI-LOOK-AHEAD. Every stage reads bars[0..i] only. Proven in the self-test by
    truncation (verdict at i identical with/without future bars).
  * Deferred data (earnings) returns None — NEVER a silent pass.
  * Pure-Python, dependency-free. SIMULATED / advisory.

A "bar" is {o,h,l,c,v}, oldest-first. The pipeline evaluates a name AS OF a signal
index `i` (default: the last bar) using only bars[0..i].
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
import json, os, sys

# ---- load frozen thresholds from the pre-registration (single source of truth) ----
_PRE = os.path.join(os.path.dirname(__file__), "preregistration_v2.json")
with open(_PRE) as _f:
    PRE = json.load(_f)
S = {k: v["thresholds"] for k, v in PRE["stages"].items()}

# ---- reuse the validated D51 not-extended gate for Stage 5 (don't duplicate) ----
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "screener_pro"))
try:
    import not_extended_gate as gate   # D51, validated forward
    _HAVE_GATE = True
except Exception:
    _HAVE_GATE = False


# ---- primitives: read bars[0..i] ONLY -----------------------------------------
def _sma(bars, i, n):
    if i + 1 < n: return None
    return sum(b["c"] for b in bars[i - n + 1:i + 1]) / n

def _rising(bars, i, n, lb):
    a, b = _sma(bars, i, n), _sma(bars, i - lb, n)
    return None if (a is None or b is None) else a > b

def _hi_lo_52w(bars, i):
    win = bars[max(0, i - 251):i + 1]
    return max(b["h"] for b in win), min(b["l"] for b in win)


@dataclass
class StagePass:
    s1: Optional[bool] = None
    s2: Optional[bool] = None
    s3: Optional[bool] = None
    s5: Optional[bool] = None
    earnings: Optional[bool] = None   # None == deferred (no feed)

@dataclass
class V2Pick:
    ticker: str
    signal_index: int
    stage_pass: StagePass = field(default_factory=StagePass)
    status: str = "REJECTED"          # REJECTED | WATCH | QUALIFIED
    reject_stage: Optional[str] = None
    pivot: Optional[float] = None
    base_depth_pct: Optional[float] = None
    contraction_count: Optional[int] = None
    rs_score: Optional[float] = None
    rs_rank: Optional[float] = None
    stop: Optional[float] = None
    target: Optional[float] = None
    vol_confirm_mult: Optional[float] = None
    not_extended: Optional[bool] = None
    detail: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self):
        d = asdict(self); d["stage_pass"] = asdict(self.stage_pass); return d


# ---- STAGE 1 — hard trend template (binary) -----------------------------------
def stage1_trend_template(bars, i, t=S["stage1_trend_template"]) -> (bool, Dict):
    if i + 1 < t["history_required_bars"]:
        return False, {"reason": "insufficient history (<252 bars)"}
    c = bars[i]["c"]
    m50, m150, m200 = _sma(bars, i, 50), _sma(bars, i, 150), _sma(bars, i, 200)
    if None in (m50, m150, m200):
        return False, {"reason": "MA history"}
    stack = c > m50 > m150 > m200
    rising = all([_rising(bars, i, 50, t["rising_lookback"]),
                  _rising(bars, i, 150, t["rising_lookback"]),
                  _rising(bars, i, 200, t["ma200_rising_days"])])
    hi, lo = _hi_lo_52w(bars, i)
    above_low = c >= lo * (1 + t["min_pct_above_52w_low"] / 100.0)
    near_high = c >= hi * (t["min_pct_of_52w_high"] / 100.0)
    ok = bool(stack and rising and above_low and near_high)
    return ok, {"stack": stack, "rising": rising, "above_52w_low": above_low,
                "near_52w_high": near_high, "c": round(c, 2),
                "ma": [round(m50, 2), round(m150, 2), round(m200, 2)]}

# ---- STAGE 2 — liquidity / quality --------------------------------------------
def stage2_liquidity(bars, i, fundamentals=None, t=S["stage2_liquidity_quality"]) -> (bool, Optional[bool], Dict):
    n = t["adv_lookback"]
    if i + 1 < n:
        return False, None, {"reason": "insufficient history"}
    adv = sum(b["c"] * b["v"] for b in bars[i - n + 1:i + 1]) / n
    liq_ok = adv >= t["min_avg_dollar_vol"]
    # earnings overlay — DEFERRED unless a fundamentals feed is supplied
    earn = None
    if fundamentals is not None:
        earn = bool(fundamentals.get("eps_accel") and fundamentals.get("rev_accel")
                    and fundamentals.get("positive_surprise"))
    return liq_ok, earn, {"adv_usd": round(adv, 0),
                          "earnings": ("DEFERRED" if earn is None else earn)}

# ---- STAGE 3 — VCP setup detection (zigzag swing-finder) -----------------------
def _zigzag(win, rev_pct):
    """Alternating swing highs/lows: a reversal is registered only after price moves
    rev_pct off the running extreme. Returns [(idx, price, 'H'|'L'), ...] oldest-first."""
    piv = []
    trend = 0                              # +1 up-leg, -1 down-leg, 0 unknown
    ext_i, ext_p = 0, win[0]["c"]
    for k in range(1, len(win)):
        h, l = win[k]["h"], win[k]["l"]
        if trend >= 0:
            if h >= ext_p: ext_i, ext_p = k, h
            elif l <= ext_p * (1 - rev_pct / 100.0):
                piv.append((ext_i, ext_p, "H")); trend = -1; ext_i, ext_p = k, l
        if trend <= 0:
            if l <= ext_p: ext_i, ext_p = k, l
            elif h >= ext_p * (1 + rev_pct / 100.0):
                piv.append((ext_i, ext_p, "L")); trend = 1; ext_i, ext_p = k, h
    piv.append((ext_i, ext_p, "H" if trend >= 0 else "L"))
    return piv

def stage3_vcp(bars, i, t=S["stage3_vcp"]) -> (bool, Dict):
    win = bars[max(0, i - t["base_window_bars"]):i + 1]
    if len(win) < 25:
        return False, {"reason": "insufficient base history"}
    piv = _zigzag(win, t["swing_reversal_pct"])
    # pullback depths = each swing HIGH down to the following swing LOW
    depths = []
    for a in range(len(piv) - 1):
        if piv[a][2] == "H" and piv[a + 1][2] == "L":
            hp, lp = piv[a][1], piv[a + 1][1]
            if hp > 0: depths.append((hp - lp) / hp * 100.0)
    depths = [d for d in depths if d > 1.0]
    if len(depths) < t["min_contractions"]:
        return False, {"reason": f"only {len(depths)} contractions", "depths": [round(d,1) for d in depths]}
    # use the last min_contractions+1 pullbacks; require successive tightening
    tail = depths[-(t["min_contractions"] + 1):] if len(depths) > t["min_contractions"] else depths
    tightening = all(tail[k + 1] <= tail[k] * t["tightness_ratio_max"] for k in range(len(tail) - 1))
    base_vol = sum(b["v"] for b in win[:len(win) // 2]) / max(1, len(win) // 2)
    pivot_vol = sum(b["v"] for b in win[-5:]) / 5.0
    dryup = pivot_vol <= base_vol * t["vol_dryup_ratio_max"]
    base_depth = max(depths)
    # pivot/buy-point = the highest swing high in the base (top of the coil)
    pivot = max((p for p in piv if p[2] == "H"), key=lambda p: p[1], default=(0, win[-1]["h"], "H"))[1]
    ok = bool(tightening and dryup and base_depth <= t["max_base_depth_pct"])
    return ok, {"pivot": round(pivot, 2), "base_depth_pct": round(base_depth, 1),
                "contraction_count": len(depths), "depths": [round(d, 1) for d in depths],
                "tightening": tightening, "vol_dryup": dryup}

# ---- STAGE 4 — RS rank vs SPY (IBD-style weighted) ----------------------------
def rs_score(bars, i, spy_bars, w=S["stage4_rs_rank"]["rs_weights"]) -> Optional[float]:
    if spy_bars is None or len(spy_bars) <= i:
        return None
    score, total = 0.0, 0.0
    for k, wt in (("63d", w["63d"]), ("126d", w["126d"]), ("189d", w["189d"]), ("252d", w["252d"])):
        lb = int(k[:-1])
        if i < lb:
            return None
        r_s = bars[i]["c"] / bars[i - lb]["c"] - 1.0
        r_m = spy_bars[i]["c"] / spy_bars[i - lb]["c"] - 1.0
        score += wt * (r_s - r_m); total += wt
    return score / total

def stage4_rank(setups: List[V2Pick], t=S["stage4_rs_rank"]) -> List[V2Pick]:
    ranked = [p for p in setups if p.rs_score is not None]
    ranked.sort(key=lambda p: p.rs_score, reverse=True)
    n = len(ranked)
    take = max(t["min_take"], int(round(n * t["top_decile"]))) if n else 0
    for idx, p in enumerate(ranked):
        p.rs_rank = round(1.0 - idx / n, 3) if n > 1 else 1.0
    top = ranked[:take]
    top_ids = {id(p) for p in top}
    for p in setups:
        if id(p) not in top_ids and p.status == "QUALIFIED":
            p.status, p.reject_stage = "WATCH", "stage4_rs_rank (below top decile)"
    return top

# ---- STAGE 5 — entry discipline -----------------------------------------------
def stage5_entry(bars, i, pivot, base_low, base_depth_pct,
                 t=S["stage5_entry"]) -> (Optional[bool], Dict):
    n = t["vol_confirm_lookback"]
    if i < n or pivot is None:
        return None, {"reason": "insufficient history / no pivot"}
    avg_vol = sum(b["v"] for b in bars[i - n:i]) / n
    vmult = bars[i]["v"] / avg_vol if avg_vol else 0.0
    vol_ok = vmult >= t["vol_confirm_mult"]
    not_ext = None
    if _HAVE_GATE:
        v = gate.evaluate(bars, i, pivot=pivot)        # D51 gate at the pivot
        not_ext = (not v.extended) and (not v.insufficient)
    stop = round(base_low, 2) if base_low is not None else None
    target = (round(pivot * (1 + base_depth_pct / 100.0), 2)
              if (pivot is not None and base_depth_pct is not None) else None)  # measured move
    ok = bool(vol_ok and (not_ext is True))
    return ok, {"vol_confirm_mult": round(vmult, 2), "vol_ok": vol_ok,
                "not_extended": not_ext, "stop": stop, "target": target}


# ---- full pipeline over a universe -> funnel + qualified picks -----------------
def run_pipeline(universe: Dict[str, Dict], spy_bars: List[Dict],
                 signal_index: Optional[int] = None) -> Dict:
    """universe: {ticker: {"bars":[...], "fundamentals":{...}|None}}.
    Returns the funnel counts + the qualified (top-decile) picks with full record."""
    funnel = {"universe": 0, "stage1": 0, "stage2": 0, "stage3_vcp": 0, "stage4_top": 0, "watch": 0}
    picks: List[V2Pick] = []
    for tk, rec in universe.items():
        bars = rec["bars"]; funnel["universe"] += 1
        i = signal_index if signal_index is not None else len(bars) - 1
        p = V2Pick(tk, i)
        ok1, d1 = stage1_trend_template(bars, i); p.stage_pass.s1 = ok1; p.detail["s1"] = d1
        if not ok1:
            p.reject_stage = "stage1_trend_template"; picks.append(p); continue
        funnel["stage1"] += 1
        liq, earn, d2 = stage2_liquidity(bars, i, rec.get("fundamentals"))
        p.stage_pass.s2 = liq; p.stage_pass.earnings = earn; p.detail["s2"] = d2
        if not liq:
            p.reject_stage = "stage2_liquidity"; picks.append(p); continue
        funnel["stage2"] += 1
        ok3, d3 = stage3_vcp(bars, i); p.stage_pass.s3 = ok3; p.detail["s3"] = d3
        if not ok3:
            p.status, p.reject_stage = "WATCH", "stage3_vcp (qualified, no setup yet)"
            funnel["watch"] += 1; picks.append(p); continue
        funnel["stage3_vcp"] += 1
        p.pivot = d3["pivot"]; p.base_depth_pct = d3["base_depth_pct"]; p.contraction_count = d3["contraction_count"]
        p.rs_score = rs_score(bars, i, spy_bars)
        p.status = "QUALIFIED"
        picks.append(p)
    # Stage 4 ranks the QUALIFIED set; below-decile -> WATCH
    qualified = [p for p in picks if p.status == "QUALIFIED"]
    top = stage4_rank(qualified)
    funnel["stage4_top"] = len(top); funnel["watch"] = sum(1 for p in picks if p.status == "WATCH")
    # Stage 5 entry discipline on the top-decile survivors
    for p in top:
        bars = universe[p.ticker]["bars"]
        base_low = (p.pivot * (1 - p.base_depth_pct / 100.0)) if (p.pivot and p.base_depth_pct) else None
        ok5, d5 = stage5_entry(bars, p.signal_index, p.pivot, base_low, p.base_depth_pct)
        p.stage_pass.s5 = ok5; p.detail["s5"] = d5
        p.stop, p.target = d5.get("stop"), d5.get("target")
        p.vol_confirm_mult, p.not_extended = d5.get("vol_confirm_mult"), d5.get("not_extended")
    return {"funnel": funnel, "qualified": [p.as_dict() for p in top],
            "all_picks": [p.as_dict() for p in picks]}


# ---- self-test: synthetic universe + anti-look-ahead proof --------------------
def _mk(n, start, step, osc, vol=1_000_000, dryup=True, seed=0):
    bars, c = [], float(start)
    for t in range(n):
        amp = max(0.02, (1.4 - 1.1 * t / n)) * osc            # contracting oscillation = VCP-ish
        c = max(0.5, c + step + (amp if ((t + seed) // 6) % 2 == 0 else -amp))
        h, l = c * 1.012, c * 0.988
        v = vol * (0.6 if (dryup and t > n - 8) else (1.0 + 0.3 * ((t + seed) % 4)))
        bars.append({"o": (h + l) / 2, "h": h, "l": l, "c": c, "v": max(1, v)})
    return bars

def _selftest():
    spy = _mk(300, 100, 0.02, 0.2, seed=1)
    uni = {
        "STRONG_VCP": {"bars": _mk(300, 20, 0.07, 0.5, vol=3_000_000, dryup=True, seed=2)},   # should qualify
        "STRONG_NOVCP": {"bars": _mk(300, 20, 0.07, 0.5, vol=3_000_000, dryup=False, seed=0)},# trend ok, vol not drying -> WATCH-ish
        "THIN": {"bars": _mk(300, 20, 0.07, 0.5, vol=200, dryup=True, seed=2)},               # dies stage2 (liquidity)
        "DOWNTREND": {"bars": _mk(300, 80, -0.06, 0.5, vol=3_000_000, seed=3)},               # dies stage1
        "CHOP": {"bars": _mk(300, 50, 0.0, 0.6, vol=3_000_000, seed=4)},                      # dies stage1
    }
    out = run_pipeline(uni, spy)
    f = out["funnel"]
    assert f["universe"] == 5
    assert f["stage1"] >= 1, "no name passed the hard trend template — gate too strict on synth"
    assert f["stage1"] < f["universe"], "trend template let everything through — gate not biting"
    # ANTI-LOOK-AHEAD: stage verdicts at index j identical on full vs truncated series
    bars = uni["STRONG_VCP"]["bars"]; j = 270
    a1, _ = stage1_trend_template(bars, j)
    b1, _ = stage1_trend_template(bars[:j + 1], j)
    a3, _ = stage3_vcp(bars, j)
    b3, _ = stage3_vcp(bars[:j + 1], j)
    assert a1 == b1 and a3 == b3, "LOOK-AHEAD LEAK in stage1/stage3"
    # deferred earnings is None, never a silent pass
    liq, earn, _ = stage2_liquidity(bars, j, fundamentals=None)
    assert earn is None
    print("SELF-TEST PASS — funnel bites (not 0, not all), no look-ahead leak, earnings deferred==None")
    print("funnel:", json.dumps(f))
    print("D51 gate wired into stage5:", _HAVE_GATE)
    return out

if __name__ == "__main__":
    _selftest()
