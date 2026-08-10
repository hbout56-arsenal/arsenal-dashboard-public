#!/usr/bin/env python3
"""
build_trade_state.py  —  ONE SOURCE FOR EVERY DECISION PARAMETER
================================================================

Assembles ``trade_state.json`` on the dashboard mirror: a single JSON that
carries everything needed to make or reject a trade. It is the RUNTIME
RENDERING of the playbook — the doctrine doc stays the doctrine; this must
never diverge from it.

Design rules (mirror side of the MAC-LOCAL dispatch):

  * NO new decision logic. Every field READS from the published module that
    already owns it (verdict, ict_state, fvg_state, internals_snapshot,
    breadth_snapshot, calendar_context, prices_futures, regime_label,
    es_swing_*, es_bars_15m, tammy/tictoc levels, loss_limits, orb_futures).
    The two exceptions the dispatch explicitly authorises are computed from
    the SAME bars the ict/fvg engines use: the volume profile (read from
    ``es_bars_15m.vp`` when present, else built here) and ATR.
  * Every field carries provenance (``source`` path) + ``age_s``. Anything
    older than its freshness budget renders ``STALE`` — never a bare value.
    A feed with no fresh row renders ``DARK``. Missing-from-mirror fields are
    ``null`` with an explicit ``reason`` — nothing is ever fabricated.
  * If a value is owned by a Mac-side module that does not publish to this
    mirror (the intraday day-type classifier, the 30-row LSQ slope gates on
    the morning internals archive, the 5m ATR), the field says so in its
    ``reason`` instead of guessing. Honesty over coverage (D64: a frozen
    mirror once lied FRESH for a week — never again).

Run:  python3 build_trade_state.py            # writes ./trade_state.json
      python3 build_trade_state.py --check    # print + validate, no write
"""

import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))

# ----------------------------------------------------------------------------
# provenance-aware readers
# ----------------------------------------------------------------------------

_CACHE = {}


def load(name):
    """Read a published JSON, cached. Returns {} on missing/broken."""
    if name in _CACHE:
        return _CACHE[name]
    path = os.path.join(HERE, name)
    try:
        with open(path) as fh:
            _CACHE[name] = json.load(fh)
    except (OSError, ValueError):
        _CACHE[name] = None
    return _CACHE[name]


def parse_ts(val):
    """Parse an ISO-ish timestamp to an aware UTC datetime, or None."""
    if not val or not isinstance(val, str):
        return None
    s = val.strip().replace("Z", "+00:00")
    # tolerate a trailing " ET"/" UTC" tag
    for tag in (" ET", " UTC"):
        if s.endswith(tag):
            s = s[: -len(tag)].strip()
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # try a couple of loose formats
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(s.split(".")[0], fmt)
                break
            except ValueError:
                dt = None
        if dt is None:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def feed_ts(doc):
    """The real data-row time of a feed doc (pushed_at > generated_at)."""
    if not isinstance(doc, dict):
        return None
    for k in ("pushed_at", "latest_row_ts", "generated_at", "timestamp",
              "updated_ts", "_refreshed_at", "as_of"):
        dt = parse_ts(doc.get(k))
        if dt:
            return dt
    return None


def reference_now():
    """
    Reference clock for age math. On a live collector this is wall-clock;
    on the snapshot mirror we anchor to the NEWEST feed timestamp so the
    freshest feed reads ~0s and every staler feed shows its true lag. The
    basis is recorded in the output so a reader never mistakes it for live.
    """
    newest = None
    for name in FEED_FILES:
        dt = feed_ts(load(name))
        if dt and (newest is None or dt > newest):
            newest = dt
    return newest or datetime.now(timezone.utc)


NOW = None  # set in main()


def prov(source, doc, budget_s, extra=None):
    """
    Build a provenance envelope: source path, age, and a LIVE/STALE/DARK
    status derived from the feed's own timestamp vs the reference clock.
    """
    dt = feed_ts(doc) if isinstance(doc, dict) else None
    age = None if dt is None else int((NOW - dt).total_seconds())
    if dt is None:
        status = "DARK"
    elif budget_s is not None and age is not None and age > budget_s:
        status = "STALE"
    else:
        status = "LIVE"
    env = {"source": source, "age_s": age, "status": status,
           "budget_s": budget_s}
    if extra:
        env.update(extra)
    return env


