# DISPATCH 108 — Monte Carlo robustness engine (`mc_robustness.py`)

**STATUS: STAGED, not loaded.** Report-only / capture-only. Reads ledgers
READ-ONLY, changes nothing live, makes no sizing decisions (Kelly = D109,
separate + gated). Not wired into any live pipeline.

---

## ⚠️ Environment finding (READ THIS FIRST)

`DISPATCH 108` is tagged `[MAC-LOCAL]` and its READ-FIRST list assumes the
**deduped per-trade ledgers**, the **D88 bootstrap module**, the **EOD packet
assembler + audit email hooks**, the **dashboard push path**, and
**`sync_check.sh`** are all reachable. This work was done in a cloud session
whose only source is `arsenal-dashboard-public` — the **published dashboard**
(JSON snapshots), not the source system. None of those five components exist
here; only their *outputs* do (e.g. `exp_ci` values baked into JSON).

Consequently this engine was authored as a **spec/scaffold to run on
MAC-LOCAL**, where the real ledgers + D88 live. It was **not** validated
against the dispatch's reproduction targets here — those numbers do not
reconcile with the public snapshot (see below), which is exactly the
condition the dispatch's own VALIDATE step calls a STOP.

### Reproduction targets vs. this public snapshot (do not match — expected)

| Dispatch target | This repo's snapshot |
|---|---|
| GC 9_21_60m **n=38, exp ≈ +8.22** | `GC_9_21_60m_filtered` n=46 / matured 43 / **exp 10.25** |
| stocks 9_21_daily **n=52, ≈ +8.19%** | `9_21_daily_filtered` n=131 / exp 5.75 (metric = net_points) |
| meter@85 **n=74, −10.79** | ES@85 **n=76, −10.79** (exp matches, n≠) |
| STRONG_LONG **n=434** reference | not present (buckets here are n=14 / n=30) |
| ES SWING **n<10** | book currently **n=0** (empty) |

**Before this engine is trusted on MAC-LOCAL, `validate_reproductions()`
must pass against the real ledgers.** It runs automatically on every non-smoke
invocation and exits non-zero (STOP) if the means don't match the scorecards.

---

## Track → ledger map (fill on MAC-LOCAL)

The `LEDGER_MAP` in `mc_robustness.py` enumerates every scored track the
dispatch names (meter, EMA, GC/CL/stocks 9_21 filtered, stock-swing buckets,
convergence, ES SWING graded book). Each entry needs its **real local ledger
path + column** for per-trade P&L (`pnl_col`) and, where the ledger carries
it, per-trade R (`r_col`). Paths in the committed file are **placeholders**.

- `unit`: `pts` (futures/EMA/meter), `%` (stock-swing), etc.
- `r_col=None` → that track reports `$` drawdown / ruin as **R-UNAVAILABLE**
  (the R-multiple series is required to map fixed-$-risk sizing to dollars;
  `pick_asymmetry.json` confirms several buckets have *no per-trade R*).
- `intraday=True` → the stationary block bootstrap also runs and IID-vs-block
  disagreement is flagged.
- `is_es_swing=True` → **forced ILLUSTRATIVE** regardless of n.

---

## What the engine computes (per track)

1. Load per-trade P&L (pts **and** R where available). `n_paths = 10,000`.
2. **Two bootstrap modes**: IID resample (default) **and** Politis–Romano
   stationary block bootstrap (mean block ≈ `n^(1/3)`) for intraday tracks;
   both reported, material disagreement flagged.
3. **Zero-edge test**: sign-flip permutation → `p(observed total ≥ | zero edge)`,
   reported plainly. High p on a losing track = *confidently negative*.
4. **Drawdown distribution**: per path, max DD in native unit, in **R**, and in
   **$** at $50/$100/$150 per trade → median / p95 / max.
5. **Risk-of-ruin**: P(any path breaches the drawdown limit), default −$1,500
   (**real bankroll stays LOCAL, never pushed**), at each sizing level.
6. **Streak-normality**: longest-losing-streak distribution vs the track's
   actual trailing streak → "within normal variance" / "OUTSIDE p95".
7. **Expectancy CI**: percentile bootstrap (1500×, matching D88's method),
   **cross-checked against the D88 module** via
   `d88_expectancy_ci_crosscheck()` — imports D88, never forks it; falls back
   to the identical internal method and flags **RECONCILE ON MAC-LOCAL** when
   D88 isn't importable.
8. **Honesty labels** (hard-coded): `n<30` → ILLUSTRATIVE, `30–100` →
   INDICATIVE, `n≥100` → ROBUST. ES SWING forced ILLUSTRATIVE.

## Outputs

- `mc_robustness.json` — LOCAL artifact (may contain $), feeds the EOD email.
- **EOD "MC ROBUSTNESS" section** — `render_eod_section()`, one compact row per
  track, mobile-legible, **shows every scored track incl. negatives** (no
  survivorship). Additive block; splice into the MAC-LOCAL EOD assembler (it
  does not mutate its input — regression-safe).
- `mc_robustness_dashboard.json` — **aggregate/simulated only**: strips every
  $, ruin-$, bankroll and sizing; keeps R-based DD, p-values, labels, verdicts.

---

## Smoke test (this environment — NOT the dispatch validation)

`python3 mc_robustness.py --smoke` reconstructs per-trade series from the
public `perf_summary.json` proxies where they are **exact** (equity[]
differenced when `len==n_matured≤41`; gauge.trades[] $→pts when `≤60`).
Large-n tracks (exact sequence unrecoverable from the downsampled proxy) are
skipped. This verifies the math end-to-end:

- **Zero-edge signal correct**: negative tracks → high pZE (wave/60m −209.5 →
  0.91; CL_9_21_daily −0.96 → 0.89); positive tracks → low pZE (GC_9_21_60m
  +10.25 → 0.03; inside_bar/GC +70.4 → 0.06).
- **Honesty labels correct**: n<30 → ILLUSTRATIVE, 30–100 → INDICATIVE.
- **ES-SWING forced ILLUSTRATIVE** verified at n=45 (would otherwise be
  INDICATIVE), tails disclaimed.
- **Both bootstrap modes run** on intraday tracks; block mean-block-len = 4 for
  n=43; IID-vs-block disagreement detector fires correctly.
- **Large-n ROBUST reference** (synthetic n=434 w/ R): smooth DD in pts/R/$,
  ruin monotonic in sizing (0.38 / 0.64 / 0.75 at $50/$100/$150), streak dist
  smooth (median 7, p95 11).
- **Dashboard JSON privacy**: no `ruin`, `dollar`, `$` or bankroll keys present.

Smoke cannot produce a ROBUST label from real data (proxies only expose exact
series for small tracks) and cannot fill R-based $/ruin — both are available
only from the real ledgers on MAC-LOCAL.

---

## To run on MAC-LOCAL

1. Fill `LEDGER_MAP` with real ledger paths + columns (pts and R).
2. `export D88_MODULE=<d88 module name>` (and `D88_FUNC` if not `expectancy_ci`)
   so the CI cross-check reuses D88 instead of the internal fallback.
3. `python3 mc_robustness.py` → runs `validate_reproductions()` first (STOP on
   mismatch), then writes `mc_robustness.json` + `mc_robustness_dashboard.json`
   and prints the EOD section.
4. Splice `render_eod_section()` output into the EOD assembler; push only
   `mc_robustness_dashboard.json` to the dashboard.
5. Re-upload `mc_robustness.py` to Project Knowledge, run `sync_check.sh`,
   paste md5s.

**Deps**: numpy only (scipy optional). No vectorbt / quantstats.
