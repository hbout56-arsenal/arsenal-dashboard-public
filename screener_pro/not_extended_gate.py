#!/usr/bin/env python3
"""
not_extended_gate.py — Dispatch 51 (LOAD ON REVIEW)

The ONE D50 filter that earned promotion on forward data: the not-extended /
no-chase EXCLUSION GATE. D50 forward read: at_market (chase/extended) −8.92%
(n=105) vs pullback_limit (not-extended) −0.04% (n=291) = +8.88 pts/trade,
both legs n>=30, survives the divide-by-N=8 haircut (+1.11).

This hardens the soft at_market-vs-pullback entry split into an EXPLICIT gate.
Thresholds are FROZEN from D50 preregistration.json — NOT re-tuned here
(re-tuning post-validation re-introduces overfit; that is forbidden by the dispatch).

Behavior contract:
  * GATE, not delete. evaluate() returns extended=True/False + the reasons. The
    engine TAGS the pick (extended=...) and demotes EXTENDED picks out of the
    actionable/ENHANCED list to context-only. The pick STILL logs to the ledger.
  * RAW control preserved. The ungated series keeps logging untouched — the gate
    only adds a flag; it never stops the RAW comparison.
  * Anti-look-ahead. ATR(14), SMA50, RSI(14) read bars[0..signal_index] only.
    Proven by the truncation test in the self-test below.

Only filter 5 ships here. Filters 1-4/6/7 stay DEFERRED (D52).
SIMULATED / advisory.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional

# ---- FROZEN pre-registered thresholds (D50 preregistration.json, filter 5) ----
# DO NOT EDIT to "improve" results — any change is a new pre-registration.
THRESHOLDS = {
    "max_atr_above_pivot": 5.0,    # reject > 5*ATR(14) above the breakout pivot
    "atr_lookback": 14,
    "max_pct_above_ma_short": 12.0,  # reject > 12% above the (rising) 50-MA
    "ma_short": 50,
    "rsi_pin_level": 80.0,         # reject RSI(14) >= 80 (pinned)
    "rsi_lookback": 14,
}
HONESTY_LINE = ("Not-extended gate (validated +8.88 pts/trade forward, n>=30, "
                "haircut-survived). RAW control still tracked.")


@dataclass
class GateVerdict:
    extended: bool                 # True => chasing => gated out of actionable
    reasons: List[str]             # which sub-rule(s) tripped
    atr_above_pivot: Optional[float]
    pct_above_ma50: Optional[float]
    rsi: Optional[float]
    insufficient: bool             # not enough history to judge (treated as NOT-gated, flagged)

    def as_dict(self):  # JSON-friendly
        return asdict(self)


# ---- primitives: read bars[0..i] ONLY (anti-look-ahead) ----------------------
def _sma(bars, i, n):
    if i + 1 < n:
        return None
    return sum(b["c"] for b in bars[i - n + 1:i + 1]) / n

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


def evaluate(bars: List[Dict], signal_index: int,
             pivot: Optional[float] = None, t=THRESHOLDS) -> GateVerdict:
    """Decide if the pick at `signal_index` is EXTENDED (chasing). bars oldest-first,
    each {o,h,l,c,v}. `pivot` = breakout pivot; defaults to the 50-MA when absent."""
    i = signal_index
    atr = _atr(bars, i, t["atr_lookback"])
    sma = _sma(bars, i, t["ma_short"])
    rsi = _rsi(bars, i, t["rsi_lookback"])
    if atr is None or sma is None or rsi is None or atr == 0:
        return GateVerdict(False, ["insufficient_history"], None, None, rsi, True)
    c = bars[i]["c"]
    pv = pivot if pivot is not None else sma
    atr_above = (c - pv) / atr
    pct_above = (c - sma) / sma * 100.0
    reasons = []
    if atr_above > t["max_atr_above_pivot"]:
        reasons.append(f">{t['max_atr_above_pivot']}xATR above pivot ({atr_above:.1f})")
    if pct_above > t["max_pct_above_ma_short"]:
        reasons.append(f">{t['max_pct_above_ma_short']}% above 50MA ({pct_above:.1f}%)")
    if rsi >= t["rsi_pin_level"]:
        reasons.append(f"RSI pinned ({rsi:.0f}>={t['rsi_pin_level']:.0f})")
    return GateVerdict(bool(reasons), reasons, round(atr_above, 2),
                       round(pct_above, 2), round(rsi, 1), False)


def tag_pick(pick: Dict, bars: List[Dict], signal_index: int,
             pivot: Optional[float] = None) -> Dict:
    """Return a copy of `pick` with the gate fields added. Does NOT drop the pick —
    the engine uses pick['extended'] to demote it to context-only while RAW logs on."""
    v = evaluate(bars, signal_index, pivot)
    out = dict(pick)
    out["extended"] = v.extended
    out["extended_reasons"] = v.reasons
    out["not_extended_clean"] = (not v.extended) and (not v.insufficient)
    out["gate_metrics"] = {"atr_above_pivot": v.atr_above_pivot,
                           "pct_above_ma50": v.pct_above_ma50, "rsi": v.rsi}
    out["gate_status"] = ("INSUFFICIENT_HISTORY" if v.insufficient
                          else ("EXTENDED" if v.extended else "NOT_EXTENDED"))
    return out


# ---- self-test: sample EXTENDED vs clean + anti-look-ahead proof -------------
def _series(n, start, step, osc=0.0, tail_pump=0.0):
    bars, c = [], float(start)
    for t in range(n):
        c = max(0.5, c + step + (osc if (t // 5) % 2 == 0 else -osc))
        if tail_pump and t >= n - 1:
            c *= (1.0 + tail_pump)               # blow the last bar up (a chase)
        h, l = c * 1.012, c * 0.988
        bars.append({"o": (h + l) / 2, "h": h, "l": l, "c": c, "v": 1_000_000})
    return bars

def _selftest():
    import json
    # CLEAN: steady advance, last bar near the 50-MA, RSI not pinned, near pivot
    clean = _series(120, 50, 0.05, osc=0.25)
    i = len(clean) - 1
    pivot_clean = _sma(clean, i, 50)            # entering right at structure
    vc = evaluate(clean, i, pivot=pivot_clean)
    # EXTENDED: same base but the entry bar is pumped far above pivot/50-MA
    ext = _series(120, 50, 0.05, osc=0.25, tail_pump=0.45)
    pivot_ext = _sma(ext, i, 50)
    ve = evaluate(ext, i, pivot=pivot_ext)

    assert vc.extended is False, f"clean wrongly gated: {vc.reasons}"
    assert ve.extended is True, f"extended not gated: {ve.as_dict()}"

    # ANTI-LOOK-AHEAD: verdict at a mid index must be identical on full vs truncated series
    j = 90
    full = evaluate(clean, j, pivot=_sma(clean, j, 50))
    trunc = evaluate(clean[:j + 1], j, pivot=_sma(clean[:j + 1], j, 50))
    assert (full.extended, full.atr_above_pivot, full.pct_above_ma50, full.rsi) == \
           (trunc.extended, trunc.atr_above_pivot, trunc.pct_above_ma50, trunc.rsi), \
           "LOOK-AHEAD LEAK in not_extended gate"

    print("SELF-TEST PASS — clean kept, extended gated, no look-ahead leak")
    print("CLEAN   pick verdict:", json.dumps(vc.as_dict()))
    print("EXTENDED pick verdict:", json.dumps(ve.as_dict()))
    # emit sample tagged picks (used by not_extended_gate.json demonstration)
    sample = [
        tag_pick({"ticker": "CLEAN_DEMO", "direction": "LONG", "entry": round(clean[i]["c"], 2)},
                 clean, i, pivot_clean),
        tag_pick({"ticker": "EXT_DEMO", "direction": "LONG", "entry": round(ext[i]["c"], 2)},
                 ext, i, pivot_ext),
    ]
    print("SAMPLE_TAGGED:", json.dumps(sample))
    return sample

if __name__ == "__main__":
    _selftest()