def stale_str(status, age_s):
    if status == "DARK":
        return "DARK"
    if status == "STALE":
        if age_s is None:
            return "STALE"
        if age_s >= 86400:
            return f"STALE({age_s // 86400}d)"
        if age_s >= 3600:
            return f"STALE({age_s // 3600}h)"
        return f"STALE({age_s // 60}m)"
    return None


def fresh_value(value, env):
    """
    Wrap a value with provenance; if the feed is STALE/DARK the rendered
    label carries the honesty tag so no bare stale number leaks through.
    """
    tag = stale_str(env["status"], env.get("age_s"))
    return {"value": value, "render": (tag or value), **env}


# Feeds that participate in the reference-clock and freshness board.
FEED_FILES = [
    "verdict.json", "internals_snapshot.json", "breadth_snapshot.json",
    "es_bars_15m.json", "prices_futures.json", "ict_state.json",
    "fvg_state.json", "es_swing_thesis.json", "es_swing_verdict.json",
    "tammy_levels.json", "tictoc_levels.json", "calendar_context.json",
    "regime_label.json", "macro_pillars_cache.json", "orb_futures.json",
    "loss_limits.json",
]

# Freshness budgets (seconds). Intraday tape = 120s per dispatch; slower
# caches get proportionally looser budgets.
BUDGET = {
    "internals_snapshot.json": 120,
    "prices_futures.json": 300,
    "verdict.json": 300,
    "ict_state.json": 300,
    "fvg_state.json": 300,
    "es_bars_15m.json": 900,
    "es_swing_thesis.json": 3600,
    "es_swing_verdict.json": 3600,
    "breadth_snapshot.json": 86400,       # one trading day (reader-clock rule)
    "calendar_context.json": 86400,
    "tammy_levels.json": 86400 * 7,       # weekly newsletter cadence
    "tictoc_levels.json": 86400 * 7,
    "regime_label.json": 86400 * 3,
    "macro_pillars_cache.json": 86400 * 3,
    "orb_futures.json": 86400,
    "loss_limits.json": 86400 * 3,
}


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------------------
# derived: ATR + volume profile (authorised — built from the ict/fvg bars)
# ----------------------------------------------------------------------------

def atr_from_bars(bars, n=14):
    if not bars or len(bars) < n + 1:
        return None
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["h"], bars[i]["l"], bars[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    a = sum(trs[:n]) / n
    for t in trs[n:]:
        a = (a * (n - 1) + t) / n
    return round(a, 2)


# ----------------------------------------------------------------------------
# derived: LSQ slope gates on whatever intraday internals rows exist
# ----------------------------------------------------------------------------

def lsq_slope(series):
    """Least-squares slope of an evenly-indexed series."""
    n = len(series)
    if n < 2:
        return None
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(series) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, series))
    den = sum((x - mx) ** 2 for x in xs)
    return None if den == 0 else num / den


def build_gates():
    """
    v3.1 gates: 30-min / 30-row LSQ on add / vold / trin, slope must clear a
    10% magnitude floor. The morning internals archive (the row series the
    gate is defined over) is a Mac-side artefact and is NOT mirrored — only
    the latest end-of-day internals snapshot is. With <15 rows the gate is
    UNRELIABLE by its own contract, so that is exactly what we publish.
    """
    snap = load("internals_snapshot.json") or {}
    rows = snap.get("rows") or []
    add = [fnum(r.get("add")) for r in rows if fnum(r.get("add")) is not None]
    vold = [fnum(r.get("vold")) for r in rows if fnum(r.get("vold")) is not None]
    trin = [fnum(r.get("trin")) for r in rows if fnum(r.get("trin")) is not None]
    env = prov("internals_snapshot.json", snap,
               BUDGET["internals_snapshot.json"])
    n = len(rows)
    unreliable_reason = None
    if n < 15:
        unreliable_reason = (
            f"<15 rows ({n} available) — morning internals archive "
            "(9:35-10:00 LSQ series) is Mac-side, not mirrored"
        )
    elif env["status"] != "LIVE":
        unreliable_reason = f"feed age {env['age_s']}s > 120s"

    add_s = lsq_slope(add) if len(add) >= 2 else None
    vold_s = lsq_slope(vold) if len(vold) >= 2 else None
    trin_s = lsq_slope(trin) if len(trin) >= 2 else None
    verdict = "UNRELIABLE" if unreliable_reason else None  # PASS/FAIL only on a live series

    return {
        "long": verdict, "short": verdict,
        "add_slope": add_s, "vold_slope": vold_s, "trin_slope": trin_s,
        "magnitude_floor_pct": 10,
        "unreliable_reason": unreliable_reason,
        "rows_used": n,
        "_prov": env,
    }


