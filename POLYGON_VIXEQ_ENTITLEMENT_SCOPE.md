# Scope — Can Polygon serve VIXEQ (and DSPX / COR1M)?

**Status:** SCOPE ONLY (no live wiring). Date: 2026-08-05.
**Question:** Your key already serves `VIX9D / VIX / VIX3M` via the Polygon indices
snapshot — are `^VIXEQ`, `^DSPX`, `^COR1M` in the *same* entitlement?

**Determination:** **Yes — same entitlement, no extra Polygon cost expected.** One
listing check remains that must be fired from the box that holds the key (MAC-LOCAL);
it could not be run from the web/remote session that produced this doc because the
Polygon key is not present here. Command is in §3.

---

## 1. What the three targets are

| Ticker | Cboe name | What it measures | Update cadence |
|---|---|---|---|
| `^VIXEQ` | Cboe S&P 500 Constituent Volatility Index | Cap-weighted RMS 30-day *single-stock* implied vol of an S&P 500 constituent basket | ~15s |
| `^DSPX` | Cboe S&P 500 Dispersion Index | Implied 30-day dispersion, `DSPX = sqrt(VIX² − VIXEQ²)` | ~15s |
| `^COR1M` | Cboe 1-Month Implied Correlation Index | Avg implied correlation of S&P 500 constituents | ~15s |

`VIXEQ` is the newest of the three (S&P DJI × Cboe, announced 2024) and is a **direct
input to DSPX** — so if `VIXEQ` lists on Polygon, `DSPX` almost certainly does too.

## 2. Why it is the same entitlement

1. **Polygon Indices is one plan, not per-family.** The Indices asset class is a single
   subscription (Starter / Developer / Advanced). Tiers differ by real-time vs 15-min
   delayed, history depth, and rate limit — **never** by which Cboe index families are
   included. There is no separate "VIX family" vs "dispersion/correlation" entitlement to buy.
2. **Same source feed.** VIX9D/VIX/VIX3M **and** DSPX/COR1M/VIXEQ all ride the **Cboe
   Global Indices Feed (CGIF)** — the same Cboe stream Polygon ingests. They are not a
   premium sub-feed; they sit alongside SPX/VIX in CGIF.
3. Therefore a key that already returns the VIX term structure from Polygon's indices
   snapshot is, by construction, on the Indices plan riding CGIF — the same plan that
   carries these three. The open question is **Polygon coverage/listing**, not entitlement.

## 3. The one check to run on the Mac (needs the key)

Reference-tickers listing (does Polygon carry them at all):

```bash
for T in VIXEQ DSPX COR1M; do
  curl -s "https://api.polygon.io/v3/reference/tickers?market=indices&ticker=I:$T&apiKey=$POLYGON_KEY" \
    | python3 -c "import sys,json;d=json.load(sys.stdin);print('I:$T ->', d.get('results') and d['results'][0].get('name') or 'NOT LISTED')"
done
```

Live value (confirms the snapshot actually returns a level, same call shape as the VIX pull):

```bash
curl -s "https://api.polygon.io/v3/snapshot/indices?ticker.any_of=I:VIX,I:VIXEQ,I:DSPX,I:COR1M&apiKey=$POLYGON_KEY" \
  | python3 -m json.tool
```

- All three return a `name` / a `value` → **entitled + listed → proceed to §5.**
- `NOT_FOUND` / empty `results` for a ticker → **listed-coverage gap** (not an entitlement
  wall). Go to §4 for that ticker only.

## 4. If a ticker is NOT listed on Polygon — cost / alternatives

No Polygon upsell fixes a *coverage* gap; the fallbacks are per-ticker and cheap:

| Option | Cost | Latency | Notes |
|---|---|---|---|
| Cboe delayed EOD file (CGIF end-of-day) | Free | EOD | Fine for a *daily* log; ratio+z is a daily read anyway. |
| Yahoo `^VIXEQ` / `^DSPX` / `^COR1M` | Free | ~15-min delayed | Already-quoted symbols; matches how SOX/VIX are DELAYED-tagged in the dash. |
| dxFeed CGIF real-time | Paid feed | RT | Overkill for a daily context flag — do not buy for this. |
| Cboe index licensing (`index_data@cboe.com`) | Paid / license | RT | Only if this ever became a *gating* input. It won't (see §5). |

**Recommendation if unlisted:** use the free Cboe/Yahoo delayed daily value and tag the
row DELAYED. Do **not** buy anything — this is a once-a-day context flag, not a trigger.

## 5. Conditional implementation spec (only if §3 passes)

Honesty-tagged per `DESIGN.md`. **CONTEXT FLAG ONLY — never a gate, never votes.**

- **Signal:** log the `VIXEQ / VIX` ratio daily with a rolling z-score, alongside the
  existing term-structure line.
  - `VIXEQ ≥ VIX` always (constituent vol ≥ index vol when correlation < 1), so the
    ratio ≥ 1 and is a monotone read on dispersion: **higher ratio → lower correlation →
    high dispersion → rotation / stock-picker's tape**; ratio → 1 → high correlation →
    macro risk-on/off, index moves as one block. (This is why it's the rotation read.)
  - `COR1M` and `DSPX`, if listed, log as corroborating columns — same story, no new math.
- **Rolling z:** trailing window (start 60 trading days; document the choice), z of the
  daily ratio. Store history so z is reproducible.
- **Where it lands:** MAC pipeline writes a new `rotation_regime.json`
  (`{ date, vixeq, vix, ratio, z, cor1m, dspx, window, source, honesty }`). The dashboard
  reads it via `ghFetch` like every other source — **no dashboard change ships until that
  JSON exists** (DESIGN.md regression guard: no new fetch source without data).
- **The 10:00 read:** surface a `ROTATION_REGIME` tag (e.g. z ≥ +1 → "DISPERSION /
  rotation-friendly"; z ≤ −1 → "CORRELATED / macro block"; else "neutral"). Context tag in
  the read **only** — it sizes/frames nothing, generates no trade, casts no vote. Price
  stays the trigger.

## 6. Bottom line

Entitlement is not the blocker — the same Polygon Indices plan + CGIF source that gives you
the VIX term structure covers VIXEQ/DSPX/COR1M. Run the §3 listing check on the Mac; if it
returns levels, wire §5; if a ticker is missing, take the free delayed fallback in §4 and
buy nothing.
