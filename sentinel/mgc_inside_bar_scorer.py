#!/usr/bin/env python3
"""
sentinel/mgc_inside_bar_scorer.py — MGC inside-bar FORWARD scorer (SHADOW / DESCRIPTIVE)

Reads the forward ledger (mgc_inside_bar_forward.csv) written by the sentinel,
scores the CLOSED (triple-barrier-stamped) rows, and returns the weekly brief:
n, expectancy (net points), PF, payoff, win%, max drawdown, and a bootstrap CI.

It ENFORCES the pre-registered gates so nothing gets promoted by vibe:

  VALIDATED  iff  n >= 30
                  AND bootstrap CI (1500x, net points) EXCLUDES 0
                  AND forward expectancy >= 50% of the in-sample +63.67 (>= 31.835)
  KILL       iff  (expectancy < 0 AND n >= 30)
                  OR max_dd < 2x the in-sample -220.8 pts (< -441.6)
                  -> track RETIRED, logged as regime-capture confirmation, NOT "needs tuning"
  else       DESCRIPTIVE (informational, never sized)

net_points in the ledger are stamped by the nightly triple-barrier labeler ALREADY
NET of MGC costs + 1 tick (0.1) slippage (per the pre-registration); this scorer
consumes them as-is. FORWARD only — never blended with the in-sample series.

Honesty: the in-sample sample lived through a single gold BULL regime. This forward
test exists to see whether the pattern survives outside it. Tagged DESCRIPTIVE until
the gates clear. Self-tested; not loaded by any live path.
"""
from __future__ import annotations
from typing import List, Dict, Optional
import csv, os, random

IN_SAMPLE_EXP = 63.67                       # in-sample GC_RAW net-points expectancy (n=71)
VALIDATION_EXP_FLOOR = 0.5 * IN_SAMPLE_EXP  # 31.835
IN_SAMPLE_MAXDD = -220.8                     # in-sample max drawdown (net points)
KILL_MAXDD = 2 * IN_SAMPLE_MAXDD            # -441.6
MIN_N = 30
BOOT_ITERS = 1500                           # bootstrap resamples for the CI
BOOT_SEED = 20260715                         # fixed seed -> reproducible CI (no Date.now-style drift)


def _max_drawdown(net: List[float]) -> float:
    """Most-negative peak-to-trough of the cumulative net-points curve (<= 0)."""
    peak = 0.0
    cum = 0.0
    mdd = 0.0
    for x in net:
        cum += x
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    return round(mdd, 4)


def _bootstrap_ci(net: List[float], iters: int = BOOT_ITERS, seed: int = BOOT_SEED,
                  lo_pct: float = 2.5, hi_pct: float = 97.5) -> Optional[List[float]]:
    """Percentile bootstrap CI of the MEAN net points. Deterministic (seeded)."""
    n = len(net)
    if n == 0:
        return None
    rnd = random.Random(seed)
    means = []
    for _ in range(iters):
        s = 0.0
        for _ in range(n):
            s += net[rnd.randrange(n)]
        means.append(s / n)
    means.sort()

    def pct(p):
        k = (len(means) - 1) * (p / 100.0)
        f = int(k)
        c = min(f + 1, len(means) - 1)
        return means[f] + (means[c] - means[f]) * (k - f)

    return [round(pct(lo_pct), 4), round(pct(hi_pct), 4)]


def _closed_net_points(rows: List[Dict]) -> List[float]:
    out = []
    for r in rows:
        v = r.get("net_points")
        if v is None or v == "":
            continue
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out


