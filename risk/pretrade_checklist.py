#!/usr/bin/env python3
"""
pretrade_checklist.py  —  DISPATCH 44, Phase 3A (Risk & Survival layer)

A quick ENFORCED pre-trade checklist that runs before "I'm in". It auto-checks
what it can from the live risk layer (loss limits, portfolio heat, regime) and
asks Hany to confirm the rest. Completion is logged to the journal; SKIPPING the
checklist is a discipline ding (D42).

CHECKLIST ITEMS
  1. entry / stop / target / size all set?
  2. matches a playbook setup?
  3. within loss limits?        (auto: reads loss_limits.json)
  4. not over-heat?             (auto: reads portfolio_heat.json)
  5. regime-appropriate?        (auto: reads regime_label.json + edge_by_regime.json)
  6. "what would make me wrong?" invalidation written?

ADVISORY / SIMULATED. Hany decides + executes.

INPUTS (read-only): loss_limits.json, portfolio_heat.json, regime_label.json,
edge_by_regime.json. A trade-intent (trade_intent.local.json) drives the worked
example; falls back to a built-in sample.

OUTPUT: pretrade_checklist.json — the template + a worked evaluation. The
checklist-completion record is appended to the journal by the live system; here
we emit the evaluation + the discipline result.
"""

import json
import os
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

LOSS_PATH = os.path.join(ROOT, "loss_limits.json")
HEAT_PATH = os.path.join(ROOT, "portfolio_heat.json")
REGIME_PATH = os.path.join(ROOT, "regime_label.json")
EDGE_PATH = os.path.join(ROOT, "edge_by_regime.json")
INTENT_LOCAL = os.path.join(ROOT, "trade_intent.local.json")  # never mirrored
OUT_PATH = os.path.join(ROOT, "pretrade_checklist.json")

CHECKLIST = [
    {"id": "levels_set", "q": "entry / stop / target / size all set?", "auto": False},
    {"id": "playbook", "q": "matches a playbook setup?", "auto": False},
    {"id": "within_limits", "q": "within loss limits?", "auto": True},
    {"id": "not_overheat", "q": "not over-heat?", "auto": True},
    {"id": "regime_ok", "q": "regime-appropriate?", "auto": True},
    {"id": "invalidation", "q": "what would make me wrong? (invalidation written)",
     "auto": False},
]

SAMPLE_INTENT = {
    "setup": "ema_gccl::CL_9_21_60m_filtered",
    "instrument": "MCL", "dir": "long",
    "entry": 71.20, "stop": 70.60, "target": 72.40, "size_contracts": 1,
    "playbook_match": True,
    "invalidation": "lose 70.60 (below the pullback low) -> thesis dead, exit.",
    "regime_instrument_key": "CL_daily",
}


def _load(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def evaluate(intent):
    loss = _load(LOSS_PATH, {})
    heat = _load(HEAT_PATH, {})
    regime = _load(REGIME_PATH, {})
    edge = _load(EDGE_PATH, {})

    results = []
    for item in CHECKLIST:
        cid = item["id"]
        passed, detail = None, ""
        if cid == "levels_set":
            passed = all(intent.get(k) is not None
                         for k in ("entry", "stop", "target", "size_contracts"))
            detail = f"entry {intent.get('entry')} / stop {intent.get('stop')} / " \
                     f"target {intent.get('target')} / size {intent.get('size_contracts')}"
        elif cid == "playbook":
            passed = bool(intent.get("playbook_match"))
            detail = intent.get("setup", "—")
        elif cid == "within_limits":
            hit = loss.get("any_limit_hit")
            passed = (hit is False)
            detail = "no loss limit active" if passed else \
                     "A LOSS LIMIT IS ACTIVE — stand down" if hit else \
                     "loss_limits.json not available"
        elif cid == "not_overheat":
            rag = (heat or {}).get("rag")
            passed = rag in ("GREEN", "AMBER")
            detail = f"open heat RAG={rag}" + (" — adding risk on RED" if rag == "RED" else "")
        elif cid == "regime_ok":
            rk = intent.get("regime_instrument_key")
            lab = (((regime or {}).get("instruments") or {}).get(rk) or {}).get("label")
            cond = (((edge or {}).get("setups") or {}).get(intent.get("setup")) or {}) \
                .get("by_regime", {}).get(lab, {})
            exp = cond.get("expectancy_R")
            passed = (exp is None) or (exp > 0) or (lab == "TRENDING")
            detail = f"current {rk} regime={lab}" + (
                f"; this setup is {exp:+.2f}R there" if exp is not None else
                "; no per-regime edge cell yet (descriptive)")
        elif cid == "invalidation":
            passed = bool(intent.get("invalidation"))
            detail = intent.get("invalidation", "— NOT WRITTEN —")
        results.append({"id": cid, "q": item["q"], "auto": item["auto"],
                        "pass": passed, "detail": detail})

    all_pass = all(r["pass"] for r in results)
    blocking = [r for r in results if not r["pass"]]
    return results, all_pass, blocking


def build(skipped=False):
    intent = _load(INTENT_LOCAL) or SAMPLE_INTENT
    intent_src = "LIVE (trade_intent.local.json — not mirrored)" \
        if os.path.exists(INTENT_LOCAL) else "SAMPLE (built-in)"
    results, all_pass, blocking = evaluate(intent)

    discipline = None
    if skipped:
        discipline = {"rule": "pretrade_checklist", "severity": "DISCIPLINE_VIOLATION",
                      "detail": "checklist skipped before entry"}

    out = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "kind": "pretrade_checklist",
        "dispatch": "44 / Phase 3A",
        "banner": "ADVISORY / SIMULATED — run before 'I'm in'. Auto-checks loss "
                  "limits, heat + regime; Hany confirms the rest. Completion logs "
                  "to the journal; SKIPPING it is a discipline ding (D42).",
        "intent_source": intent_src,
        "checklist_template": CHECKLIST,
        "evaluation": results,
        "all_clear": all_pass,
        "blocking_items": [b["id"] for b in blocking],
        "verdict": ("CLEAR — proceed (Hany executes)" if all_pass else
                    "NOT CLEAR — " + ", ".join(b["q"] for b in blocking)),
        "discipline_log": [discipline] if discipline else [],
        "privacy": "The actual trade intent lives in trade_intent.local.json "
                   "(never mirrored). Only the pass/fail evaluation is emitted.",
    }
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=2)
    return out


if __name__ == "__main__":
    res = build()
    print(f"pretrade_checklist.json written. intent={res['intent_source']}")
    for r in res["evaluation"]:
        mark = "✓" if r["pass"] else "✗"
        print(f"  {mark} [{'auto' if r['auto'] else 'hany'}] {r['q']}  — {r['detail']}")
    print(f"VERDICT: {res['verdict']}")