# ----------------------------------------------------------------------------
# section builders
# ----------------------------------------------------------------------------

def build_phase():
    pf = load("prices_futures.json") or {}
    cal = load("calendar_context.json") or {}
    if pf.get("market_open") is False:
        return "CLOSED"
    # window boundaries are Mac-side; from the mirror we only know open/closed
    return "PRE" if pf.get("market_open") is None else "WINDOW1"


def build_classification():
    """
    day_type + VD_UP/VD_DOWN, evaluated on the 9:35-10:00 rows, first-match.
    That classifier lives Mac-side and does NOT publish to the mirror, and
    the row series it needs is not mirrored either. We publish it unclassified
    with the reason, and surface the end-of-day internals row as CONTEXT ONLY
    (never as a classification) so the gap is visible, not papered over.
    """
    snap = load("internals_snapshot.json") or {}
    rows = snap.get("rows") or []
    last = rows[-1] if rows else {}
    inputs = {
        "add_end": fnum(last.get("add")),
        "adspd_end": fnum(last.get("adspd")),
        "trin_end": fnum(last.get("trin")),
        "vold_end": fnum(last.get("vold")),
        "tick_end": fnum(last.get("tick")),
    }
    env = prov("internals_snapshot.json", snap,
               BUDGET["internals_snapshot.json"])
    return {
        "day_type": None,
        "evaluated_at": None,
        "inputs": inputs,
        "inputs_note": "end-of-session row only (16:04) — CONTEXT, not the "
                       "9:35-10:00 classification window",
        "unclassified_reason": "intraday day-type classifier is Mac-side and "
                               "does not publish to this mirror; the "
                               "9:35-10:00 internals archive it reads is not "
                               "mirrored either",
        "_prov": env,
    }


def build_risk():
    ll = load("loss_limits.json") or {}
    swing = load("es_swing_thesis.json") or {}
    d = load("es_bars_15m.json") or {}
    bars = d.get("bars") or []
    atr15 = atr_from_bars(bars, 14)
    lim = ll.get("registered_limits", {})
    today = (ll.get("status") or {}).get("today", {})
    env_ll = prov("loss_limits.json", ll, BUDGET["loss_limits.json"])
    env_bars = prov("es_bars_15m.json", d, BUDGET["es_bars_15m.json"])
    min_stop = round(atr15 * 1.5, 2) if atr15 is not None else None
    return {
        "atr_5m": {
            "value": None,
            "reason": "5m bars not published to mirror; es_bars_* carry "
                      "15m/60m/daily only",
        },
        "atr_15m": fresh_value(atr15, env_bars),
        "atr_source": "computed Wilder-14 on es_bars_15m.bars (same bars "
                      "ict/fvg use)",
        "min_stop": min_stop,
        "min_stop_basis": "atr_15m * 1.5",
        "min_rr": swing.get("min_rr", 1.5),
        "size": "half (1 MES)",
        "trades_today": today.get("n_trades"),
        "max_trades": lim.get("consecutive_loser_limit"),
        "one_loss_done": bool(today.get("daily_limit_hit")
                              or today.get("consecutive_limit_hit")) or None,
        "daily_stop_R": lim.get("daily_stop_R"),
        "daily_stop_pct": lim.get("daily_stop_pct"),
        "flat_by": "15:30",
        "_prov": {"loss_limits": env_ll, "bars": env_bars},
    }


