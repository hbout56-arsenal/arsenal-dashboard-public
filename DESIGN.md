# Arsenal Dashboard — Design Standard (Dispatch 46)

Every panel, every tab, every future build follows this. Presentation only — it never
changes data, signals, or engine logic. The dashboard must read fast and calm under
pressure: the answer first, the "why" one tap away, the diagnostics out of the way.

## 1. Information hierarchy — top-to-bottom on every tab

1. **STATUS BAR** (always visible, top, sticky). One consolidated block: regime badge +
   posture + feed FRESH/STALE + a one-line "what's actionable right now." If the feed is
   STALE/FROZEN it shows **one loud banner** — never scattered warnings.
2. **THE ANSWER** (the actionable layer). The deployable-edge state, any live/triggered
   setup, the decision level. What you act on. Always open.
3. **CONTEXT** (collapsible `<details>`, closed by default). Scorecards, pillar tables,
   breadth/internals detail, regime sub-reads, confluence — the "why," one tap away.
4. **DIAGNOSTICS** (collapsible, closed by default). n<30 DESCRIPTIVE tables, raw signal
   rows, controls (OFF-WINDOW, HISTORICAL baseline), method notes.

## 2. Tabs

Order: **Overview · Futures · Stocks/Swing · $15K / Risk · Journal · Alerts.**
Each tab opens with an H2 heading + one plain-language line: "what this tab is for."
Overview = the at-a-glance answer across books; it reuses already-fetched sources only
(no new data fetch).

## 3. Colour standard (consistent, accessibility-safe — tokens are the single source of truth)

Defined once in `:root`; never hardcode a semantic hex again — use the token.

| token | meaning | use |
|---|---|---|
| `--pos` / `--pos-ink` | GOOD · confirmed · go-aligned | green |
| `--neg` / `--neg-ink` | BAD · stop · loss | red |
| `--warn` / `--warn-ink` | CAUTION · wait · stale-ish | amber |
| `--info` / `--info-ink` | INFORMATIONAL · context-only (non-voting pillars) | blue |
| `--idle` / `--dim` | INACTIVE · N-A · no-vote | grey |
| `--pal-stock/mgc/mcl/mes` | categorical instrument palette — **NOT semantic** | per-instrument bars only |

Rules:
- **Never use colour as the only signal.** Pair every colour with an icon or word
  (✓ go · ✗ stop · ◉ caution · — N/A · ● live) for colourblind safety.
- Honesty states keep their mapping: **FROZEN red · DARK/STALE amber · LIVE green ·
  SESSION-CLOSED grey.**
- A small **legend, collapsible, closed by default**.

## 4. Help & readability

- **An (i) tooltip on every panel** — one plain-language sentence: what it is, how to read
  it, and its honesty tag (validated `n≥30` vs descriptive `n<30` vs informational/non-voting).
  Reuse the honesty lines already written. Implemented via `hI(key)` (the icon) + `hP(key)`
  (the panel) reading the shared `HELP` map; add new keys there, don't inline copy.
- **Plain language in headings; precise terms in the tooltip.** e.g. heading "What's working
  right now," tooltip "edge × regime cross-tab."
- **Collapse walls of repeated rows.** A HOLD/HOLD/N-A signal block shows a one-line summary
  ("Internals: no vote — feed stale") with the full per-signal breakdown behind a drop-down.
- **No honesty caveat is ever dropped** (SIMULATED · n<30 · context-not-trigger ·
  price-is-the-trigger · DELAYED · STUDY/control). They move into the tooltip or the
  Diagnostics drawer, never disappear.

## 5. Shared components (use these so every panel is consistent + future-proof)

- `statusBar(prefix, {...})` — the level-1 sticky status block.
- `section(title, bodyHTML, {helpKey, level, open})` — a panel with a plain heading, an
  optional (i), and a `level` of `answer | context | diagnostics`. `context`/`diagnostics`
  render as `<details>` closed by default; `answer` renders open.
- `oneLineThenDetails(summary, fullHTML)` — the HOLD-wall collapser.
- `tag(kind, text)` — a coloured-with-word chip (`pos|neg|warn|info|idle`).

A new panel = call `section(...)` at the right `level` with an `hI/hP` help key. That is the
whole contract — placement, colour, collapse, and help all come for free and stay consistent.

## 6. Regression guard (every change, hard — D29)

Before pushing any presentation change: back up `index.html`; every prior panel still present
and still bound to the **same** `ghFetch` source (diff the data-binding set — it must be
byte-identical unless a merge is explicitly listed); 0 conflict markers; `node --check` clean;
headless-render every tab; confirm no `ghFetch` URL changed. Push only when all pass.

## 7. v2 (2026-10-26) — the simplified front page

`index.html` is now the 4-screen page (NOW · SETUPS · EDGE · STRUCTURE); the full 19-view page is
preserved unchanged as `index_full.html` and linked from STRUCTURE → Feeds. Rules that produced v2:

- **One ladder, not five panels.** ICT pools, FVG gaps, VP/FIB confluence, swing levels, newsletter
  levels and meter guidance merge into a single price-sorted ladder with a source tag per row.
- **Doctrine on the front screen.** Slope gates v3.1 (30-row LSQ on ADD/VOLD/TRIN, 10%-of-level
  magnitude rule, <15 rows or stale feed = UNRELIABLE) and the three Playbook v3 cards (Washout Long,
  Cluster Fade, Failed Retest) are computed in the page from `internals_snapshot.json`.
- **Evidence decides what is shown as actionable.** EDGE splits every scorecard track into
  working (n≥30, CI excludes 0, exp>0), measured no-edge (retired from NOW/SETUPS, still logged),
  and accruing (n<30). SETUPS lists only validated buckets (convergence-HIGH, PULLBACK_LONG,
  BOUNCE_SHORT) plus clearly-tagged informational shadows (Minervini reset, ORB A+, ICT in killzone).
  STRONG_LONG at-market (forward −2.4%/trade) and ES EMA 5m/15m scalps (all negative) are not shown.
- **No new data fetch.** v2 binds only to files already in the allowlist; nothing in push_public_display changed.
