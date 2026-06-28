#!/usr/bin/env python3
"""
loss_limits.py  —  DISPATCH 44, Phase 1B (Risk & Survival layer)

Pre-registered circuit breakers: daily stop, consecutive-loser limit, weekly
limit. ADVISORY + journal-enforced. This cannot force-flatten (Hany executes) —
it makes the rule LOUD (an alert + a dashboard banner) and logs breaches to the
discipline scorecard. This is the #1 thing that stops one bad day erasing a
month.

INPUTS (read-only)
------------------
- journal.local.json     the LIVE forward journal (D42). Gitignored, NEVER
                         mirrored. Falls back to journal.sample.json (synthetic)
                         for validation/demo when no live journal exists.
- account_summary.json   SIMULATED $15k paper equity (public) for the %->R/$ ref.
- loss_limits_config.local.json   OPTIONAL override of the default limits.

OUTPUT
------
- loss_limits.json       mirror-safe computed view: the registered limits,
                         today's + rolling status in R and % (NO real $),
                         breach flags, the alert payload, and the discipline log.

Reuses the alert convention from the existing alert system (alert_format.py in
the private tree); a minimal, convention-matching formatter is inlined here so
the public mirror is self-contained.
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timezone, date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

LIVE_JOURNAL = os.path.join(ROOT, "journal.local.json")          # never mirrored
SAMPLE_JOURNAL = os.path.join(HERE, "journal.sample.json")       # synthetic
ACCT_PATH = os.path.join(ROOT, "account_summary.json")
CONFIG_LOCAL = os.path.join(ROOT, "loss_limits_config.local.json")
OUT_PATH = os.path.join(ROOT, "loss_limits.json")

# ── sensible defaults (Hany-set; override via loss_limits_config.local.json) ──
DEFAULT_LIMITS = {
    "daily_stop_pct": -3.0,        # stop trading for the day at -3% equity ...
    "daily_stop_R": -2.0,          # ... or -2R, whichever comes first
    "consecutive_loser_limit": 2,  # 2 losers in a row -> stop
    "weekly_stop_pct": -6.0,       # -6% on the week -> halve size next week
}


def _load(path):
    with open(path) as f:
        return json.load(f)


def _iso_week(d):
    y, w, _ = date.fromisoformat(d).isocalendar()
    return f"{y}-W{w:02d}"


def alert(level, title, body, source="loss_limits"):
    """Convention-matching alert payload (mirrors alert_format.py)."""
    return {
        "source": source,
        "level": level,                 # INFO | WARN | CRITICAL
        "title": title,
        "body": body,
        "recipient": "hbout56@gmail.com (self-only)",
        "labels": ["SIMULATED", "ADVISORY", "cannot force-execute — Hany acts"],
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
    }


def evaluate(journal, limits, as_of=None):
    trades = journal.get("trades", [])
    if not trades:
        return None, [], []
    dates = sorted({t["date"] for t in trades})
    as_of = as_of or dates[-1]
    week = _iso_week(as_of)

    today = [t for t in trades if t["date"] == as_of]
    wk = [t for t in trades if _iso_week(t["date"]) == week]

    day_R = round(sum(t.get("pnl_R", 0) for t in today), 3)
    day_pct = round(sum(t.get("pnl_pct", 0) for t in today), 3)
    wk_R = round(sum(t.get("pnl_R", 0) for t in wk), 3)
    wk_pct = round(sum(t.get("pnl_pct", 0) for t in wk), 3)

    # consecutive losers within the day, in journal order
    max_consec = 0
    run = 0
    consec_after_limit = 0
    for t in today:
        if t.get("result") == "loss":
            run += 1
            max_consec = max(max_consec, run)
            if run > limits["consecutive_loser_limit"]:
                consec_after_limit += 1
        else:
            run = 0

    breaches = []
    alerts = []

    # daily stop
    daily_hit = day_pct <= limits["daily_stop_pct"] or day_R <= limits["daily_stop_R"]
    if daily_hit:
        msg = (f"DAILY LOSS LIMIT HIT — stop trading. Today {day_R}R / "
               f"{day_pct}% (limit {limits['daily_stop_R']}R / "
               f"{limits['daily_stop_pct']}%).")
        alerts.append(alert("CRITICAL", "DAILY LOSS LIMIT HIT — STOP", msg))
        breaches.append({"date": as_of, "rule": "daily_stop",
                         "detail": f"{day_R}R / {day_pct}%", "severity": "limit_hit"})

    # consecutive losers
    if max_consec >= limits["consecutive_loser_limit"]:
        msg = (f"CONSECUTIVE-LOSER LIMIT HIT — stop trading. {max_consec} losers "
               f"in a row (limit {limits['consecutive_loser_limit']}).")
        alerts.append(alert("CRITICAL", "CONSECUTIVE-LOSER LIMIT HIT — STOP", msg))
        breaches.append({"date": as_of, "rule": "consecutive_losers",
                         "detail": f"{max_consec} in a row",
                         "severity": "limit_hit"})
    if consec_after_limit > 0:
        # took trades AFTER the rule said stop -> discipline VIOLATION
        breaches.append({"date": as_of, "rule": "consecutive_losers",
                         "detail": f"{consec_after_limit} trade(s) taken after the "
                                   f"stop rule fired",
                         "severity": "DISCIPLINE_VIOLATION"})

    # weekly limit
    weekly_hit = wk_pct <= limits["weekly_stop_pct"]
    if weekly_hit:
        msg = (f"WEEKLY LOSS LIMIT HIT — halve size next week. Week {week}: "
               f"{wk_pct}% (limit {limits['weekly_stop_pct']}%).")
        alerts.append(alert("WARN", "WEEKLY LOSS LIMIT — HALVE SIZE NEXT WEEK", msg))
        breaches.append({"date": as_of, "rule": "weekly_stop",
                         "detail": f"{wk_pct}% on week {week}", "severity": "limit_hit"})

    status = {
        "as_of": as_of,
        "iso_week": week,
        "today": {
            "n_trades": len(today),
            "pnl_R": day_R, "pnl_pct": day_pct,
            "max_consecutive_losers": max_consec,
            "daily_limit_hit": daily_hit,
            "consecutive_limit_hit": max_consec >= limits["consecutive_loser_limit"],
        },
        "week": {
            "n_trades": len(wk), "pnl_R": wk_R, "pnl_pct": wk_pct,
            "weekly_limit_hit": weekly_hit,
            "next_week_action": "HALVE SIZE" if weekly_hit else "normal size",
        },
    }
    return status, alerts, breaches


def build(as_of=None):
    acct = _load(ACCT_PATH)
    sim_equity = float(acct.get("rules", {}).get("start_balance", 15000.0))

    limits = dict(DEFAULT_LIMITS)
    limits_source = "DEFAULT"
    if os.path.exists(CONFIG_LOCAL):
        try:
            limits.update(_load(CONFIG_LOCAL))
            limits_source = "LOCAL_override"
        except Exception:
            pass

    if os.path.exists(LIVE_JOURNAL):
        journal = _load(LIVE_JOURNAL)
        journal_source = "LIVE (journal.local.json — not mirrored)"
    else:
        journal = _load(SAMPLE_JOURNAL)
        journal_source = "SAMPLE (synthetic — no live journal present)"

    status, alerts, breaches = evaluate(journal, limits, as_of=as_of)

    out = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "kind": "loss_limits_circuit_breakers",
        "dispatch": "44 / Phase 1B",
        "banner": "ADVISORY / SIMULATED — these limits CANNOT force-flatten "
                  "(Hany executes). They make the rule loud + log every breach "
                  "to the discipline scorecard (D42). Breaking a loss limit IS a "
                  "discipline violation.",
        "journal_source": journal_source,
        "limits_source": limits_source,
        "registered_limits": limits,
        "equity_basis": "SIMULATED_paper_15k (%->R reference; no real $ mirrored)",
        "status": status,
        "alerts": alerts,
        "any_limit_hit": bool(alerts),
        "discipline_log": breaches,
        "privacy": "Live P&L lives in journal.local.json (never mirrored). Only "
                   "R-multiples, %s, breach flags + the alert text are emitted "
                   "here — no real $.",
    }
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=2)
    return out


if __name__ == "__main__":
    res = build()
    print(f"loss_limits.json written. journal={res['journal_source']}")
    s = res["status"]
    print(f"as_of {s['as_of']}  today {s['today']['pnl_R']}R / "
          f"{s['today']['pnl_pct']}%  consec_losers={s['today']['max_consecutive_losers']}")
    print(f"week {s['iso_week']}  {s['week']['pnl_R']}R / {s['week']['pnl_pct']}%  "
          f"next_week={s['week']['next_week_action']}")
    print(f"any_limit_hit={res['any_limit_hit']}")
    for a in res["alerts"]:
        print(f"  [{a['level']}] {a['title']} :: {a['body']}")
    print("discipline_log:")
    for b in res["discipline_log"]:
        print(f"  - {b['date']} {b['rule']} [{b['severity']}] {b['detail']}")
