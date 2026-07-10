#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mc_robustness.py  --  DISPATCH 108  --  Monte Carlo robustness engine

STATUS: STAGED, report-only, capture/observe-only. Changes nothing live.
        Reads per-trade ledgers READ-ONLY. No auto-sizing. No Kelly (that is
        D109, a separate gated module). This engine INFORMS the human.

WHAT IT ANSWERS (per scored track, honestly):
  (a) Is the observed edge distinguishable from zero-edge luck?
      -> sign-flip permutation test, p(observed total P&L or better | zero edge)
  (b) What max-drawdown range is NORMAL at current sizing?
      -> bootstrap DD distribution in R and in $ at $50/$100/$150 per trade
         (median / p95 / max), so a losing streak can be judged in-variance
         vs broken.
  (c) Risk-of-ruin at $50/$100/$150 fixed risk per trade on MES
      -> probability any resampled path breaches a drawdown limit
         (default -$1,500; the real bankroll figure stays LOCAL, never pushed).

Plus: longest-losing-streak normality verdict, and a bootstrap expectancy CI
that is CROSS-CHECKED against the existing D88 percentile-bootstrap machinery
(reused, never forked -- see d88_expectancy_ci_crosscheck()).

DEPENDENCIES: numpy only (scipy optional, not required). NO heavy deps
              (no vectorbt / quantstats), per dispatch guardrails.

--------------------------------------------------------------------------
IMPORTANT ENVIRONMENT NOTE (read before running):
  The authoritative, deduped per-trade ledgers live on MAC-LOCAL. This module
  reads them through LEDGER_MAP below -- YOU MUST point each track at its real
  ledger file + column (pts and, where available, R). Until LEDGER_MAP is
  filled with real local paths, run with `--smoke` to exercise the full
  pipeline against the PUBLIC dashboard proxies (perf_summary.json), which is
  a SMOKE TEST of the math, NOT the dispatch's validation. The dispatch's
  reproduction checks (GC 9_21_60m n=38 ~ +8.22, stocks 9_21_daily n=52 ~
  +8.19%, meter@85 n=74 -10.79, STRONG_LONG n=434) must be run on MAC-LOCAL
  against the real ledgers -- see validate_reproductions().
--------------------------------------------------------------------------
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np

# ============================================================================
# CONSTANTS / TUNABLES
# ============================================================================

N_PATHS_DEFAULT = 10_000          # resampled paths per track per bootstrap mode
N_PERM_DEFAULT = 10_000           # sign-flip permutations for zero-edge test
N_BOOT_EXPECTANCY = 1_500         # match D88 ci_method: "percentile bootstrap 1500x"
ALPHA = 0.05                      # 95% CIs
SIZING_LEVELS = (50.0, 100.0, 150.0)   # $ risk per trade (1R) on MES
RUIN_LIMIT_DEFAULT = -1_500.0     # $ drawdown limit; REAL bankroll stays LOCAL
SEED_DEFAULT = 108                # deterministic; reproducible runs

# Honesty tiers (hard-coded, non-negotiable)
HONESTY_ILLUSTRATIVE = "ILLUSTRATIVE"
HONESTY_INDICATIVE = "INDICATIVE"
HONESTY_ROBUST = "ROBUST"

# MES point value (for pts->$ fallback ONLY; ruin/DD-$ prefer the R series).
MES_POINT_VALUE = 5.0


# ============================================================================
# TRACK -> LEDGER MAP  (EDIT ON MAC-LOCAL)
# ============================================================================
# Each entry describes ONE scored track and where its deduped per-trade series
# lives. `pnl_col` is per-trade P&L in the track's native unit (pts for
# futures/EMA/meter tracks, % for stock-swing buckets). `r_col` is the
# per-trade R-multiple column if the ledger carries one (many do not -- e.g.
# pick_asymmetry states "no per-trade R available"); leave None if absent and
# the $ DD / ruin outputs for that track will be reported as R-UNAVAILABLE.
#
#   intraday=True  -> also run the stationary block bootstrap (serial
#                     correlation plausible); disagreement with IID is flagged.
#   is_es_swing=True -> force ILLUSTRATIVE regardless of n (graded book, n<10).
#
# The `path` values below are LOCAL placeholders. Fill them with the real
# deduped ledger paths on MAC-LOCAL. Nothing here embeds a real $ figure.
# ----------------------------------------------------------------------------