def build_levels():
    d = load("es_bars_15m.json") or {}
    vp = d.get("vp") or {}
    swing = load("es_swing_thesis.json") or {}
    verdict = load("verdict.json") or {}
    dd = load("es_bars_daily.json") or {}
    daily = dd.get("bars") or []
    tammy = load("tammy_levels.json") or {}
    tictoc = load("tictoc_levels.json") or {}

    env_bars = prov("es_bars_15m.json", d, BUDGET["es_bars_15m.json"])
    env_swing = prov("es_swing_thesis.json", swing, BUDGET["es_swing_thesis.json"])
    env_daily = prov("es_bars_daily.json", dd, BUDGET["es_bars_15m.json"])
    env_tammy = prov("tammy_levels.json", tammy, BUDGET["tammy_levels.json"])
    env_tictoc = prov("tictoc_levels.json", tictoc, BUDGET["tictoc_levels.json"])

    price = fnum(verdict.get("es_price"))
    nearest = swing.get("nearest_levels") or []
    pools_above, pools_below = [], []
    for lv in nearest:
        p = fnum(lv.get("level"))
        if p is None or price is None:
            continue
        item = {"price": p, "kind": lv.get("kind"),
                "dist": round(p - price, 2)}
        (pools_above if p >= price else pools_below).append(item)

    prior_rth = None
    if len(daily) >= 2:
        pr = daily[-2]
        prior_rth = {"h": pr.get("h"), "l": pr.get("l"), "c": pr.get("c")}

    return {
        "pools_above": sorted(pools_above, key=lambda x: x["price"]),
        "pools_below": sorted(pools_below, key=lambda x: -x["price"]),
        "pools_source": "es_swing_thesis.nearest_levels",
        "fvg_unmitigated": [f for f in (load("fvg_state.json") or {}).get("fvgs", [])],
        "prior_rth": fresh_value(prior_rth, env_daily),
        "overnight": {"value": None,
                      "reason": "overnight H/L not published as a discrete "
                                "field on the mirror"},
        "vah": fresh_value(vp.get("vah"), env_bars),
        "poc": fresh_value(vp.get("poc"), env_bars),
        "val": fresh_value(vp.get("val"), env_bars),
        "vp_basis": vp.get("basis"),
        "newsletter": {
            "ter_schure": fresh_value(
                {"context": verdict.get("newsletter_context")},
                prov("verdict.json", verdict, BUDGET["verdict.json"])),
            "tammy": fresh_value(
                {"levels": tammy.get("levels"), "as_of": tammy.get("as_of")},
                env_tammy),
            "tic_toc": fresh_value(
                {"levels": tictoc.get("levels"), "as_of": tictoc.get("as_of")},
                env_tictoc),
        },
        "es_spx_basis": {"value": None,
                         "reason": "es-spx basis not published as a discrete "
                                   "field on the mirror; es_bars are "
                                   "unadjusted (offset 0) front-month ESU6"},
        "_prov": {"bars": env_bars, "swing": env_swing},
    }


def build_context():
    breadth = load("breadth_snapshot.json") or {}
    internals = load("internals_snapshot.json") or {}
    macro = load("macro_pillars_cache.json") or {}
    rows = internals.get("rows") or []
    last = rows[-1] if rows else {}
    env_b = prov("breadth_snapshot.json", breadth, BUDGET["breadth_snapshot.json"])
    env_i = prov("internals_snapshot.json", internals,
                 BUDGET["internals_snapshot.json"])
    env_m = prov("macro_pillars_cache.json", macro, BUDGET["macro_pillars_cache.json"])
    return {
        "megacap_pct": {"value": None,
                        "reason": "megacap breadth not published to mirror"},
        "megacap_verdict": None,
        "vix": fresh_value(fnum(last.get("vix")), env_i),
        "vix_term": {"value": None,
                     "reason": "vix9d / vix3m term structure not published to "
                               "mirror; spot VIX only (internals_snapshot)"},
        "nyad_cum": fresh_value(breadth.get("nyad_cum"), env_b),
        "nyad_vs_ath": fresh_value(breadth.get("below_peak"), env_b),
        "nyad_at_new_high": fresh_value(breadth.get("at_new_high"), env_b),
        "breadth_gate": (load("es_swing_verdict.json") or {}).get("breadth_gate"),
        "fld_status": fresh_value(macro.get("fld_status"), env_m),
        "_prov": {"breadth": env_b, "internals": env_i, "macro": env_m},
    }


def build_calendar():
    cal = load("calendar_context.json") or {}
    mc = load("market_calendar.json") or {}
    session = cal.get("date")
    events = mc.get("events") or []
    today_events = [e for e in events if e.get("date") == session]
    upcoming = sorted([e for e in events if e.get("date", "") >= (session or "")],
                      key=lambda e: (e.get("date", ""), e.get("time", "")))
    next_event = next((e for e in upcoming
                       if not (e.get("date") == session
                               and e.get("kind") in ("holiday",))), None)
    env = prov("calendar_context.json", cal, BUDGET["calendar_context.json"])
    return {
        "today_events": [e.get("label") for e in today_events],
        "next_event": (f"{next_event.get('label')}" if next_event else None),
        "no_position_into": bool(today_events) or None,
        "is_turn_of_month": cal.get("is_turn_of_month"),
        "days_to_month_end": cal.get("days_to_month_end"),
        "nyse_status": "closed" if (load("prices_futures.json") or {}).get(
            "market_open") is False else "full",
        "_prov": env,
    }


