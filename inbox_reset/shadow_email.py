#!/usr/bin/env python3
"""
inbox_reset/shadow_email.py — D114 SHADOW TRAINING MODE email formatter.

Turns D114's shadow emails ON but CLEARLY MARKED and still NOT validated. This is
the presentation seam that wraps the frozen sentinel Decision + Candidate; it is
decoupled (takes a plain 'decision record' dict) so it self-tests here without the
sentinel/ package (which lives on PR #20's branch). Integration: in
sentinel/shadow_run.py, replace the EMAIL_ENABLED=False no-op with a call to
render_fire() for qualified decisions and collect suppressed rows for the 16:15
near-miss digest. The [SHADOW] tag comes off only after the real-data re-run.

Guardrails implemented (dispatch Part 3):
  1. Subject prefix, mandatory: "[SHADOW—NOT VALIDATED] {CARD} {LONG|SHORT} @ {level}".
     NEVER "TRADE:" — that prefix is reserved for post-validation.
  2. Body = reasoning, not just numbers: Card / Location / Event / Gates / Risk /
     megacap + RSP-SPY. Footer: "--- YOUR CHECK: location? event complete? flow agreeing? ---".
  3. Near-miss digest, ONE email 16:15: every setup that ARMED but was SUPPRESSED,
     with the SPECIFIC gate that killed it.
  4. Outcome line on every fire AND near-miss: triple-barrier over the next 30/60 min.
  5. Everything still logs to ledgers/sentinel_forward.csv. Still NOT validated.

Run:  python3 inbox_reset/shadow_email.py --selftest
      python3 inbox_reset/shadow_email.py --sample     # T3: one fire + one digest
"""
from __future__ import annotations
from typing import Dict, List, Optional
import argparse

SHADOW_PREFIX = "[SHADOW—NOT VALIDATED]"
FOOTER = "--- YOUR CHECK: location? event complete? flow agreeing? ---"


# ── numeric helpers ───────────────────────────────────────────────────────────
def _r_multiple(entry: float, stop: float, target: float) -> Optional[float]:
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    return round(abs(target - entry) / risk, 2)


def _min_stop(atr5m: float, invalidating_extreme: float, direction: str, mult: float = 1.5) -> float:
    pad = mult * atr5m
    return round(invalidating_extreme + pad, 2) if direction == "SHORT" else round(invalidating_extreme - pad, 2)


def triple_barrier(direction: str, entry: float, stop: float, t1: float,
                   bars: List[Dict]) -> Dict:
    """Minimal triple-barrier over a list of {high,low} bars (chronological).
    Returns {barrier, R, bars_to}. Stop checked before target within a bar (conservative)."""
    risk = abs(entry - stop)
    for i, b in enumerate(bars, 1):
        hi, lo = b["high"], b["low"]
        if direction == "SHORT":
            if hi >= stop:
                return {"barrier": "STOP", "R": round(-abs(entry - stop) / risk, 2) if risk else None, "bars_to": i}
            if lo <= t1:
                return {"barrier": "T1", "R": round((entry - t1) / risk, 2) if risk else None, "bars_to": i}
        else:
            if lo <= stop:
                return {"barrier": "STOP", "R": round(-abs(entry - stop) / risk, 2) if risk else None, "bars_to": i}
            if hi >= t1:
                return {"barrier": "T1", "R": round((t1 - entry) / risk, 2) if risk else None, "bars_to": i}
    last = bars[-1] if bars else None
    if last is None:
        return {"barrier": "NONE", "R": None, "bars_to": 0}
    close = (last["high"] + last["low"]) / 2.0
    r = ((entry - close) if direction == "SHORT" else (close - entry)) / risk if risk else None
    return {"barrier": "TIME", "R": round(r, 2) if r is not None else None, "bars_to": len(bars)}


def outcome_line(rec: Dict) -> str:
    """Triple-barrier over the next 30/60 min. Fires WITHOUT outcomes teach nothing."""
    o = rec.get("outcome")
    if not o:
        return "Outcome  : (pending — nightly labeler stamps 30/60-min triple-barrier)"
    def leg(key):
        d = o.get(key)
        if not d:
            return "n/a"
        rr = d.get("R")
        return f"{d.get('barrier','?')}" + (f" {rr:+.2f}R" if isinstance(rr, (int, float)) else "")
    return f"Outcome  : 30m {leg('m30')} | 60m {leg('m60')} (triple-barrier)"