@dataclass
class TrackCfg:
    track_id: str
    display: str
    path: str                      # local ledger path (CSV or JSON)
    pnl_col: str                   # per-trade P&L column (native unit)
    unit: str = "pts"              # "pts" | "R" | "%"
    r_col: Optional[str] = None    # per-trade R column, if present
    fmt: str = "csv"               # "csv" | "json"
    json_records_key: Optional[str] = None  # for json: key holding the list
    intraday: bool = False         # run block bootstrap + flag serial corr
    is_es_swing: bool = False      # force ILLUSTRATIVE
    group: str = ""                # display grouping (meter / EMA / GC-CL / ...)


# NOTE: this is the *template* for MAC-LOCAL. It enumerates every scored track
# the dispatch names (meter, EMA tracks, GC/CL/stocks 9_21 filtered, stock-swing
# buckets, convergence, ES SWING graded book). Paths are placeholders.
LEDGER_MAP: list[TrackCfg] = [
    # --- meter scorecard (per instrument / threshold) ---
    TrackCfg("meter_ES_85", "Meter ES @85", "ledgers/meter_es_85.csv",
             "net_points", "pts", intraday=True, group="meter"),
    TrackCfg("meter_ES_70", "Meter ES @70", "ledgers/meter_es_70.csv",
             "net_points", "pts", intraday=True, group="meter"),
    TrackCfg("meter_GC_85", "Meter GC @85", "ledgers/meter_gc_85.csv",
             "net_points", "pts", intraday=True, group="meter"),
    TrackCfg("meter_CL_85", "Meter CL @85", "ledgers/meter_cl_85.csv",
             "net_points", "pts", intraday=True, group="meter"),
    # --- EMA tracks (intraday) ---
    TrackCfg("ema_9_21_5m_raw", "EMA 9/21 5m raw", "ledgers/ema_9_21_5m.csv",
             "net_points", "pts", r_col="r_multiple", intraday=True, group="EMA"),
    # --- GC / CL / stocks 9_21 filtered ---
    TrackCfg("GC_9_21_60m_filtered", "GC 9/21 60m filt", "ledgers/gc_9_21_60m_filtered.csv",
             "net_points", "pts", r_col="r_multiple", intraday=True, group="GC-CL"),
    TrackCfg("CL_9_21_60m_filtered", "CL 9/21 60m filt", "ledgers/cl_9_21_60m_filtered.csv",
             "net_points", "pts", r_col="r_multiple", intraday=True, group="GC-CL"),
    TrackCfg("stocks_9_21_daily_filtered", "Stocks 9/21 D filt", "ledgers/stocks_9_21_daily_filtered.csv",
             "net_pct", "%", intraday=False, group="stocks"),
    # --- stock-swing buckets (daily; serial corr less plausible) ---
    TrackCfg("swing_STRONG_LONG", "Swing STRONG_LONG", "ledgers/swing_strong_long.csv",
             "net_pct", "%", intraday=False, group="swing"),
    # --- convergence ---
    TrackCfg("convergence", "Convergence", "ledgers/convergence.csv",
             "net_points", "pts", intraday=True, group="convergence"),
    # --- ES SWING graded book (n<10 -> ILLUSTRATIVE) ---
    TrackCfg("es_swing_book", "ES SWING book", "ledgers/es_swing_book.csv",
             "expectancy_pts", "pts", intraday=False, is_es_swing=True, group="ES-SWING"),
]


# ============================================================================
# LEDGER LOADING  (READ-ONLY)
# ============================================================================

@dataclass
class Series:
    track_id: str
    display: str
    unit: str
    pnl: np.ndarray                 # per-trade P&L, native unit, chronological
    r: Optional[np.ndarray]         # per-trade R-multiple, or None
    intraday: bool
    is_es_swing: bool
    group: str
    source: str                     # provenance string (file / proxy)


def _read_csv_column(path: str, col: str) -> np.ndarray:
    vals = []
    with open(path, newline="") as fh:
        rd = csv.DictReader(fh)
        if col not in (rd.fieldnames or []):
            raise KeyError(f"column {col!r} not in {path} (have {rd.fieldnames})")
        for row in rd:
            raw = row.get(col, "")
            if raw is None or str(raw).strip() == "":
                continue
            vals.append(float(raw))
    return np.asarray(vals, dtype=float)


def _read_json_column(path: str, records_key: Optional[str], col: str) -> np.ndarray:
    with open(path) as fh:
        d = json.load(fh)
    recs = d[records_key] if records_key else d
    return np.asarray([float(r[col]) for r in recs if r.get(col) is not None], dtype=float)


