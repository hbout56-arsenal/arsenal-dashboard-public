# sentinel/ — MGC inside-bar forward test (DETECTION-ONLY, DISABLED)

A pre-registration + detection-only alert leg to earn the `inside_bar` **GC_RAW** track
forward. In-sample GC_RAW is the system's best track (exp **+63.67 pts**, n **71**,
PF **7.05**, win **74.6%**) but is **suspected regime capture** — one gold bull market,
plus a raw-beats-filtered inversion. This tests whether it survives outside that regime.

**Nothing here executes, sizes, or votes.** It is SHADOW / DESCRIPTIVE.

## Files

| file | role | state |
|---|---|---|
| `mgc_inside_bar_prereg.TEMPLATE.md` | Part 1 pre-registration | **TEMPLATE — freeze on the Mac** |
| `mgc_inside_bar_sentinel.py` | Part 2 detection-only detector + guard + debounce + ledger writer | **DISABLED** (`ENABLED=False`) |
| `com.arsenal.mgc_inside_bar_sentinel.plist` | launchd job | **DISABLED** (`Disabled=true`) template |
| `mgc_inside_bar_scorer.py` | Part 3 forward scorer (gates + bootstrap CI) | reference, not loaded |
| `mgc_inside_bar_scorecard_publisher.py` | public summary projector → `../mgc_inside_bar_scorecard.json` | reads PRIVATE ledger; summary-only |
| `mgc_inside_bar_forward.csv` | Part 3 forward ledger | header only (0 armed) |
| `fixtures/gc_daily_inside_bar_fixture.json` | real daily GC rows for the selftest | verbatim from `gc_bars_daily.json` |

## Public/private split (operator-confirmed)

- **PRIVATE** (backup repo + `~/arsenal/ledgers/`): detector, frozen §1 prereg, and
  `mgc_inside_bar_forward.csv` (full per-trade rows: entry/stop/target/regime tag).
  Lives beside `mes_event_labels.csv` — they share the scorer.
- **PUBLIC** (this dashboard repo): `mgc_inside_bar_scorecard.json` **only** — n,
  expectancy, CI, gate, kill-criteria state, `generated_at`. No rule, no per-trade rows.
  Mirrors `es_swing_scorecard.json`.
- The publisher **never reads a ledger from the public repo**: ledger path comes from
  `$MGC_IB_LEDGER` / `--ledger`, defaulting to the private
  `~/arsenal/ledgers/mgc_inside_bar_forward.csv`. Absent ledger → `n=0 / ACCRUING /
  not-yet-armed` (never errors).
- **Sequence (do not reorder):** the Mac creates the private home (code + ledger) and
  freezes §1 → *then* public PR #18 trims down to the scorecard. **Never delete from
  public before private exists.** Freeze / arm / plist paths / D110 column reconciliation
  are the Mac's job; this public session's work ends at the publisher.

## Why it lives here, and what's deferred

`inside_bar_engine.py`, the live sentinel family, the plists, and `~/arsenal/ledgers/`
live on the Mac and are **not** in this public mirror. Per operator decision:

- **Part 1 is deferred to the Mac** — the verbatim GC_RAW rule freeze can only be done
  where the engine source is. `mgc_inside_bar_prereg.TEMPLATE.md` §2–§7 are pre-filled
  from the dispatch and ready to lock; §1 (the rule dump) is a TODO to fill from source.
- The sentinel's coded geometry (inside-bar definition, break trigger, structural stop)
  mirrors the dashboard's stated setup; the **target is a PROVISIONAL 1R placeholder**
  pending the §1 freeze. Reconcile all four against `inside_bar_engine.py` before arming.

## Two guards, both must flip (on the Mac, after the freeze)

1. code: `ENABLED = False` in `mgc_inside_bar_sentinel.py`
2. launchd: `Disabled=true` + `RunAtLoad=false` in the plist

Plus: reconcile the plist placeholder paths (`/Users/REPLACE_ME/...`) and confirm the
ledger column names against the **D110 labeler** so the scorer can share it.

## Selftests (production-shaped, real fixture — the tz-bug lesson)

```
python3 sentinel/mgc_inside_bar_sentinel.py --selftest   # 8 checks
python3 sentinel/mgc_inside_bar_scorer.py   --selftest   # 8 checks
```

The detector selftest consumes **real daily GC rows** (`fixtures/…`, epoch-ms `t`,
o/h/l/c/v) pulled verbatim from `gc_bars_daily.json` — **tz-aware** datetimes, real row
schema, an actual **2026-07-09** inside bar for the positive case and **2026-07-13** for
the negative. It also asserts: guard-off never fires, 10-min debounce, no order/exec
text in any alert, anti-look-ahead on the regime tag, and the ledger-row shape.

## Alert & ledger

On an armed inside bar the detector emits `SETUP ARMED: MGC INSIDE BAR @ <price>` plus
the last few bars, and appends **one ARMED row** (not a taken trade) to
`mgc_inside_bar_forward.csv`. The nightly triple-barrier labeler stamps
direction/outcome/`net_points` (net of costs + 1 tick slippage). Weekly brief comes from
the scorer, tagged **DESCRIPTIVE** until the §4 gates clear.