# ── suppression-reason -> human, with the SPECIFIC killing gate ────────────────
def humanize_suppression(rec: Dict) -> str:
    if rec.get("suppression_detail"):
        return rec["suppression_detail"]
    code = rec.get("suppression_reason", "") or ""
    sa, sv, st = rec.get("add_slope"), rec.get("vold_slope"), rec.get("trin_slope")
    div = rec.get("divergence")
    m = {
        "WINDOW": "outside window (09:35–11:30 / 14:00–15:15 ET)",
        "SLOPE:ADD_FLAT": "ADD slope FLAT (<10% of level)",
        "SLOPE:DIRECTION": f"slope disagrees (ADD {sa}, VOLD {sv}, TRIN {st})",
        "DIV:BELOW_FLOOR": f"ADD delta {div} < max(150-issue, 10%|ADD|) floor",
        "DEBOUNCE": "duplicate level this session (±3 pts)",
        "DAILY_CAP": "daily cap (2/day) already met",
        "UNRELIABLE:ROWS": "feed too thin (<15 rows) — slopes unreliable",
        "UNRELIABLE:FEED_AGE": "feed age >120s — slopes unreliable",
    }
    for k, v in m.items():
        if code.startswith(k):
            return v
    if code.startswith("EVENT:"):
        return f"event not complete ({code.split(':',1)[1].lower()})"
    if code.startswith("RISK:"):
        return f"risk floor ({code.split(':',1)[1].lower()})"
    return code or "suppressed"


# ── context line ──────────────────────────────────────────────────────────────
def _ctx_line(rec: Dict) -> str:
    mc = rec.get("megacap_pct", {}) or {}
    rs = rec.get("rsp_spy", {}) or {}
    mcv = mc.get("value")
    mc_s = f"{mcv:+.2f}%" if isinstance(mcv, (int, float)) else f"n/a ({mc.get('status','?')})"
    ratio = rs.get("ratio")
    rs_s = f"{ratio:.5f}" if isinstance(ratio, (int, float)) else f"n/a ({rs.get('status','?')})"
    return f"megacap {mc_s} | RSP/SPY {rs_s}  (context — megacap is NOT a gate)"


# ── event line — state WHICH completion evidence ──────────────────────────────
def _event_line(rec: Dict) -> str:
    ev = rec.get("event", {}) or {}
    setup = rec.get("setup", "")
    if setup == "Cluster Fade":
        tagged = ev.get("pool_tagged")
        rej = ev.get("rejected_within_bars")
        return (f"sweep/pool tagged: {'YES' if tagged else 'NO'}; "
                f"rejection ≤3 bars: {'YES ('+str(rej)+' bars)' if rej is not None else 'NO'}")
    if setup == "Failed Retest":
        bc = ev.get("boundary_close_beyond_pts")
        rt = ev.get("retested")
        return (f"boundary close ≥1pt beyond: {'YES ('+str(bc)+' pts)' if bc else 'NO'}; "
                f"retest: {'YES' if rt else 'NO'}")
    if setup == "Washout Reclaim":
        rb = ev.get("washout_reclaim_bars")
        return f"TICK≤−900 at support + reclaim ≤3 bars: {'YES ('+str(rb)+' bars)' if rb is not None else 'NO'}"
    if setup == "Pullback-Hold":
        rej = ev.get("rejected_within_bars")
        return f"held the level (rejection ≤3 bars): {'YES ('+str(rej)+' bars)' if rej is not None else 'NO'}"
    return ev.get("detail", "—")


# ── fire email ────────────────────────────────────────────────────────────────
def shadow_subject(rec: Dict) -> str:
    return f"{SHADOW_PREFIX} {rec['setup']} {rec['dir']} @ {rec['level']:g}"


def shadow_body(rec: Dict) -> str:
    entry, stop, t1 = rec["entry"], rec["stop"], rec["t1"]
    atr = rec.get("atr5m", 0.0)
    inval = rec.get("invalidating_extreme", stop)
    min_stop = _min_stop(atr, inval, rec["dir"])
    rr = _r_multiple(entry, stop, t1)
    sa, sv, st = rec.get("add_slope"), rec.get("vold_slope"), rec.get("trin_slope")
    verdict = "QUALIFIED (all Part-1 gates pass)" if rec.get("qualified") else "SUPPRESSED"
    lines = [
        f"Card     : {rec['setup']} {rec['dir']}",
        f"Location : {rec.get('level_name','level')} @ {rec['level']:g} — {rec.get('why','named decision level')}",
        f"Event    : {_event_line(rec)}",
        f"Gates    : ADD slope {sa} | VOLD slope {sv} | TRIN slope {st}  => {verdict}",
        f"Risk     : ATR(5m) {atr:.2f}; min stop (1.5x beyond {inval:g}) {min_stop:g}; "
        f"proposed stop {stop:g}; entry {entry:g} -> T1 {t1:g}  R:R {rr if rr is not None else 'n/a'}",
        f"Context  : {_ctx_line(rec)}",
        outcome_line(rec),
        "",
        FOOTER,
        "SHADOW — reasoning artifact, NOT validated, NOT a trade. Logs to sentinel_forward.csv.",
    ]
    return "\n".join(lines)


def render_fire(rec: Dict) -> Dict:
    return {"subject": shadow_subject(rec), "body": shadow_body(rec)}