def load_track(cfg: TrackCfg) -> Series:
    """Load ONE track's deduped per-trade series, read-only, from its real
    ledger. Raises if the file/column is missing -- that is the dispatch's
    'ledger mapping is wrong, STOP' guard surfacing early."""
    if cfg.fmt == "csv":
        pnl = _read_csv_column(cfg.path, cfg.pnl_col)
        r = _read_csv_column(cfg.path, cfg.r_col) if cfg.r_col else None
    elif cfg.fmt == "json":
        pnl = _read_json_column(cfg.path, cfg.json_records_key, cfg.pnl_col)
        r = _read_json_column(cfg.path, cfg.json_records_key, cfg.r_col) if cfg.r_col else None
    else:
        raise ValueError(f"unknown fmt {cfg.fmt!r}")
    if r is not None and len(r) != len(pnl):
        raise ValueError(f"{cfg.track_id}: R length {len(r)} != pnl length {len(pnl)}")
    return Series(cfg.track_id, cfg.display, cfg.unit, pnl, r,
                  cfg.intraday, cfg.is_es_swing, cfg.group, source=cfg.path)


# ============================================================================
# BOOTSTRAP CORES  (numpy, vectorised over paths)
# ============================================================================

def iid_bootstrap_indices(n: int, n_paths: int, rng: np.random.Generator) -> np.ndarray:
    """IID resample WITH replacement -> (n_paths, n) index matrix."""
    return rng.integers(0, n, size=(n_paths, n))


def stationary_block_bootstrap_indices(n: int, n_paths: int, mean_block: float,
                                        rng: np.random.Generator) -> np.ndarray:
    """Politis-Romano stationary block bootstrap. Geometric block lengths with
    mean `mean_block`; wrap-around. Preserves serial correlation. Returns an
    (n_paths, n) index matrix built column-by-column (vectorised over paths)."""
    p = 1.0 / max(mean_block, 1.0)          # P(start new block) each step
    idx = np.empty((n_paths, n), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, size=n_paths)
    for j in range(1, n):
        start_new = rng.random(n_paths) < p
        cont = (idx[:, j - 1] + 1) % n       # continue current block (wrap)
        fresh = rng.integers(0, n, size=n_paths)
        idx[:, j] = np.where(start_new, fresh, cont)
    return idx


def mean_block_length(n: int) -> int:
    """Politis-Romano rule-of-thumb: mean block ~ n^(1/3), floored at 2."""
    return max(2, int(round(n ** (1.0 / 3.0))))


# ============================================================================
# PATH STATISTICS  (vectorised)
# ============================================================================

def max_drawdown_per_path(paths: np.ndarray) -> np.ndarray:
    """Most-negative running drawdown of each path's equity curve.
    paths: (P, n) per-trade P&L. Returns (P,) drawdown magnitudes (>= 0)."""
    equity = np.cumsum(paths, axis=1)
    peak = np.maximum.accumulate(equity, axis=1)
    dd = equity - peak                      # <= 0
    return -dd.min(axis=1)                   # magnitude


def longest_losing_streak_per_path(paths: np.ndarray) -> np.ndarray:
    """Longest run of consecutive losing (<0) trades per path. Vectorised
    over paths, loop over the (small) trade dimension."""
    neg = (paths < 0).astype(np.int64)       # (P, n)
    P, n = neg.shape
    run = np.zeros(P, dtype=np.int64)
    best = np.zeros(P, dtype=np.int64)
    for j in range(n):
        run = (run + neg[:, j]) * neg[:, j]  # reset to 0 on a win
        best = np.maximum(best, run)
    return best


def trailing_losing_streak(pnl: np.ndarray) -> int:
    """Current (trailing) consecutive-loss count in the real, ordered series."""
    c = 0
    for v in pnl[::-1]:
        if v < 0:
            c += 1
        else:
            break
    return c


# ============================================================================
# ZERO-EDGE PERMUTATION TEST  (sign-flip)
# ============================================================================

