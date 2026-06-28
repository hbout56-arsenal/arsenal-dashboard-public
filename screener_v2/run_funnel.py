#!/usr/bin/env python3
"""
screener_v2/run_funnel.py — Dispatch 53 funnel runner (SHADOW · build, don't load)

Two entry points:
  * run_real(universe_path, spy_path)  — run the funnel on a REAL universe the engine
    supplies (point-in-time bars + optional fundamentals). THIS is the real report.
  * _smoke()                           — run on a SYNTHETIC fixture to demonstrate the
    funnel MECHANICS end-to-end (incl. fully-qualified picks). NOT a real edge funnel,
    NOT proof — survivorship-biased by construction; labelled SYNTHETIC everywhere.

The synthetic fixture tunes only the INPUT data (legitimate smoke-test fixtures). It
NEVER tunes the frozen Stage thresholds (that would be post-hoc overfit, forbidden).

SIMULATED / advisory. v2 is SHADOW: logs only, never feeds the live engine.
"""
from __future__ import annotations
import json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
import pipeline as P


def run_real(universe: dict, spy_bars: list, signal_index=None) -> dict:
    """universe: {ticker: {"bars":[{o,h,l,c,v}...], "fundamentals":{...}|None}}.
    Returns the funnel + qualified picks. The engine repo calls this with Polygon data."""
    out = P.run_pipeline(universe, spy_bars, signal_index)
    out["source"] = "REAL"
    return out


# ---------------- synthetic fixtures (INPUT only; thresholds frozen) -----------
def _uptrend(n_pre, start, slope):
    """A clean rising leg that builds a 52-week range + rising 50/150/200 MAs."""
    bars, c = [], float(start)
    for _ in range(n_pre):
        c *= (1 + slope)
        h, l = c * 1.010, c * 0.990
        bars.append({"o": (h + l) / 2, "h": h, "l": l, "c": c, "v": 1_000_000})
    return bars

def _vcp_base(bars, contractions, base_len, dollar_per_share, dryup=True):
    """Append a textbook VCP base: successive shallower pullbacks under a pivot, with
    volume declining into the pivot, then a breakout bar just above the pivot."""
    pivot = bars[-1]["h"]
    seg = max(4, base_len // (len(contractions) + 1))
    base_vol = 1_000_000
    for ci, depth in enumerate(contractions):
        low = pivot * (1 - depth / 100.0)
        # down into the contraction low, then back up toward the pivot
        half = max(2, seg // 2)
        for k in range(half):                      # pull back
            c = pivot - (pivot - low) * (k + 1) / half
            h, l = c * 1.006, c * 0.994
            v = base_vol * (1.0 - 0.12 * ci)       # volume fades each successive contraction
            bars.append({"o": c, "h": h, "l": max(l, low), "c": c, "v": v})
        for k in range(seg - half):                # recover toward pivot (undercut the pivot)
            c = low + (pivot - low) * (k + 1) / (seg - half) * 0.985
            h, l = min(c * 1.006, pivot * 0.999), c * 0.994
            v = base_vol * (0.85 - 0.12 * ci)
            bars.append({"o": c, "h": h, "l": l, "c": c, "v": v})
    # volume dry-up bars right under the pivot
    for _ in range(5):
        c = pivot * 0.992
        bars.append({"o": c, "h": pivot * 0.998, "l": c * 0.995, "c": c,
                     "v": base_vol * (0.40 if dryup else 1.3)})
    # breakout bar: just above the pivot, on confirming volume, NOT extended
    c = pivot * 1.004
    bars.append({"o": pivot * 0.999, "h": c * 1.004, "l": pivot * 0.997, "c": c,
                 "v": base_vol * 1.6})
    return bars, round(pivot, 2)

def _make_vcp_name(start=8.0, slope=0.013, n_pre=245, contractions=(22, 13, 7)):
    bars = _uptrend(n_pre, start, slope)
    bars, pivot = _vcp_base(bars, list(contractions), base_len=48, dollar_per_share=start)
    # base share-volume ~1M at price ~$100+ => ADV well above the $20M floor; dry-up
    # shape is preserved (no flat-dollar rescale, which would destroy the dry-up signal).
    return {"bars": bars, "fundamentals": None}

def _smoke():
    spy = _uptrend(300, 100, 0.0006)
    uni = {
        "VCP_A": _make_vcp_name(start=9.0, slope=0.0135, contractions=(24, 14, 8)),
        "VCP_B": _make_vcp_name(start=12.0, slope=0.0120, contractions=(20, 12, 6)),
        "VCP_C": _make_vcp_name(start=7.5, slope=0.0150, contractions=(28, 16, 9)),
        "NO_DRYUP": _make_vcp_name(start=10.0, slope=0.0130, contractions=(22, 13, 7)),
        "THIN": {"bars": _make_vcp_name(start=9.0, slope=0.0135)["bars"][:], "fundamentals": None},
        "DOWNTREND": {"bars": _uptrend(120, 80, -0.004), "fundamentals": None},
        "CHOP": {"bars": _uptrend(300, 50, 0.0)[:-1] + [{"o":50,"h":51,"l":49,"c":50,"v":3_000_000}], "fundamentals": None},
    }
    # make NO_DRYUP fail the volume dry-up; make THIN illiquid
    for b in uni["NO_DRYUP"]["bars"][-10:]:
        b["v"] *= 4
    for b in uni["THIN"]["bars"]:
        b["v"] = 1000.0
    out = P.run_pipeline(uni, spy)
    out["source"] = "SYNTHETIC_SMOKE — mechanics only, NOT a real funnel, NOT proof (survivorship-biased)"
    return out


if __name__ == "__main__":
    out = _smoke()
    f = out["funnel"]
    print("SOURCE:", out["source"])
    print("\nFUNNEL  universe=%d -> stage1=%d -> stage2=%d -> stage3_vcp=%d -> stage4_top=%d  (watch=%d)"
          % (f["universe"], f["stage1"], f["stage2"], f["stage3_vcp"], f["stage4_top"], f["watch"]))
    print("\nQUALIFIED (top-decile) sample picks — full record:")
    for p in out["qualified"]:
        d5 = p["detail"].get("s5", {})
        print("  %-7s pivot=%s base_depth=%s%% contractions=%s rs=%.4f rank=%s | entry vol=%sx not_ext=%s stop=%s target=%s s5_pass=%s"
              % (p["ticker"], p["pivot"], p["base_depth_pct"], p["contraction_count"],
                 p["rs_score"], p["rs_rank"], d5.get("vol_confirm_mult"), p["not_extended"],
                 p["stop"], p["target"], p["stage_pass"]["s5"]))
    print("\nWATCH / REJECTED (why):")
    for p in out["all_picks"]:
        if p["status"] != "QUALIFIED" or p["ticker"] not in {q["ticker"] for q in out["qualified"]}:
            print("  %-9s %-9s %s" % (p["ticker"], p["status"], p.get("reject_stage")))
