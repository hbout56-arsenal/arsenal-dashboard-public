#!/usr/bin/env python3
"""
sentinel/mgc_inside_bar_scorecard_publisher.py — PUBLIC scorecard projector (SHADOW)

Projects the PRIVATE forward ledger down to a PUBLIC summary scorecard. This is the
only MGC-inside-bar artifact that belongs in the public dashboard repo: it carries
n / expectancy / CI / gate / kill-criteria state / generated_at and NOTHING else —
no rule, no per-trade rows. Mirrors es_swing_scorecard.json.

PUBLIC/PRIVATE split (do not violate):
  - It NEVER reads a ledger from the public repo. The ledger path comes from
    $MGC_IB_LEDGER or --ledger, defaulting to the PRIVATE Mac home
    ~/arsenal/ledgers/mgc_inside_bar_forward.csv.
  - If the ledger is ABSENT it publishes n=0 / ACCRUING / not-yet-armed rather than
    erroring (that is the honest pre-arm state).
  - Output `rows` is ALWAYS [] — per-trade rows stay private.

Scoring/gates come from mgc_inside_bar_scorer (the shared scorer that also serves the
private mes_event_labels track). Self-tested; not loaded by any live path.
"""
from __future__ import annotations
from typing import Dict, Optional
import os, sys, json, datetime as dt

# shared scorer lives beside this file (moves private with the rest of the code)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mgc_inside_bar_scorer import (  # noqa: E402
    score_csv, IN_SAMPLE_EXP, VALIDATION_EXP_FLOOR, KILL_MAXDD, MIN_N,
)

DEFAULT_LEDGER = os.path.expanduser("~/arsenal/ledgers/mgc_inside_bar_forward.csv")  # PRIVATE
DEFAULT_OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "mgc_inside_bar_scorecard.json")  # public dashboard repo root
BOOK = "MGC-INSIDE-BAR (GC_RAW forward · daily · micro gold)"
HONESTY = (
    "FORWARD-ONLY, no backfill. DETECTION-ONLY / NON-VOTING / SHADOW — never sized. "
    "In-sample GC_RAW (exp +63.67, n=71) lived through a SINGLE gold bull regime and is "
    "suspected regime capture; this test earns it forward. Gate = pre-registered: nothing "
    "is VALIDATED until n>=30 AND bootstrap CI (1500x net points) excludes 0 AND forward "
    "expectancy >= 50% of in-sample (>= 31.835). KILL on negative expectancy at n>=30 or "
    "max drawdown < 2x in-sample (-441.6) -> retired as regime-capture confirmation, not "
    "'needs tuning.' Rule + per-trade rows are PRIVATE; this file is summary-only."
)


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _is_armed() -> bool:
    """True only if the detector's own guard is flipped on the Mac. Absent/unreadable
    detector (e.g. trimmed public checkout) => not armed."""
    try:
        from mgc_inside_bar_sentinel import ENABLED  # noqa: E402
        return bool(ENABLED)
    except Exception:
        return False


def build_scorecard(ledger_path: str = DEFAULT_LEDGER, now_iso: Optional[str] = None,
                    start_date: Optional[str] = None) -> Dict:
    """Project the ledger to the public summary scorecard (summary-only, rows=[])."""
    s = score_csv(ledger_path)                    # ACCRUING/n=0 if the ledger is absent
    n_closed = s.get("n_closed", 0)
    killed = s.get("gate") == "KILLED"
    armed = _is_armed()
    gate = s.get("gate", "DESCRIPTIVE")
    if n_closed == 0:
        gate_str = "DESCRIPTIVE — n<30 (ACCRUING, not yet armed)" if not armed \
                   else "DESCRIPTIVE — n<30 (ACCRUING)"
    elif gate == "VALIDATED":
        gate_str = "VALIDATED — n>=30, CI excludes 0, exp>=50% in-sample"
    elif gate == "KILLED":
        gate_str = "KILLED — kill criterion hit; track RETIRED"
    else:
        gate_str = f"DESCRIPTIVE — n<30" if n_closed < MIN_N else "DESCRIPTIVE — edge unconfirmed"
    return {
        "generated_at": now_iso or _now_iso(),
        "book": BOOK,
        "metric": "net_points",
        "n_scoreable": n_closed,
        "n_total": s.get("n_armed", 0),
        "win_rate": s.get("win_rate_pct"),
        "expectancy_pts": s.get("expectancy"),
        "exp_ci": s.get("boot_ci") or [None, None],
        "ci_excludes_0": bool(s.get("ci_excludes_0", False)),
        "VALIDATED": gate == "VALIDATED",
        "gate": gate_str,
        "kill_state": "KILLED" if killed else "not-triggered",
        "kill_criteria": {
            "neg_expectancy_at_n_ge_30": bool(s.get("expectancy") is not None
                                              and s["expectancy"] < 0 and n_closed >= MIN_N),
            "max_dd_breach": bool(s.get("max_dd") is not None and s["max_dd"] < KILL_MAXDD),
            "max_dd": s.get("max_dd"),
            "kill_max_dd": KILL_MAXDD,
        },
        "armed": armed,
        "start_date": start_date,
        "in_sample_expectancy": IN_SAMPLE_EXP,
        "validation_floor": round(VALIDATION_EXP_FLOOR, 4),
        "min_n": MIN_N,
        "honesty": HONESTY,
        "rows": [],   # ALWAYS empty in public — per-trade rows are private
    }