def zero_edge_pvalue(pnl: np.ndarray, n_perm: int, rng: np.random.Generator) -> float:
    """Sign-flip permutation test. Under the zero-edge null each trade's sign
    is random; we compare the observed TOTAL P&L against the null distribution
    of totals. Returns p = P(permuted total >= observed total | zero edge).

    Interpretation (per dispatch): a confidently-NEGATIVE track (e.g. meter@85)
    yields p ~ 1.0 for a *positive*-edge hypothesis (almost every sign-flip
    beats the very-negative observed total). A strong positive edge yields
    p ~ 0. Reported plainly, no stars."""
    n = pnl.size
    observed = pnl.sum()
    mag = np.abs(pnl)
    # chunk to bound memory for large n
    chunk = max(1, min(n_perm, 4_000_000 // max(n, 1)))
    ge = 0
    done = 0
    while done < n_perm:
        c = min(chunk, n_perm - done)
        signs = rng.integers(0, 2, size=(c, n)) * 2 - 1   # {-1,+1}
        totals = (signs * mag).sum(axis=1)
        ge += int(np.count_nonzero(totals >= observed))
        done += c
    return ge / n_perm


# ============================================================================
# EXPECTANCY CI  +  D88 CROSS-CHECK
# ============================================================================

def percentile_bootstrap_mean_ci(pnl: np.ndarray, n_boot: int, alpha: float,
                                  rng: np.random.Generator) -> tuple[float, float]:
    """Percentile bootstrap CI on mean P&L/trade -- the SAME method D88 uses
    ('percentile bootstrap 1500x'). We do not fork the math; this exists so
    the engine is self-contained AND so we can reconcile against D88."""
    n = pnl.size
    idx = rng.integers(0, n, size=(n_boot, n))
    means = pnl[idx].mean(axis=1)
    lo = float(np.percentile(means, 100 * alpha / 2))
    hi = float(np.percentile(means, 100 * (1 - alpha / 2)))
    return lo, hi


def d88_expectancy_ci_crosscheck(pnl: np.ndarray, n_boot: int, alpha: float,
                                 rng: np.random.Generator) -> dict:
    """Reuse the D88 CI machinery if importable; otherwise fall back to the
    identical percentile-bootstrap method and FLAG that reconciliation must be
    completed on MAC-LOCAL. Never forks D88's math -- imports it.

    Expected D88 interface (any one of these, tried in order):
        d88_bootstrap.expectancy_ci(pnl, n_boot=, alpha=) -> (lo, hi)
        bootstrap_ci.expectancy_ci(pnl, n_boot=, alpha=)  -> (lo, hi)
    Set env D88_MODULE / D88_FUNC to override."""
    internal_lo, internal_hi = percentile_bootstrap_mean_ci(pnl, n_boot, alpha, rng)
    mod_name = os.environ.get("D88_MODULE", "")
    func_name = os.environ.get("D88_FUNC", "expectancy_ci")
    candidates = [mod_name] if mod_name else ["d88_bootstrap", "bootstrap_ci", "d88"]
    for m in candidates:
        if not m:
            continue
        try:
            mod = __import__(m)
            fn = getattr(mod, func_name)
            lo, hi = fn(pnl, n_boot=n_boot, alpha=alpha)
            # reconcile
            tol = 1e-6 + 0.02 * (abs(internal_hi - internal_lo))  # 2% of width
            agree = abs(lo - internal_lo) <= tol and abs(hi - internal_hi) <= tol
            return {
                "ci": [round(float(lo), 4), round(float(hi), 4)],
                "source": f"D88:{m}.{func_name}",
                "internal_ci": [round(internal_lo, 4), round(internal_hi, 4)],
                "reconciled": bool(agree),
                "note": "OK" if agree else "DIVERGES FROM INTERNAL -- INVESTIGATE",
            }
        except Exception:
            continue
    return {
        "ci": [round(internal_lo, 4), round(internal_hi, 4)],
        "source": "internal_percentile_bootstrap_1500x",
        "internal_ci": [round(internal_lo, 4), round(internal_hi, 4)],
        "reconciled": None,
        "note": "D88 module not importable here -- RECONCILE ON MAC-LOCAL",
    }


# ============================================================================
# HONESTY LABEL
# ============================================================================

def honesty_label(n: int, is_es_swing: bool) -> tuple[str, str]:
    """Hard-coded tiers. ES SWING (n<10) MUST render ILLUSTRATIVE."""
    if is_es_swing or n < 30:
        return HONESTY_ILLUSTRATIVE, (
            f"ILLUSTRATIVE -- resampling n={n} trades cannot characterize tails")
    if n < 100:
        return HONESTY_INDICATIVE, f"INDICATIVE -- n={n} (30-100)"
    return HONESTY_ROBUST, f"ROBUST -- n={n} (>=100)"


# ============================================================================
# PER-TRACK ANALYSIS
# ============================================================================

def _dd_summary(dd: np.ndarray) -> dict:
    return {
        "median": round(float(np.median(dd)), 3),
        "p95": round(float(np.percentile(dd, 95)), 3),
        "max": round(float(dd.max()), 3),
    }


def _analyze_mode(pnl: np.ndarray, r: Optional[np.ndarray], idx: np.ndarray,
                  ruin_limit: float) -> dict:
    """Compute DD (pts + R + $), ruin, streak distribution for one bootstrap
    mode given a precomputed index matrix."""
    paths_pnl = pnl[idx]                       # (P, n) native-unit paths
    dd_native = max_drawdown_per_path(paths_pnl)
    streaks = longest_losing_streak_per_path(paths_pnl)

    out: dict = {
        "dd_native": _dd_summary(dd_native),   # pts or %
        "streak_dist": {
            "median": int(np.median(streaks)),
            "p95": int(np.percentile(streaks, 95)),
            "max": int(streaks.max()),
        },
        "_streaks": streaks,                    # kept for verdict, stripped later
    }

    if r is not None:
        paths_r = r[idx]
        dd_r = max_drawdown_per_path(paths_r)
        out["dd_R"] = _dd_summary(dd_r)
        equity_r = np.cumsum(paths_r, axis=1)
        trough_r = equity_r.min(axis=1)         # (P,) worst cumulative R
        dd_dollars = {}
        ruin = {}
        for lvl in SIZING_LEVELS:
            dd_dollars[f"${int(lvl)}"] = _dd_summary(dd_r * lvl)
            # ruin: any path whose cumulative $ breaches the limit
            breached = (trough_r * lvl) <= ruin_limit
            ruin[f"${int(lvl)}"] = round(float(np.mean(breached)), 4)
        out["dd_dollars"] = dd_dollars
        out["ruin_prob"] = ruin
    else:
        out["dd_R"] = None
        out["dd_dollars"] = None
        out["ruin_prob"] = None
        out["r_note"] = "R-UNAVAILABLE -- provide r_col for $ DD / ruin"
    return out


def analyze_track(s: Series, n_paths: int, n_perm: int, ruin_limit: float,
                  seed: int) -> dict:
    rng = np.random.default_rng(seed + abs(hash(s.track_id)) % 100_000)
    n = int(s.pnl.size)
    label, label_text = honesty_label(n, s.is_es_swing)

    expectancy = float(s.pnl.mean()) if n else float("nan")
    total = float(s.pnl.sum()) if n else float("nan")

    result: dict = {
        "track_id": s.track_id,
        "display": s.display,
        "group": s.group,
        "unit": s.unit,
        "n": n,
        "expectancy": round(expectancy, 4) if n else None,
        "net_total": round(total, 3) if n else None,
        "honesty": label,
        "honesty_text": label_text,
        "source": s.source,
    }

    if n < 2:
        result["status"] = "SKIPPED -- need >=2 trades to resample"
        return result

    # (a) zero-edge permutation test
    result["p_zero_edge"] = round(zero_edge_pvalue(s.pnl, n_perm, rng), 4)

    # (7) expectancy CI + D88 cross-check
    result["expectancy_ci"] = d88_expectancy_ci_crosscheck(
        s.pnl, N_BOOT_EXPECTANCY, ALPHA, rng)

    # (2) bootstrap modes: IID always; block for intraday tracks
    iid_idx = iid_bootstrap_indices(n, n_paths, rng)
    modes = {"iid": _analyze_mode(s.pnl, s.r, iid_idx, ruin_limit)}
    if s.intraday:
        L = mean_block_length(n)
        blk_idx = stationary_block_bootstrap_indices(n, n_paths, L, rng)
        modes["block"] = _analyze_mode(s.pnl, s.r, blk_idx, ruin_limit)
        modes["block"]["mean_block_len"] = L

    # (6) streak-normality verdict vs the ACTUAL trailing streak
    actual_streak = trailing_losing_streak(s.pnl)
    result["current_losing_streak"] = actual_streak
    for mkey, m in modes.items():
        p95 = int(np.percentile(m["_streaks"], 95))
        verdict = "within normal variance" if actual_streak <= p95 else "OUTSIDE p95"
        m["streak_verdict"] = verdict
        del m["_streaks"]                       # strip raw array before serialise

    # flag material IID-vs-block disagreement (autocorrelation matters)
    if "block" in modes:
        result["iid_vs_block"] = _disagreement_flags(modes["iid"], modes["block"])

    result["modes"] = modes
    return result


def _disagreement_flags(iid: dict, blk: dict, rel_tol: float = 0.25) -> dict:
    """Flag tracks where IID and block bootstrap materially disagree."""
    flags = []

    def rel(a, b):
        denom = max(abs(a), abs(b), 1e-9)
        return abs(a - b) / denom

    # DD p95 (native)
    if rel(iid["dd_native"]["p95"], blk["dd_native"]["p95"]) > rel_tol:
        flags.append(f"DD_p95 native diverges "
                     f"(IID {iid['dd_native']['p95']} vs block {blk['dd_native']['p95']})")
    # ruin at $100 if present
    if iid.get("ruin_prob") and blk.get("ruin_prob"):
        ri, rb = iid["ruin_prob"]["$100"], blk["ruin_prob"]["$100"]
        if abs(ri - rb) > 0.05:
            flags.append(f"ruin@$100 diverges (IID {ri} vs block {rb})")
    # streak p95
    if abs(iid["streak_dist"]["p95"] - blk["streak_dist"]["p95"]) >= 2:
        flags.append(f"streak_p95 diverges "
                     f"(IID {iid['streak_dist']['p95']} vs block {blk['streak_dist']['p95']})")
    return {"material": bool(flags), "flags": flags}


# ============================================================================
# OUTPUT RENDERERS
# ============================================================================

def build_full_json(results: list[dict], ruin_limit: float, seed: int,
                    n_paths: int = N_PATHS_DEFAULT, n_perm: int = N_PERM_DEFAULT) -> dict:
    """mc_robustness.json -- the LOCAL artifact (may contain $). Feeds the EOD
    email. NOT pushed to the public dashboard as-is."""
    return {
        "kind": "mc_robustness",
        "dispatch": "D108",
        "status": "STAGED / report-only / read-only ledgers",
        "params": {
            "n_paths": n_paths, "n_perm": n_perm,
            "n_boot_expectancy": N_BOOT_EXPECTANCY, "alpha": ALPHA,
            "sizing_levels_usd": list(SIZING_LEVELS),
            "ruin_limit_usd": ruin_limit, "seed": seed,
        },
        "honesty_tiers": {
            "n<30": HONESTY_ILLUSTRATIVE, "30-100": HONESTY_INDICATIVE,
            "n>=100": HONESTY_ROBUST,
            "note": "ES SWING forced ILLUSTRATIVE; tails explicitly disclaimed",
        },
        "tracks": results,
    }


def build_dashboard_json(results: list[dict]) -> dict:
    """Dashboard JSON -- AGGREGATE / SIMULATED ONLY. Strips every $ figure,
    ruin-$, bankroll and sizing. Keeps R-based DD, p-values, labels, verdicts."""
    pub = []
    for r in results:
        row = {
            "track": r.get("display"),
            "group": r.get("group"),
            "n": r.get("n"),
            "unit": r.get("unit"),
            "expectancy": r.get("expectancy"),
            "expectancy_ci": (r.get("expectancy_ci") or {}).get("ci"),
            "p_zero_edge": r.get("p_zero_edge"),
            "honesty": r.get("honesty"),
        }
        modes = r.get("modes", {})
        iid = modes.get("iid", {})
        if iid:
            row["dd_native_p95"] = iid.get("dd_native", {}).get("p95")
            row["dd_R_p95"] = (iid.get("dd_R") or {}).get("p95")
            row["streak_p95"] = iid.get("streak_dist", {}).get("p95")
            row["streak_verdict"] = iid.get("streak_verdict")
        row["iid_vs_block_material"] = (r.get("iid_vs_block") or {}).get("material")
        pub.append(row)
    return {
        "kind": "mc_robustness_dashboard",
        "privacy": "aggregate/simulated only -- no $, no bankroll, no positions",
        "honesty_tiers": {"n<30": "ILLUSTRATIVE", "30-100": "INDICATIVE", "n>=100": "ROBUST"},
        "tracks": pub,
    }


def render_eod_section(results: list[dict]) -> str:
    """Compact 'MC ROBUSTNESS' section for the EOD email. One row per track,
    mobile-legible. Shows EVERY scored track incl. negatives (no survivorship).
    This is an ADDITIVE block -- splice into the MAC-LOCAL EOD assembler; it
    does not mutate its input."""
    lines = []
    lines.append("MC ROBUSTNESS  (D108 -- STAGED, resampled/simulated)")
    lines.append("track           n    exp   pZE   DDp95($100)  ruin$100  streak  label")
    lines.append("-" * 78)
    for r in results:
        modes = r.get("modes", {})
        iid = modes.get("iid", {})
        n = r.get("n", 0)
        exp = r.get("expectancy")
        pze = r.get("p_zero_edge")
        ddd = (iid.get("dd_dollars") or {}).get("$100", {}) if iid else {}
        dd95 = ddd.get("p95")
        ruin = (iid.get("ruin_prob") or {}).get("$100") if iid else None
        sv = iid.get("streak_verdict", "?") if iid else "?"
        sv_short = "OK" if sv == "within normal variance" else ("!p95" if sv == "OUTSIDE p95" else "?")
        lab = {"ILLUSTRATIVE": "ILL", "INDICATIVE": "IND", "ROBUST": "ROB"}.get(r.get("honesty"), "?")
        dd_s = f"{dd95:>8.0f}" if isinstance(dd95, (int, float)) else "   R-n/a"
        ruin_s = f"{ruin:>6.2%}" if isinstance(ruin, (int, float)) else "  R-n/a"
        exp_s = f"{exp:>6.2f}" if isinstance(exp, (int, float)) else "   n/a"
        pze_s = f"{pze:>4.2f}" if isinstance(pze, (int, float)) else " n/a"
        lines.append(f"{r.get('display','')[:14]:<14} {n:>4} {exp_s} {pze_s}  "
                     f"{dd_s}   {ruin_s}   {sv_short:<5} {lab}")
    lines.append("-" * 78)
    lines.append("pZE=p(zero-edge); high pZE on a losing track = confidently negative.")
    lines.append("ILL/IND/ROB = honesty tier. R-n/a = no per-trade R -> $ DD/ruin unavailable.")
    return "\n".join(lines)


# ============================================================================
# VALIDATION (MAC-LOCAL)  --  the dispatch's STOP guard
# ============================================================================

REPRO_TARGETS = {
    # track_id : (expected_n, expected_expectancy, tol_n, tol_exp, unit)
    "GC_9_21_60m_filtered": (38, 8.22, 3, 0.5, "pts"),
    "stocks_9_21_daily_filtered": (52, 8.19, 3, 0.5, "%"),
    "meter_ES_85": (74, -10.79, 3, 0.5, "pts"),
}


def validate_reproductions(results_by_id: dict) -> list[str]:
    """Reproduce known scorecard stats from the ledgers. If the engine's means
    do not match the scorecards, THE LEDGER MAPPING IS WRONG -> STOP.
    Returns a list of FAILURE strings (empty == all reproductions passed)."""
    failures = []
    for tid, (en, ee, tn, te, unit) in REPRO_TARGETS.items():
        r = results_by_id.get(tid)
        if r is None:
            failures.append(f"{tid}: not present in results (expected n~{en}, exp~{ee})")
            continue
        if abs((r.get("n") or 0) - en) > tn:
            failures.append(f"{tid}: n={r.get('n')} != expected {en} (+-{tn})")
        exp = r.get("expectancy")
        if exp is None or abs(exp - ee) > te:
            failures.append(f"{tid}: exp={exp} != expected {ee} (+-{te})")
    return failures


# ============================================================================
# SMOKE MODE  --  exercise the pipeline on PUBLIC perf_summary.json proxies
# ============================================================================
# This is NOT the dispatch validation. It reconstructs the per-trade series
# from the public dashboard's downsampled proxies where they are EXACT:
#   - equity[] differenced when len(equity)==n_matured<=41
#   - gauge.trades[] ($, last-60) converted to pts via the size_label, when
#     len==n_matured<=60
# Large-n tracks (exact sequence not recoverable) are marked partial/skipped.
# It lets us verify the math end-to-end in this environment.

def _parse_dollars_per_point(size_label: str) -> Optional[float]:
    """'2 GC contracts ($100/pt)' -> 200.0 ; returns None if unparseable."""
    import re
    m_ct = re.match(r"\s*(\d+)\s+", size_label or "")
    m_pt = re.search(r"\$(\d+(?:\.\d+)?)\s*/\s*pt", size_label or "")
    if not m_pt:
        return None
    contracts = float(m_ct.group(1)) if m_ct else 1.0
    return contracts * float(m_pt.group(1))


def load_smoke_series() -> list[Series]:
    """Build Series from perf_summary.json proxies. Clearly a SMOKE source."""
    with open("perf_summary.json") as fh:
        d = json.load(fh)
    out: list[Series] = []
    intraday_systems = {"ema", "ema_gccl", "fvg", "ict", "inside_bar"}
    for sname, sysd in d.get("systems", {}).items():
        for t in sysd.get("tracks", []):
            if not isinstance(t, dict):
                continue
            nm = t.get("n_matured")
            eq = t.get("equity", []) or []
            g = t.get("gauge", {}) or {}
            gt = g.get("trades", []) or []
            pnl = None
            src = None
            # exact per-trade via equity differencing (small tracks)
            if isinstance(nm, int) and len(eq) == nm and 2 <= nm <= 41:
                pnl = np.diff(np.concatenate([[0.0], np.asarray(eq, float)]))
                src = "proxy:equity-diff"
            # else exact via gauge.trades ($ -> pts), last-60 window
            elif isinstance(nm, int) and len(gt) == nm and 2 <= nm <= 60:
                dpp = _parse_dollars_per_point(g.get("size_label", ""))
                if dpp:
                    pnl = np.asarray(gt, float) / dpp
                    src = "proxy:gauge$/pt"
            if pnl is None:
                continue  # large-n: exact sequence not recoverable from proxy
            tid = f"{sname}:{t.get('track')}"
            out.append(Series(
                track_id=tid, display=f"{sname}/{t.get('track')}"[:14], unit="pts",
                pnl=pnl, r=None, intraday=(sname in intraday_systems),
                is_es_swing=False, group=sname, source=src))
    # force an ES-SWING style ILLUSTRATIVE demo from the smallest wave track
    return out


# ============================================================================
# DRIVER
# ============================================================================

def run(series_list: list[Series], n_paths: int, n_perm: int,
        ruin_limit: float, seed: int) -> list[dict]:
    results = []
    for s in series_list:
        results.append(analyze_track(s, n_paths, n_perm, ruin_limit, seed))
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description="D108 Monte Carlo robustness engine (report-only)")
    ap.add_argument("--smoke", action="store_true",
                    help="exercise pipeline on public perf_summary.json proxies (NOT validation)")
    ap.add_argument("--n-paths", type=int, default=N_PATHS_DEFAULT)
    ap.add_argument("--n-perm", type=int, default=N_PERM_DEFAULT)
    ap.add_argument("--ruin-limit", type=float, default=RUIN_LIMIT_DEFAULT,
                    help="$ drawdown limit (LOCAL; default -1500)")
    ap.add_argument("--seed", type=int, default=SEED_DEFAULT)
    ap.add_argument("--out", default="mc_robustness.json")
    ap.add_argument("--dashboard-out", default="mc_robustness_dashboard.json")
    ap.add_argument("--eod-out", default=None, help="write EOD section to file")
    ap.add_argument("--no-write", action="store_true", help="print only, write nothing")
    args = ap.parse_args(argv)

    if args.smoke:
        print("=== SMOKE MODE: public perf_summary.json proxies -- NOT dispatch validation ===",
              file=sys.stderr)
        series_list = load_smoke_series()
    else:
        # MAC-LOCAL path: load the real deduped ledgers via LEDGER_MAP
        series_list = []
        for cfg in LEDGER_MAP:
            try:
                series_list.append(load_track(cfg))
            except Exception as e:
                print(f"LEDGER LOAD FAILED for {cfg.track_id}: {e}", file=sys.stderr)
                print("  -> fill LEDGER_MAP with the real local ledger path/column. STOP.",
                      file=sys.stderr)
                return 2

    results = run(series_list, args.n_paths, args.n_perm, args.ruin_limit, args.seed)
    results_by_id = {r["track_id"]: r for r in results}

    # dispatch STOP guard (only meaningful with real ledgers)
    if not args.smoke:
        fails = validate_reproductions(results_by_id)
        if fails:
            print("REPRODUCTION VALIDATION FAILED -- ledger mapping is wrong. STOP.",
                  file=sys.stderr)
            for f in fails:
                print("  - " + f, file=sys.stderr)
            return 3

    full = build_full_json(results, args.ruin_limit, args.seed, args.n_paths, args.n_perm)
    dash = build_dashboard_json(results)
    eod = render_eod_section(results)

    print(eod)
    if not args.no_write:
        with open(args.out, "w") as fh:
            json.dump(full, fh, indent=2)
        with open(args.dashboard_out, "w") as fh:
            json.dump(dash, fh, indent=2)
        if args.eod_out:
            with open(args.eod_out, "w") as fh:
                fh.write(eod + "\n")
        print(f"\n[wrote {args.out}, {args.dashboard_out}]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
