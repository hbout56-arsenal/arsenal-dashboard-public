# Dispatch 53 — screener_v2: parallel pro-faithful screener (SHADOW · build, don't load)

A ground-up Minervini/O'Neil/Zanger/CANSLIM **gating+ranking** pipeline, built as a
**separate parallel pipeline**. It logs its **own** forward pick ledger head-to-head vs
the current engine and **never touches/replaces/feeds** the live screener, email, or
dashboard selection. Promotion to live comes ONLY if v2's forward picks beat the current
engine's forward picks over **n≥30, haircut-applied, + explicit go**. This is **planting**,
not harvesting. `SIMULATED / advisory.`

---

## 0. Scope honesty (same wall as D50/D51)
This repo has **no universe, no OHLCV, no fundamentals feed**. So the **real funnel must
run in the engine repo** (Polygon + the universe) via `run_funnel.run_real(universe, spy)`.
Here I built + self-tested the full pipeline and ran the funnel on a **SYNTHETIC fixture**
to prove the mechanics end-to-end. **The synthetic funnel is NOT a real funnel and NOT
proof** — it is survivorship-biased by construction and labelled SYNTHETIC everywhere.

---

## 1. Architecture — gating+ranking (reject first, then rank)
| stage | role | gate (frozen — see `preregistration_v2.json`) |
|---|---|---|
| 1 trend_template | HARD GATE (binary) | px>50>150>200, all rising, 200 rising ≥22d, ≥25% above 52w-low, ≥75% of 52w-high |
| 2 liquidity/quality | GATE | ADV ≥ $20M; earnings overlay **DEFERRED** unless a feed exists (None, never a silent pass) |
| 3 vcp | SETUP GATE | ≥2 contractions each ≤0.75× prior (zigzag, 4% reversal), vol dry-up ≤0.85× base, base ≤35%; else **WATCH** |
| 4 rs_rank | RANK | IBD-weighted RS vs SPY (0.4/0.2/0.2/0.2 over 63/126/189/252d); take **top decile** |
| 5 entry | ENTRY | **D51 not-extended gate** at pivot + vol-confirm ≥1.4× + structural stop + measured-move target + risk_model size |

Key difference vs today's **scoring** engine: most of the universe **dies at the gate**
before anything is ranked. Stage 5 **reuses the already-validated D51 gate** (imported, not
duplicated).

## 2. The funnel (SYNTHETIC SMOKE — mechanics only, NOT proof)
```
universe=7 -> stage1=5 -> stage2=4 -> stage3_vcp=2 -> stage4_top=1   (watch=3)
```
The gate **bites correctly** (not 0, not all):
- **DOWNTREND, CHOP** → rejected at Stage 1 (hard trend template).
- **THIN** → rejected at Stage 2 (liquidity floor).
- **VCP_B** (no valid contraction), **NO_DRYUP** (volume not drying) → **WATCH** (qualified name, no setup yet — not a buy).
- **VCP_A** → **WATCH** (valid VCP but below the top RS decile).
- **VCP_C** → **QUALIFIED** (top decile), full record below.

**Sample QUALIFIED pick (full record):**
```
VCP_C  pivot 293.11 · base_depth 24.0% · contractions 3 (24→14→8) · RS 6.608 rank 1.0
       entry vol 2.0x · not_extended True · stop 222.76 (below base) · target 363.46 (measured move) · S5 PASS
```
> On a real universe of thousands this funnel yields a **tight watchlist of strong setups**.
> Here it is 7 synthetic names → 1 qualified, which is the *correct* top-decile mechanic, not
> an edge claim.

## 3. Forward ledger + head-to-head (the whole point)
`ledger.py` logs `screener_v2_picks` (per pick: stage-pass record, VCP base, RS rank,
pivot/stop/target, regime_at_signal, timestamp; outcome stamped at close) and tracks v2
**forward** vs current-engine **forward**, expectancy-led, ÷6 haircut, n<30 DESCRIPTIVE,
FORWARD never blended with HISTORICAL.

**Day-0 status (`screener_v2_status.json`):**
```
screener_v2 vs current engine — v2 n=0 (exp n/a), current n=0 (exp n/a)
· ACCRUING — keep logging (need n>=30 both sides)
```
A day-0 forward verdict is impossible by construction — you plant, then wait. Promotion to
live selection requires **n≥30 forward beat + ÷6 haircut + explicit go**; until then v2 is
**SHADOW** (logs, never trades).

## 4. Anti-look-ahead proof
- `python3 screener_v2/pipeline.py` → `SELF-TEST PASS — funnel bites …, no look-ahead leak,
  earnings deferred==None`. Stage-1 and Stage-3 verdicts at a mid index are **identical on
  the full vs truncated series** (asserted); every stage reads `bars[0..signal]` only.
- `python3 screener_v2/ledger.py` → `SELF-TEST PASS — day0 ACCRUING, n<30 DESCRIPTIVE,
  n>=30 beat eligible, ledger row well-formed`.

## 5. Verdict / status
- **Built, self-tested, NOT loaded.** Pipeline + ledger + runner + frozen pre-registration.
- **Nothing wired into the live engine/email/dashboard.** Current engine remains the sole
  live source of truth (RAW control untouched).
- **Open hand-off to the engine repo:** call `run_funnel.run_real(universe, spy_bars)` on the
  real point-in-time universe to get the **real** funnel; begin logging `screener_v2_picks`
  forward; surface `review_line` in the weekly R&D review. Earnings overlay activates only if
  a fundamentals feed is wired (else stays DEFERRED).