# ── near-miss digest (one email, 16:15) ───────────────────────────────────────
def near_miss_digest(suppressed: List[Dict], date: str) -> Dict:
    subject = f"{SHADOW_PREFIX} NEAR-MISS DIGEST {date} — {len(suppressed)} armed & suppressed"
    header = ("Every setup that ARMED but was SUPPRESSED today, with the SPECIFIC gate that "
              "killed it + what price then did (triple-barrier). Primary teaching artifact.\n")
    blocks = [header]
    if not suppressed:
        blocks.append("(none armed today)")
    for rec in suppressed:
        line = (f"{rec.get('ts','--:--')} {rec['setup']} {rec['level']:g} "
                f"{rec.get('dir','')} — SUPPRESSED: {humanize_suppression(rec)}.")
        blocks.append(line)
        blocks.append("   " + outcome_line(rec).replace("Outcome  : ", "then: "))
    blocks.append("")
    blocks.append(FOOTER)
    blocks.append("SHADOW — NOT validated. Logs to sentinel_forward.csv.")
    return {"subject": subject, "body": "\n".join(blocks)}


# ── self-test / sample (T3) ───────────────────────────────────────────────────
def _sample_fire() -> Dict:
    rec = {
        "ts": "10:49", "date": "2026-08-11", "setup": "Cluster Fade", "dir": "SHORT",
        "level": 7617.0, "level_name": "cluster VP-POC (Tammy 7618 shelf)",
        "why": "prior-day POC + Tammy resistance shelf; swept then rejected",
        "entry": 7617.0, "stop": 7627.0, "t1": 7601.0, "t2": 7589.0,
        "invalidating_extreme": 7620.0, "atr5m": 4.0,
        "add_slope": -8.1, "vold_slope": -4.2e6, "trin_slope": 0.03, "divergence": 600.0,
        "event": {"pool_tagged": True, "rejected_within_bars": 2},
        "qualified": True, "suppression_reason": "",
        "megacap_pct": {"value": -0.42, "status": "OK"},
        "rsp_spy": {"ratio": 0.24310, "status": "OK"},
        "outcome": {"m30": {"barrier": "T1", "R": 1.6}, "m60": {"barrier": "T1", "R": 1.6}},
    }
    return render_fire(rec)


def _sample_digest() -> Dict:
    suppressed = [
        {"ts": "11:26", "setup": "Cluster Fade", "dir": "SHORT", "level": 7606.25,
         "suppression_detail": "ADD delta 15 < 150-issue floor; VOLD rising",
         "outcome": {"m30": {"barrier": "STOP", "R": -1.0}, "m60": {"barrier": "TIME", "R": -0.6}}},
        {"ts": "09:32", "setup": "Cluster Fade", "dir": "SHORT", "level": 7618.0,
         "suppression_reason": "WINDOW",
         "outcome": {"m30": {"barrier": "TIME", "R": 0.2}, "m60": {"barrier": "TIME", "R": -0.1}}},
        {"ts": "14:05", "setup": "Failed Retest", "dir": "LONG", "level": 7690.0,
         "suppression_reason": "SLOPE:DIRECTION", "add_slope": -3.0, "vold_slope": -1.1e6, "trin_slope": 0.02,
         "outcome": {"m30": {"barrier": "STOP", "R": -1.0}, "m60": {"barrier": "STOP", "R": -1.0}}},
    ]
    return near_miss_digest(suppressed, "2026-08-11")


def _selftest() -> int:
    fails = 0

    def check(name, cond):
        nonlocal fails
        print(f"  {'PASS' if cond else 'FAIL'}  {name}")
        if not cond:
            fails += 1

    f = _sample_fire()
    check("subject carries [SHADOW—NOT VALIDATED]", f["subject"].startswith(SHADOW_PREFIX))
    check("subject NEVER uses TRADE:", "TRADE:" not in f["subject"])
    check("subject has CARD DIR @ level", "Cluster Fade SHORT @ 7617" in f["subject"])
    for sec in ["Card", "Location", "Event", "Gates", "Risk", "Context", "Outcome"]:
        check(f"body has {sec} section", f"{sec}" in f["body"])
    check("body has YOUR CHECK footer", FOOTER in f["body"])
    check("fire has an outcome (not pending)", "30m T1" in f["body"])
    check("R:R present", "R:R" in f["body"])

    d = _sample_digest()
    check("digest is ONE email w/ SHADOW prefix", d["subject"].startswith(SHADOW_PREFIX))
    check("digest names the killing gate (ADD delta)", "ADD delta 15 < 150-issue floor" in d["body"])
    check("digest maps WINDOW suppression", "outside window" in d["body"])
    check("digest maps SLOPE:DIRECTION", "slope disagrees" in d["body"])
    check("every near-miss has an outcome line", d["body"].count("then:") == 3)

    tb = triple_barrier("SHORT", 7617.0, 7627.0, 7601.0,
                        [{"high": 7615, "low": 7599}])
    check("triple_barrier T1 for short", tb["barrier"] == "T1" and tb["R"] == 1.6)

    print(f"\nshadow_email self-test: {'ALL PASS' if fails == 0 else str(fails) + ' FAILED'}")
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--sample", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(1 if _selftest() else 0)
    if a.sample:
        f = _sample_fire()
        print("=== SHADOW FIRE ===\nSubject: " + f["subject"] + "\n\n" + f["body"])
        d = _sample_digest()
        print("\n\n=== NEAR-MISS DIGEST (16:15) ===\nSubject: " + d["subject"] + "\n\n" + d["body"])
        raise SystemExit(0)
    ap.print_help()
    raise SystemExit(2)


if __name__ == "__main__":
    main()