def score(rows: List[Dict]) -> Dict:
    """Score closed ledger rows against the pre-registered gates."""
    net = _closed_net_points(rows)
    n = len(net)
    n_armed = len(rows)
    if n == 0:
        return {"kind": "mgc_inside_bar_forward", "basis": "FORWARD · net points · DESCRIPTIVE",
                "n_armed": n_armed, "n_closed": 0, "status": "ACCRUING (n=0)",
                "gate": "DESCRIPTIVE", "expectancy": None, "profit_factor": None,
                "payoff_ratio": None, "win_rate_pct": None, "max_dd": None, "boot_ci": None,
                "review_line": f"ACCRUING — {n_armed} armed, 0 closed. Nothing to score yet. DESCRIPTIVE."}

    wins = [x for x in net if x > 0]
    losses = [x for x in net if x <= 0]
    gross_w, gross_l = sum(wins), -sum(losses)
    avg_w = (gross_w / len(wins)) if wins else 0.0
    avg_l = (gross_l / len(losses)) if losses else 0.0
    exp = sum(net) / n
    mdd = _max_drawdown(net)
    ci = _bootstrap_ci(net)
    ci_excludes_0 = ci is not None and not (ci[0] <= 0 <= ci[1])

    # ---- gate logic (pre-registered) ----
    killed = (exp < 0 and n >= MIN_N) or (mdd < KILL_MAXDD)
    validated = (n >= MIN_N and ci_excludes_0 and exp >= VALIDATION_EXP_FLOOR)
    if killed:
        gate = "KILLED"
        reason = ("expectancy negative at n>=30" if (exp < 0 and n >= MIN_N)
                  else f"max_dd {mdd} < 2x in-sample ({KILL_MAXDD})")
        review = (f"KILL CRITERION HIT ({reason}). Track RETIRED — logged as regime-capture "
                  f"confirmation, NOT 'needs tuning'. n={n}, exp={round(exp,3)}, max_dd={mdd}.")
    elif validated:
        gate = "VALIDATED"
        review = (f"VALIDATED — n={n}>=30, CI {ci} excludes 0, exp {round(exp,3)} "
                  f">= 50% of in-sample ({round(VALIDATION_EXP_FLOOR,3)}). Eligible for sizing review.")
    else:
        gate = "DESCRIPTIVE"
        unmet = []
        if n < MIN_N:
            unmet.append(f"n={n}<30")
        if not ci_excludes_0:
            unmet.append(f"CI {ci} spans 0")
        if exp < VALIDATION_EXP_FLOOR:
            unmet.append(f"exp {round(exp,3)} < floor {round(VALIDATION_EXP_FLOOR,3)}")
        review = (f"DESCRIPTIVE — informational, never sized. Unmet: {', '.join(unmet)}. "
                  f"In-sample lived one gold bull regime; earning it forward.")

    return {
        "kind": "mgc_inside_bar_forward", "basis": "FORWARD · net points · gates pre-registered",
        "n_armed": n_armed, "n_closed": n,
        "expectancy": round(exp, 4), "in_sample_expectancy": IN_SAMPLE_EXP,
        "validation_floor": round(VALIDATION_EXP_FLOOR, 4),
        "profit_factor": round(gross_w / gross_l, 4) if gross_l else None,
        "payoff_ratio": round(avg_w / avg_l, 4) if avg_l else None,
        "win_rate_pct": round(100.0 * len(wins) / n, 1),
        "max_dd": mdd, "kill_max_dd": KILL_MAXDD,
        "boot_ci": ci, "boot_iters": BOOT_ITERS, "ci_excludes_0": ci_excludes_0,
        "gate": gate, "status": gate, "review_line": review,
    }


def score_csv(path: str) -> Dict:
    if not (os.path.exists(path) and os.path.getsize(path) > 0):
        return score([])
    with open(path, newline="") as fh:
        return score(list(csv.DictReader(fh)))


# ------------------------------------------------------------------ selftest
def _row(net):  # production-shaped closed row (subset of the ledger schema)
    return {"instrument": "MGC", "timeframe": "daily", "direction": "long",
            "outcome": "target" if net > 0 else "stop", "net_points": str(net)}


def _selftest() -> None:
    # (0) empty ledger -> ACCRUING, DESCRIPTIVE
    assert score([])["gate"] == "DESCRIPTIVE" and score([])["n_closed"] == 0

    # (1) armed-but-not-closed rows are not scored as trades
    s = score([{"instrument": "MGC", "net_points": ""}, {"instrument": "MGC", "net_points": None}])
    assert s["n_armed"] == 2 and s["n_closed"] == 0

    # (2) small positive sample: n<30 -> DESCRIPTIVE regardless of how good it looks
    good_small = [_row(x) for x in [80, 90, -30, 70, 85]]
    s = score(good_small)
    assert s["n_closed"] == 5 and s["gate"] == "DESCRIPTIVE"

    # (3) VALIDATED: n>=30, strong positive, CI clears 0, exp >= 31.835
    big = [_row(x) for x in ([80, 75, 90, -25, 85, 70] * 6)]  # 36 rows, mean well above floor
    s = score(big)
    assert s["n_closed"] == 36
    assert s["ci_excludes_0"] and s["expectancy"] >= VALIDATION_EXP_FLOOR
    assert s["gate"] == "VALIDATED", s["review_line"]

    # (4) KILL by negative expectancy at n>=30
    bad = [_row(x) for x in ([-60, -50, 20, -40, 10, -30] * 6)]  # 36 rows, mean < 0
    s = score(bad)
    assert s["n_closed"] == 36 and s["expectancy"] < 0 and s["gate"] == "KILLED", s

    # (5) KILL by drawdown breach: cumulative trough below -441.6 (2x in-sample)
    dd = [_row(x) for x in ([-100.0] * 5)]  # cum: -100..-500 < -441.6
    s = score(dd)
    assert s["max_dd"] <= KILL_MAXDD and s["gate"] == "KILLED", s

    # (6) high win-rate but tiny/near-zero edge at n>=30, CI spans 0 -> DESCRIPTIVE not VALIDATED
    marg = [_row(x) for x in ([5, 6, -4, 5, -6, 5] * 6)]  # 36 rows, small mean, CI likely spans 0
    s = score(marg)
    assert s["n_closed"] == 36 and s["gate"] in ("DESCRIPTIVE",), s["review_line"]

    # (7) bootstrap CI is deterministic (seeded) -> identical across runs
    assert score(big)["boot_ci"] == score(big)["boot_ci"]

    print("mgc_inside_bar_scorer selftest: OK (8 checks; gates VALIDATED/KILL/DESCRIPTIVE exercised)")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        p = os.environ.get("MGC_IB_LEDGER",
                           os.path.join(os.path.dirname(__file__), "mgc_inside_bar_forward.csv"))
        import json
        print(json.dumps(score_csv(p), indent=2))
