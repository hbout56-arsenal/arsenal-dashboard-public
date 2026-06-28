# screener_v2 — parallel pro-faithful screener (Dispatch 53 · SHADOW · NOT loaded)

A ground-up Minervini/O'Neil/Zanger/CANSLIM **gating+ranking** pipeline that runs in
**parallel** to the live engine and logs its **own** forward ledger head-to-head. It
**never** feeds the live screener/email/dashboard. Promotion only on **n≥30 forward beat +
÷6 haircut + explicit go**. `SIMULATED / advisory.`

| file | what it is |
|---|---|
| `preregistration_v2.json` | FROZEN stage thresholds (set before the funnel run). ÷N=6 haircut. |
| `pipeline.py` | Stages 1–5 (gating+ranking), anti-look-ahead, reuses D51 not-extended gate. Self-test. |
| `run_funnel.py` | `run_real(universe, spy)` for the engine; `_smoke()` synthetic mechanics demo. |
| `ledger.py` | `screener_v2_picks` schema + forward head-to-head tracker (expectancy-led, ÷6, n<30 DESC). Self-test. |
| `screener_v2_status.json` | day-0 status: synthetic funnel + ACCRUING head-to-head + review line. |
| `D53_report.md` | the funnel report, caveats, verdict. |

## Run
```
python3 screener_v2/pipeline.py      # stage self-test + anti-look-ahead proof
python3 screener_v2/ledger.py        # ledger / head-to-head self-test
python3 screener_v2/run_funnel.py    # SYNTHETIC funnel (mechanics only, NOT proof)
```

## Engine hand-off (where the REAL funnel runs)
This repo has no universe/price/fundamentals feed. In the engine repo:
```python
from screener_v2 import run_funnel
out = run_funnel.run_real(universe, spy_bars)   # universe={tk:{"bars":[...], "fundamentals":{...}|None}}
# -> out["funnel"] (real survivor counts), out["qualified"] (top-decile picks, full record)
# then log out["qualified"] into screener_v2_picks forward; stamp outcomes at close;
# feed closed trades to ledger.head_to_head(v2_closed, current_closed) for the weekly review line.
```
Bars must be sliced to point-in-time (the pipeline enforces `bars[0..signal]`, but feed it
real point-in-time data). Earnings overlay activates only if `fundamentals` is supplied;
otherwise it stays DEFERRED (never a silent pass).

## Status: SHADOW (planting)
Day-0 verdict = **ACCRUING**. Nothing loaded. Current engine remains the sole live source of
truth. v2 earns promotion only by beating it forward over n≥30 after the haircut.
