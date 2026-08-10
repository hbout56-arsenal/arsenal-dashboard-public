#!/usr/bin/env python3
"""
inbox_reset/verify_suspensions.py — T2: confirm every suspended job is INERT
(no email on its next scheduled fire) and every KEPT job is untouched.

Mechanism modelled: every sender reads alert_prefs.json; enabled=false SUPPRESSES
the source (no email). feed_watchdog is email-suspended but keeps logging (gate left
enabled on purpose). The Mac-local senders (setup_sentinel, candle_pattern_alert) are
not in the in-repo gate; their inertness is asserted from alert_suspensions.json
(dated reversible flag -> SUSPENDED/unloaded).

Run:  python3 inbox_reset/verify_suspensions.py        # exit 0 if all inert as intended
"""
from __future__ import annotations
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def load(name):
    with open(os.path.join(ROOT, name)) as fh:
        return json.load(fh)


def would_email(prefs, source_id):
    """Mirror alert_prefs.py: a sender emits only if its gate is enabled (default on)."""
    node = prefs.get(source_id, {})
    return bool(node.get("enabled", True)) and bool(prefs.get("_all", {}).get("enabled", True))


def main():
    prefs = load("alert_prefs.json")
    registry = {s["id"]: s for s in load("alert_registry.json")["sources"]}
    susp = {s["id"]: s for s in load("alert_suspensions.json")["suspensions"]}
    fails = 0

    def check(name, cond):
        nonlocal fails
        print(f"  {'PASS' if cond else 'FAIL'}  {name}")
        if not cond:
            fails += 1

    print("T2 — suspended jobs are INERT on next fire:")
    # 1. arsenal_alerts / orb_intraday — gated OFF in-repo => no email.
    check("orb_intraday (arsenal_alerts) gate enabled=false", would_email(prefs, "orb_intraday") is False)
    check("orb_intraday registry on_now=false", registry["orb_intraday"]["on_now"] is False)

    # 2. feed_watchdog — EMAIL suspended, LOG kept (gate deliberately left enabled).
    fw = susp["feed_watchdog"]
    check("feed_watchdog email suspended (scope=email_only)",
          registry["feed_watchdog"]["suspended_2026-08-10"]["scope"] == "email_only")
    check("feed_watchdog logging KEPT", registry["feed_watchdog"]["suspended_2026-08-10"]["log_kept"] is True)

    # 3. Mac-local senders — recorded SUSPENDED (unloaded) with prior state preserved.
    for jid in ("setup_sentinel", "candle_pattern_alert"):
        s = susp[jid]
        check(f"{jid} recorded SUSPENDED", "SUSPEND" in s["action"].upper()
              and str(s.get("new_state", "")).upper().startswith("SUSPENDED"))
        check(f"{jid} prior_state preserved (reversible)", bool(s.get("prior_state")) and s.get("reversible") is True)

    print("\nKEPT-UNCHANGED jobs still emit / run (must NOT be silenced):")
    for jid in ("stocks_curated", "ict_killzone", "inside_bar", "ema_gccl", "ema_stocks", "fvg", "ict_offwindow"):
        check(f"{jid} still enabled", would_email(prefs, jid) is True)
    check("ema_es remains OFF (pre-existing, not part of this dispatch)", would_email(prefs, "ema_es") is False)

    print(f"\nT2 verify_suspensions: {'ALL PASS' if fails == 0 else str(fails) + ' FAILED'}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
