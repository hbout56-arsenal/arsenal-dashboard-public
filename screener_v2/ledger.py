#!/usr/bin/env python3
"""
screener_v2/ledger.py — Dispatch 53 forward ledger + head-to-head tracker (SHADOW)

screener_v2 logs its OWN forward pick ledger (screener_v2_picks) and tracks it
head-to-head vs the CURRENT engine's forward picks. Expectancy-led (net/PF/payoff,
win% footnote), ÷N haircut, n<30 DESCRIPTIVE, FORWARD never blended with HISTORICAL.

This is PLANTING: at day 0 there are 0 closed v2 trades, so the verdict is ACCRUING.
Promotion to live selection requires v2's FORWARD picks to beat the current engine's
FORWARD picks over n>=30, haircut-applied, plus an explicit go. Until then: SHADOW.

Anti-look-ahead: a pick is recorded at signal time with only data <= signal; outcome
is stamped later when the trade closes. SIMULATED / advisory.
"""
from __future__ import annotations
from typing import List, Dict, Optional
import json

LEDGER_FIELDS = ["ticker", "signal_date", "stage_pass_record", "vcp_base", "base_depth_pct",
                 "contraction_count", "rs_rank", "rs_score", "pivot", "stop", "target",
                 "entry_trigger", "vol_confirm_mult", "not_extended", "regime_at_signal",
                 "size_pct", "timestamp", "outcome", "return_pct", "R"]

HAIRCUT_N = 6  # 5 stage gates ablated + 1 full pipeline (from preregistration_v2.json)


def record_pick(v2pick: Dict, signal_date: str, regime_at_signal=None,
                size_pct=None, timestamp=None) -> Dict:
    """Normalize a pipeline V2Pick dict into a forward-ledger row (outcome unset)."""
    sp = v2pick.get("stage_pass", {})
    return {
        "ticker": v2pick.get("ticker"), "signal_date": signal_date,
        "stage_pass_record": {"s1": sp.get("s1"), "s2": sp.get("s2"), "s3": sp.get("s3"),
                              "s5": sp.get("s5"), "earnings": sp.get("earnings")},
        "vcp_base": v2pick.get("pivot"), "base_depth_pct": v2pick.get("base_depth_pct"),
        "contraction_count": v2pick.get("contraction_count"),
        "rs_rank": v2pick.get("rs_rank"), "rs_score": v2pick.get("rs_score"),
        "pivot": v2pick.get("pivot"), "stop": v2pick.get("stop"), "target": v2pick.get("target"),
        "entry_trigger": "pivot breakout + vol>=1.4x", "vol_confirm_mult": v2pick.get("vol_confirm_mult"),
        "not_extended": v2pick.get("not_extended"), "regime_at_signal": regime_at_signal,
        "size_pct": size_pct, "timestamp": timestamp,
        "outcome": None, "return_pct": None, "R": None,   # stamped at close
    }


def _stats(closed: List[Dict]) -> Dict:
    """Expectancy-led stats over closed trades (return_pct present)."""
    rs = [t["return_pct"] for t in closed if t.get("return_pct") is not None]
    n = len(rs)
    if n == 0:
        return {"n": 0, "expectancy_pct": None, "profit_factor": None, "payoff_ratio": None,
                "win_rate_pct": None, "status": "ACCRUING (n=0)"}
    wins = [r for r in rs if r > 0]; losses = [r for r in rs if r <= 0]
    gross_w, gross_l = sum(wins), -sum(losses)
    avg_w = (gross_w / len(wins)) if wins else 0.0
    avg_l = (gross_l / len(losses)) if losses else 0.0
    return {
        "n": n, "expectancy_pct": round(sum(rs) / n, 4),
        "profit_factor": round(gross_w / gross_l, 2) if gross_l else None,
        "payoff_ratio": round(avg_w / avg_l, 2) if avg_l else None,
        "win_rate_pct": round(100.0 * len(wins) / n, 1),
        "status": "VALIDATED candidate (n>=30)" if n >= 30 else "DESCRIPTIVE (n<30)",
    }