def publish(ledger_path: str = DEFAULT_LEDGER, out_path: str = DEFAULT_OUT,
            start_date: Optional[str] = None) -> str:
    card = build_scorecard(ledger_path, start_date=start_date)
    with open(out_path, "w") as fh:
        json.dump(card, fh, indent=1)
        fh.write("\n")
    return out_path


# ------------------------------------------------------------------ selftest
def _selftest() -> None:
    import tempfile, csv
    from mgc_inside_bar_sentinel import LEDGER_FIELDS

    # (1) ABSENT ledger -> n=0 / ACCRUING / not-armed, rows empty, no error
    card = build_scorecard("/nonexistent/path/mgc_inside_bar_forward.csv",
                           now_iso="2026-07-15T00:00:00+00:00")
    assert card["n_scoreable"] == 0 and card["n_total"] == 0
    assert card["armed"] is False and card["rows"] == []
    assert "ACCRUING" in card["gate"] and card["VALIDATED"] is False
    assert card["kill_state"] == "not-triggered"

    # (2) summary-only: NO rule/per-trade keys ever leak into the public card
    banned = {"entry_trigger", "long_trigger", "short_trigger", "stop", "target",
              "bar_definition", "session_filter", "timeframe_rule", "price"}
    assert not (banned & set(card.keys())), "rule/per-trade field leaked to public card"
    blob = json.dumps(card)
    assert "trigger" not in blob.lower() or "entry_trigger" not in blob  # no trigger rule text
    assert card["rows"] == []

    # (3) with a closed private ledger -> stats populate, rows STILL empty
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "led.csv")
        with open(p, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=LEDGER_FIELDS)
            w.writeheader()
            for i in range(4):
                r = {k: "" for k in LEDGER_FIELDS}
                r.update({"instrument": "MGC", "direction": "long",
                          "outcome": "target" if i % 2 == 0 else "stop",
                          "net_points": "50" if i % 2 == 0 else "-20"})
                w.writerow(r)
        card2 = build_scorecard(p, now_iso="2026-07-15T00:00:00+00:00")
        assert card2["n_scoreable"] == 4 and card2["expectancy_pts"] is not None
        assert card2["rows"] == [], "per-trade rows must never appear in the public card"
        assert card2["exp_ci"][0] is not None

    # (4) shape mirrors es_swing_scorecard.json core keys
    for k in ("generated_at", "book", "metric", "n_scoreable", "n_total", "win_rate",
              "expectancy_pts", "exp_ci", "ci_excludes_0", "VALIDATED", "gate", "honesty", "rows"):
        assert k in card, f"missing es_swing-mirrored key: {k}"

    print("mgc_inside_bar_scorecard_publisher selftest: OK (4 checks; summary-only, rows never leak)")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--selftest" in args:
        _selftest()
    else:
        ledger = os.environ.get("MGC_IB_LEDGER", DEFAULT_LEDGER)
        out = os.environ.get("MGC_IB_SCORECARD", DEFAULT_OUT)
        # optional: --ledger PATH / --out PATH / --start YYYY-MM-DD
        start = None
        if "--ledger" in args:
            ledger = args[args.index("--ledger") + 1]
        if "--out" in args:
            out = args[args.index("--out") + 1]
        if "--start" in args:
            start = args[args.index("--start") + 1]
        path = publish(ledger, out, start_date=start)
        print(f"wrote {path} (ledger={ledger}, exists={os.path.exists(ledger)})")