def build_cards():
    """
    Live status of the setup cards. Read from the setup engines that own
    them (orb_futures proposals, es_swing gating). No card is invented; a
    blocked engine is shown BLOCKED with its own blocking reason.
    """
    cards = []
    orb = load("orb_futures.json") or {}
    env_orb = prov("orb_futures.json", orb, BUDGET["orb_futures.json"])
    for t in orb.get("triggers", []):
        fails = t.get("fails") or []
        cards.append({
            "name": f"ORB {t.get('micro')} {t.get('side')}",
            "status": "QUALIFIED" if t.get("aplus") else "BLOCKED",
            "blocking_reason": ("A+ filters failed: " + ", ".join(fails))
                               if fails else None,
            "proposed": {"entry": t.get("entry"), "stop": t.get("stop"),
                         "t1": t.get("t1"), "t2": t.get("t2"),
                         "rr": t.get("rr_t2")},
            "trigger_time": t.get("trigger_time"),
            "source": "orb_futures.json",
            "_prov": env_orb,
        })
    swing = load("es_swing_verdict.json") or {}
    env_sw = prov("es_swing_verdict.json", swing, BUDGET["es_swing_verdict.json"])
    cards.append({
        "name": "ES Swing (60m break)",
        "status": "ARMED" if swing.get("actionable_count") else "BLOCKED",
        "blocking_reason": swing.get("headline"),
        "proposed": None,
        "source": "es_swing_verdict.json",
        "_prov": env_sw,
    })
    return cards


def build_freshness():
    board = {}
    for name in FEED_FILES:
        doc = load(name)
        env = prov(name, doc if isinstance(doc, dict) else {},
                   BUDGET.get(name))
        board[name.replace(".json", "")] = {
            "age_s": env["age_s"],
            "status": "DARK" if env["status"] == "DARK" else (
                "LIVE" if env["status"] == "LIVE" else "STALE"),
            "source_path": name,
        }
    return board


# ----------------------------------------------------------------------------
# assemble
# ----------------------------------------------------------------------------

def build():
    cal = load("calendar_context.json") or {}
    state = {
        "schema": "trade_state/1",
        "generated_at": NOW.isoformat(),
        "generated_by": "build_trade_state.py (dashboard mirror aggregator)",
        "reference_clock": "newest published feed timestamp (snapshot mirror; "
                           "NOT wall-clock — ages are relative to the freshest "
                           "feed)",
        "session_date": cal.get("date"),
        "phase": build_phase(),
        "classification": build_classification(),
        "gates": build_gates(),
        "risk": build_risk(),
        "levels": build_levels(),
        "context": build_context(),
        "calendar": build_calendar(),
        "cards": build_cards(),
        "freshness": build_freshness(),
        "mirror_gaps": [
            "day-type classifier (Mac-side; needs 9:35-10:00 internals archive)",
            "30-row LSQ slope gates (needs the same morning internals archive)",
            "atr_5m (no 5m bars mirrored)",
            "es_spx_basis, vix term structure, megacap breadth (not mirrored)",
        ],
        "provenance_note": "Every value carries source + age_s + status. "
                           "STALE(age)/DARK is rendered instead of a bare "
                           "value when a feed is past its freshness budget. "
                           "null+reason marks a field owned by a module that "
                           "does not publish to this mirror — never fabricated.",
    }
    return state


def main():
    global NOW
    NOW = reference_now()
    state = build()
    if "--check" in sys.argv:
        print(json.dumps(state, indent=2, default=str))
        # light validation
        assert state["freshness"], "empty freshness board"
        assert state["levels"]["poc"]["value"] is not None, "no POC read"
        print("\nOK: trade_state assembled, POC/VAH/VAL read, freshness board "
              f"has {len(state['freshness'])} feeds.", file=sys.stderr)
        return
    out = os.path.join(HERE, "trade_state.json")
    with open(out, "w") as fh:
        json.dump(state, fh, indent=2, default=str)
        fh.write("\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
