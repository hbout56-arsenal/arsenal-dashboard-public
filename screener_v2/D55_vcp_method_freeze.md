# Dispatch 55 follow-up — VCP method frozen (ZigZag = accepted bug-fix); FTEC stands

Hany's decision: the degenerate D50 reference VCP detector was a **bug**; the faithful
**ZigZag** detector is the correct implementation and is now **frozen**. FTEC stands as the
canonical lone qualifier for 2026-06-26. `SHADOW — educational, forward-validating, not a live signal.`

## 1. VCP method pre-registration (FROZEN) — `screener_v2/vcp_method_prereg.json`
- **detector_id:** `zigzag_v1_prereg_2026-06-29`
- **detector:** ZigZag swing-finder (reversal registered only after price moves ≥ `swing_reversal_pct` off the running extreme; pullback depths = swing-high → next swing-low; require ≥2 tightening contractions, vol dry-up, base ≤35%).
- **Frozen constants:** `swing_reversal_pct = 4.0` (the knob the funnel is most sensitive to — count swings ~0–4; **now pre-registered at 4.0**), `min_contractions 2`, `tightness 0.75`, `vol_dryup 0.85`, `max_base_depth 35%`, `base_window 60`.
- **This is the LAST post-hoc method change.** From here the method is frozen; any future change is a NEW pre-registered decision with its **own** forward series.
- Mirrored as a pointer in `preregistration_v2.json → stage3_vcp.vcp_method_frozen`.

## 2. Honesty note added to the tab (D54)
The Pro Screener tab now renders (verified headless against the **real** `screener_v2_funnel.json`):
- **Method note (constant):** "VCP detector = ZigZag (bug-fix replacing the degenerate D50 reference); method pre-registered 2026-06-29. FTEC is the first qualifier under the frozen method. SHADOW — educational, forward-validating, not a live signal."
- **Representativeness flag:** "◉ 0 single stocks qualified — survivor(s) are correlated tech ETFs. Watch whether single stocks clear as the frozen method runs weekly."
- **Honest read:** surfaces the engine's `honest_read` verdict (**TOO STRICT** at stage3_vcp) + notes.
- **ETF flag** on each setup (FTEC: "◉ ETF — not a single stock").

## 3. FTEC re-tag (forward ledger — engine-owned)
FTEC's forward pick **`V2_FTEC_20260626`** must be tagged `detector="zigzag_v1_prereg_2026-06-29"`
in `screener_v2_picks` so the head-to-head series is unambiguous from here. The tab already
renders a per-pick `detector` field when present.

## 4. Engine emit spec (so these persist through regeneration)
`screener_v2_funnel.json` is engine-regenerated each run. To make the annotations durable,
`run_real()`/publish should emit, going forward:
```json
"vcp_method": {"detector":"ZigZag","detector_id":"zigzag_v1_prereg_2026-06-29","frozen_at":"2026-06-29","swing_reversal_pct":4.0},
// and on each qualified pick:
"detector": "zigzag_v1_prereg_2026-06-29"
```
And tag the `screener_v2_picks` ledger row for `V2_FTEC_20260626` with the same `detector` id.
(The tab degrades gracefully if these are absent — the method note is a constant; `honest_read`
+ `is_etf` are already emitted by the engine.)

## 5. Open flag (monitor, do NOT tune)
Both survivors (FTEC, IYW) are correlated tech-sector ETFs; **0 single stocks** cleared this
session. If, after several weekly runs under the frozen method, single stocks ~never qualify,
a loosening is a **separate pre-registered decision** with its own forward series — never a
quiet tweak. Reported, not tuned.

## Regression / privacy
`node --check` clean · 0 conflict markers · no existing `ghFetch` changed · all prior panels
intact · backup `backups/index.html.D55.bak`. Privacy: levels + size band (%/R) only, no $/positions.
