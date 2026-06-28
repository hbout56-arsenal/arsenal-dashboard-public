# Dispatch 51 — ship the validated not-extended exclusion gate (LOAD ON REVIEW)

Ships **only** D50 Filter 5 (not-extended / no-chase) — the one filter that cleared
the bar on forward data (+8.88 pts/trade, both legs n≥30, survives ÷8 haircut).
Filters 1-4/6/7 stay **DEFERRED** (D52). `SIMULATED / advisory.`

## What shipped
| file | role |
|---|---|
| `screener_pro/not_extended_gate.py` | production gate (loadable). `evaluate()` / `tag_pick()`. FROZEN D50 thresholds, anti-look-ahead, self-test. |
| `not_extended_gate.json` | dashboard data: frozen thresholds, honesty line, RAW-vs-gated forward comparison, sample tagged picks, anti-look-ahead proof. |
| `index.html` (additive) | per-pick CLEAN/EXTENDED chip in `pickRow`; "Not-extended gate — VALIDATED" panel; `notext` HELP entry; best-effort `ghFetch`. |

## Frozen thresholds (pre-registered — NOT re-tuned)
EXTENDED if **any**: entry > **5×ATR(14)** above pivot · price > **12%** above 50-MA · **RSI(14) ≥ 80**.

## Sample picks (worked example, frozen thresholds, from the self-test)
```
CLEAN_DEMO  LONG  ATR>pivot 0.44 ·  1.08% >50MA · RSI 45.5  → ✓ not-extended (KEPT)
EXT_DEMO    LONG  ATR>pivot 8.14 · 45.25% >50MA · RSI 94.3  → ✗ EXTENDED  (gated, all 3 rules trip)
```

## Anti-look-ahead proof
`python3 screener_pro/not_extended_gate.py` →
`SELF-TEST PASS — clean kept, extended gated, no look-ahead leak`.
ATR/SMA50/RSI read `bars[0..signal_index]` only; the verdict at a mid index is
byte-identical on the full vs truncated series (asserted).

## RAW control preserved
- Gate **flags & demotes**, never deletes (`tag_pick` adds `extended`/`gate_status`;
  the engine demotes EXTENDED to context-only — the pick still logs).
- Dashboard chip renders **only when a pick is tagged**; untagged picks are visually
  unchanged → the ungated RAW series keeps logging and rendering as the control.
- `not_extended_gate.json` surfaces the **RAW ungated control** leg alongside the
  clean/excluded legs so the comparison keeps accumulating.

## Forward read after gating (ties to D50 expectation)
| leg | n | exp | PF | win% |
|---|---:|---:|---:|---:|
| RAW (ungated control) | 396 | −2.40% | 0.43 | 35.1 |
| ✓ CLEAN — kept (pullback_limit) | 291 | −0.04% | 0.98 | 42.3 |
| ✗ EXTENDED — excluded (at_market) | 105 | −8.92% | 0.09 | 15.2 |

Gap **+8.88 pts/trade**, after ÷8 haircut **+1.11**; excluding extended lifts the
blended series **+2.35 pts** (−2.40% → −0.04%). Matches D50 exactly.

## Regression guard (D29)
- `node --check` on the extracted main script: **clean**. 0 conflict markers.
- Prior panels present (curated / engine-top5 / scorecard / EMA). Only **one** new
  `ghFetch` (`not_extended_gate.json`); no existing data-binding changed.
- Backup: `backups/index.html.D51.bak` (md5 `c24e95df…`, the pre-D51 file).

## Decision log — pivot source for the ATR-extension leg (recorded, not silent)
The engine wires the gate with `gate.tag_pick(view_pick, sliced, len(sliced)-1, pivot=None)`
(`gate_apply.py:121-124`). With `pivot=None` the module falls back to the **50-MA** as the
pivot, so the *"X×ATR above pivot"* leg measures extension above the **50-day MA structure**,
not above the specific breakout pivot named in pre-registered rule #5.

- **Anti-look-ahead: certified.** `sliced = bars[:i+1]` (i = last bar on/before signal date);
  the module only ever sees `bars[0..signal]`. Verified live: 13/13 tags internally consistent
  with the frozen thresholds.
- **Side effect (accepted):** the "ATR-above-pivot" and "%-above-50-MA" legs are then both
  50-MA-anchored, so they partly measure the same distance. RSI(80) and the %-above-50-MA leg
  are unaffected.
- **DECISION (option 1):** **keep `pivot=None`** for this cycle. It is the behavior that was
  validated this run, it is conservative, and it changes no thresholds (no re-tune). Passing the
  true breakout pivot is a deliberate fidelity refinement deferred to **D52**, to be logged as a
  tracked config change (it would shift some verdicts), not swapped mid-cycle.
- **Make it explicit in the artifact:** the engine should stamp `pivot_source` into the
  generated `not_extended_gate.json` (e.g. `"pivot_source": "50MA_fallback (pivot=None)"`) so
  the live data records which anchor produced the tags.