def head_to_head(v2_closed: List[Dict], current_closed: List[Dict], n_haircut=HAIRCUT_N) -> Dict:
    """FORWARD head-to-head: screener_v2 vs current engine. Never blends with historical."""
    v2, cur = _stats(v2_closed), _stats(current_closed)
    both_ready = (v2["n"] >= 30 and cur["n"] >= 30)
    lift = None; verdict = "ACCRUING — keep logging (need n>=30 both sides)"
    if v2["expectancy_pct"] is not None and cur["expectancy_pct"] is not None:
        lift = round(v2["expectancy_pct"] - cur["expectancy_pct"], 4)
        if both_ready:
            haircut_lift = round(lift / n_haircut, 4)
            if haircut_lift > 0:
                verdict = f"v2 LEADS (+{lift} pts gross, +{haircut_lift} after /{n_haircut} haircut) — eligible for go-review"
            else:
                verdict = f"current LEADS or tie (lift {lift}, /{n_haircut} = {haircut_lift}) — v2 stays SHADOW"
        else:
            verdict = f"ACCRUING — gross lift {lift} but n<30 (v2 {v2['n']}, current {cur['n']}); DESCRIPTIVE, not actionable"
    return {
        "kind": "screener_v2_vs_current_forward", "basis": "FORWARD only · expectancy-led · win% footnote",
        "screener_v2": v2, "current_engine": cur, "gross_expectancy_lift_pct": lift,
        "haircut_N": n_haircut, "both_n_ge_30": both_ready, "verdict": verdict,
        "promotion_rule": "v2 -> live ONLY on n>=30 forward beat + haircut + explicit go. Else SHADOW.",
        "review_line": _review_line(v2, cur, verdict),
    }


def _review_line(v2, cur, verdict) -> str:
    fmt = lambda s: ("exp " + ("+" if (s["expectancy_pct"] or 0) >= 0 else "") +
                     str(s["expectancy_pct"]) + "%") if s["expectancy_pct"] is not None else "exp n/a"
    return (f"screener_v2 vs current engine — v2 n={v2['n']} ({fmt(v2)}), "
            f"current n={cur['n']} ({fmt(cur)}) · {verdict}")


def _selftest():
    # day-0: no closed trades -> ACCRUING
    h0 = head_to_head([], [])
    assert h0["screener_v2"]["n"] == 0 and "ACCRUING" in h0["verdict"]
    # n<30 both -> DESCRIPTIVE, not actionable even if v2 looks better
    v2 = [{"return_pct": x} for x in [3, -1, 4, -1, 5]]
    cur = [{"return_pct": x} for x in [-2, -1, 1, -3, 0]]
    h1 = head_to_head(v2, cur)
    assert "ACCRUING" in h1["verdict"] and h1["gross_expectancy_lift_pct"] > 0
    # n>=30 both, v2 better -> eligible (lift survives /6)
    import math
    v2b = [{"return_pct": 2.0} for _ in range(30)]
    curb = [{"return_pct": -1.0} for _ in range(30)]
    h2 = head_to_head(v2b, curb)
    assert h2["both_n_ge_30"] and "v2 LEADS" in h2["verdict"]
    # record_pick produces a ledger row with outcome unset
    row = record_pick({"ticker": "X", "pivot": 10.0, "base_depth_pct": 12.0,
                       "stage_pass": {"s1": True}}, "2026-06-28")
    assert row["outcome"] is None and set(LEDGER_FIELDS) == set(row.keys())
    print("SELF-TEST PASS — day0 ACCRUING, n<30 DESCRIPTIVE, n>=30 beat eligible, ledger row well-formed")
    print("day-0 review line:", h0["review_line"])

if __name__ == "__main__":
    _selftest()
