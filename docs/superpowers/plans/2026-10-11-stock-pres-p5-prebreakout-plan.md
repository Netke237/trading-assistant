# STOCK-PRES-P5-PREBREAKOUT — Pre-Breakout setup scanner in the Options layout

Phase id: `STOCK-PRES-P5-PREBREAKOUT` · Board item / tracking issue: **#150** · Programme: #144
Branch: `board/stock-pres-p5-prebreakout-2e4085d3` (cut from `main` `48ff4ce9`)
Design: `docs/superpowers/specs/2026-10-10-stock-presentation/` (`preview.html` → Pre-Breakout view,
`prebreakout.png`, README D1–D14) · Decision: `STOCK-PRESENTATION-2026-10-10`

## Why

The Pre-Breakout setup scanner still has its pre-redesign layout. Kenneth approved proposal 02 (D9): the same
page in the Options layout, **every existing item kept with today's text and behaviour**, plus the approved NEW
items for this page (README "New items": confidence breakdown, "Why it's a setup" inline, mini chart, Fib swing
low/high; "How this page works" for all pages). D3: no Position handoff — it stays a scanner + watch/alert
tool. D14: **presentation only; must not pre-empt reconciliation ticket 10 "Pre-Breakout exit semantics"**
(`.scratch/project-ticket-reconciliation-20261009/issues/10-t4-exits.md`) — nothing here says or implies
anything about entries, stops, targets or exits.

## The gate (audit_rule)

A finding blocks only if it can put a **wrong number in front of a user or on a broker order**, or **corrupt
persisted data**. A comment blocks only if it misstates mechanism.

## Scope

**Files this phase may change (nothing else):**
- `frontend/app/(frame)/screener/step-4-prebreakout/page.tsx`, `page.module.css`, new files in that folder
  (`scanThresholds.ts`, `PreBreakoutRowDetails.tsx` or similar, `__tests__/**`)
- `frontend/components/organisms/CandlestickChart/index.tsx` and its `__tests__/` — **one additive optional
  prop** (T1), and `frontend/__mocks__/lightweight-charts.js` — add `removePriceLine` to the fake series (T1)
- `frontend/components/organisms/PreBreakoutParamsPanel/index.tsx` and `FibPullbackParamsPanel/index.tsx` —
  **display-only** lines, added after plan round 2 (R2-2, R2-3); see T2 item 1c. No prop, state, handler or
  layout change.
- this plan and `docs/superpowers/PROJECT_STATE.json` (coordinator only)

The item's "Touches" line names the page folder and the panels' placement. The CandlestickChart prop is the
one shared-component change, needed because the approved mini chart draws a swing-high / Fib level line and
the shared chart cannot draw a price line today. It is additive (absent prop = today's behaviour for every
existing caller); no in-flight board item touches that file (checked: #147's branch changes only docs).

**Out:** backend (the P1 fields already exist), `frontend/types/`, `scanStore` (no new field, no persistence
change, no `version` bump), `PreBreakoutParamsPanel` / `FibPullbackParamsPanel` internals (placed, not
edited), `CompositeAlertDialog`, `WatchStar`, `api.ts`, every scan request body, the confidence / metric
semantics, any entry/stop/exit wording.

## Mechanism today (verified on `48ff4ce9`)

- `step-4-prebreakout/page.tsx` (594 lines) renders a header (`Setup Scanner`; "Scanning {universeLabel} ·
  {direction}"), a three-button mode toggle (Pre-Breakout / Pullback to EMA {emaPeriod} / Fib Pullback, local
  `scanMode`), then per mode: a description text; the symbol-override textarea + Run Scan (`runScan`); the
  mode's parameters (Pullback: an inline `<details>` "Scan parameters" with EMA / trend EMA inputs + "Reset to
  defaults"; Pre-Breakout: `PreBreakoutParamsPanel`; Fib: `FibPullbackParamsPanel`, both self-contained
  `<details>` with Reset); the error line; the table; the empty state. One `CompositeAlertDialog` for
  `alertSymbol`.
- Results: Pre-Breakout → `scanStore.preBreakoutResults`, Fib → `scanStore.fibPullbackResults` (both
  in-memory only: **not** in `partialize`), Pullback → local `pullbackResults`. Only this page writes them.
- Params are **local `useState`, reset to the defaults on every mount**. An effect clears all results when
  params / universe / direction change **after** the first render. So within one mount the rows always match
  the current params, but after leaving the page and coming back the stored Pre-Breakout / Fib rows remain
  while the params are back to defaults.
- **Consequence (pre-existing, gate-relevant for this phase):** after a scan with non-default params and a
  remount, today's tooltips state the *default* thresholds ("Must be below 0.85 to pass…") against rows that
  were judged on other thresholds, and the Fib Distance cell's pass/caution tone uses the default tolerance.
  The approved "Why it's a setup" puts exactly these thresholds on screen as text, so this phase **ties every
  displayed threshold to the scan that produced the rows** (T2, `scanThresholds.ts`) and uses it for the
  existing tooltips too, so a row's tooltip and its detail can never disagree. The tooltip *text* is
  unchanged; only the source of the threshold number changes.
- The backend applies the page's 7 Pre-Breakout overrides on top of `strategy_params.yaml`
  `breakout_setup.active.<dir>` (`routers/stock_scan.py:2189-2210`), so the thresholds the page sent are the
  ones the rows were judged on. `fib_enabled` is never sent and is not in the active params, so Pre-Breakout
  rows normally carry 3 confidence components (atr / vol / proximity); the detail renders whatever the row's
  `confidence_breakdown.components` holds (4 with `fib`).
- P1 fields (`frontend/types/stockDomain.ts:82-107`): `PreBreakoutResultRow.confidence_breakdown`
  (`weights`, `components{score, weight, contribution}`, `unrounded`, `confidence`, `fib_used`) and
  `fib_swing {low, high}`; `FibPullbackResultRow.fib_swing`. Absent on rows from before P1 (cannot occur
  in memory after a reload, but the detail must not crash on `undefined`/`null`).
- Fib level price (for "61.8% level $159.63"): `strategy_engine._fibonacci_pullback_detail`
  (`backend/app/services/strategy_engine.py:192-205`): Bullish `high − r × (high − low)`, Bearish
  `low + r × (high − low)`, `r = _FIB_RATIOS[label]` (`:109-115`: 23.6→0.236, 38.2→0.382, 50→0.5,
  61.8→0.618, 78.6→0.786). The Fib route returns `fib_swing` from the same helper call
  (`routers/stock_scan.py:2153`).
- `CandlestickChart` (`components/organisms/CandlestickChart/index.tsx`) takes `data`, `height`,
  `showToggles`, `defaultIndicators`; it creates one candlestick series (`:95`, `candleSeriesRef`) and sets
  its data in an effect (`:153`). No price-line support. `api.getCandles(symbol)` (`lib/api.ts:602`) returns
  the daily candles `InlineChartPanel` already uses.
- Tests that exercise this page today: `frontend/lib/__tests__/p3aScanSizing.test.tsx` (Pullback request
  body). It must stay green unchanged.

## Target layout (preview.html → Pre-Breakout)

```
Header (unchanged text)
How this page works (NEW, collapsed)
Mode toggle (unchanged)
┌ main column ───────────────────────────────┐ ┌ side column (aside "Scan", ~300px) ───┐
│ Card: mode description (unchanged text)     │ │ Card "Scan": symbol textarea,          │
│   error line (unchanged)                    │ │   Run Scan / Scanning…,                │
│   table (unchanged columns + tooltips;      │ │   the mode's parameters (unchanged     │
│     Pre-Breakout and Fib get a ▸/▾ column)  │ │   component / block, Reset)            │
│   expanded row → details (NEW)              │ │ Card "What you can do" (static text)   │
│   empty state (unchanged)                   │ └────────────────────────────────────────┘
└─────────────────────────────────────────────┘
```

Cards: `border: 1px solid var(--border-subtle)`, no shadow, `var(--bg-surface)`, radius 8px, existing tokens
only (P4's `.panel` / `.cardTitle` / `.pageExplanation` rules, copied). Two columns
(`grid-template-columns: minmax(0, 1fr) 300px; gap: 16px; align-items: start`). The three table grids switch
their fixed pixel columns to `minmax(0, …fr)` tracks so the tables fit the main column at the 1280px minimum
without horizontal scroll (visual check under "Needs Kenneth").

## Acceptance — this phase's slice of the mapping (nothing removed)

| # | Item today | Where it goes | Kind |
|---|---|---|---|
| M1 | Header "Setup Scanner", "Scanning {universe} · {direction}" | Page head, same text | EXISTING |
| M2 | Mode toggle Pre-Breakout / Pullback to EMA N / Fib Pullback (`aria-pressed`) | Under page head, same | EXISTING |
| M3 | Mode description texts (3, incl. the live proximity % in the Pre-Breakout one) | Top of each mode card, same text | EXISTING |
| M4 | Symbol override textarea (placeholder) + Run Scan / "Scanning…" (disabled while scanning) | Side "Scan" card, same handler | MOVED |
| M5 | Params: Pullback EMA block + "Reset to defaults"; `PreBreakoutParamsPanel` + Reset; `FibPullbackParamsPanel` + Reset | Side "Scan" card, the current mode's only, unchanged inside | MOVED |
| M6 | Pre-Breakout table: watch, 📈, symbol, dir, confidence, ATR ratio, vol ratio, proximity %, Set Alert + tooltips; sorted by confidence | Main card, same columns and tooltip texts, + ▸/▾ column | EXISTING |
| M7 | Pullback table: watch, symbol, company, dir, score, price, confidence, Set Alert + tooltips | Main card, same, **no** details | EXISTING |
| M8 | Fib table: watch, 📈, symbol, dir, fib level, distance, at level, confidence, "+" alert + tooltips | Main card, same, + ▸/▾ column | EXISTING |
| M9 | `CompositeAlertDialog`, the three empty states (with today's differing conditions), the error line, the empty-universe messages | Unchanged | EXISTING |
| M10 | Tooltip facts (ratio vs threshold); swing level and range ratio (in the data, not shown) | "Why it's a setup" in the Pre-Breakout row details; tooltips stay | NEW |
| M11 | — | Confidence breakdown (P1 field) in the Pre-Breakout row details | NEW |
| M12 | — | Mini chart in Pre-Breakout and Fib row details | NEW |
| M13 | — | Fib swing low / high (P1 field) + level price in the Fib row details | NEW |
| M14 | — | "How this page works" | NEW |
| M15 | — | Side "What you can do" card (describes the existing actions) | NEW (static text) |

Plus: thresholds tied to the scan (T2); typecheck + full Jest green; plan audit and code audit clean.

## Tasks (test-first; one ticket each; T1 → T2 → T3, serial — T2 and T3 both edit `page.tsx`)

### Task 1 — `CandlestickChart` optional `priceLines`

**Files:** `frontend/components/organisms/CandlestickChart/index.tsx`, a new test in its `__tests__/`,
`frontend/__mocks__/lightweight-charts.js` (add `removePriceLine: jest.fn()` to `makeSeriesApi`; nothing
else in the mock changes).

**Change:** new optional prop `priceLines?: { price: number; title: string }[]`. An effect keyed on the
candle series (the same `chartVersion`/series lifecycle the data effect uses) and on a stable key of
`priceLines` (`JSON.stringify` of the array) creates one price line per entry with
`candle.createPriceLine({ price, title, color: token('--accent'), lineWidth: 1,
lineStyle: LineStyle.Dashed, axisLabelVisible: true })`, keeps the returned handles, and removes them
(`candle.removePriceLine(h)`) in its cleanup. Entries whose `price` is not a finite number are skipped (no
line, no throw). Absent or empty prop → no `createPriceLine` call: every existing caller is unchanged.

**Tests first (must fail before the change):** with the mocked library,
- `priceLines={[{ price: 201.4, title: 'Swing high' }]}` → the candle series' `createPriceLine` called once
  with `price: 201.4`, `title: 'Swing high'`;
- no prop → `createPriceLine` not called;
- `{ price: NaN }` entry skipped, a sibling finite entry still drawn;
- re-render with a different `priceLines` → the old handle passed to `removePriceLine`, the new one created;
- the existing `CandlestickChart` tests stay green unchanged.

**Commit:** `feat(chart): optional price lines on CandlestickChart (STOCK-PRES-P5-PREBREAKOUT T1)`

### Task 2 — Options layout, How this page works, What you can do, thresholds tied to the scan

**Files:** `step-4-prebreakout/page.tsx`, `page.module.css`, new `step-4-prebreakout/scanThresholds.ts`, new
`step-4-prebreakout/__tests__/presentationLayout.test.tsx` and `__tests__/scanThresholds.test.tsx`.

**Change (no logic change except the threshold source; every M1–M9 element keeps its JSX, props, conditions
and handlers):**
1. **Thresholds tied to the scan.** `scanThresholds.ts` holds module-level state with the same lifetime as the
   in-memory results (lost on reload together with them):
   `rememberPreBreakoutScan(p: PreBreakoutParams)`, `preBreakoutScanParams(): PreBreakoutParams | null`,
   `rememberFibScan(p: FibPullbackParams)`, `fibScanParams(): FibPullbackParams | null`,
   `fmtThreshold(x: number, minDecimals: number): string` and `__resetScanThresholdsForTests()`.
   **The remembered values are the ones the backend applied** (plan round 1, F3): the inputs are free-typed
   numbers, and the backend coerces the integer keys with Python `int()` (truncation toward zero;
   `routers/stock_scan.py` `_INT_OVERRIDE_KEYS` / `_FIB_INT_OVERRIDE_KEYS`) and uses the floats as sent. So
   `remember*` stores `Math.trunc(v)` for `atrAvgLookback`, `rangeLookbackBars`, `swingLookback` (Fib:
   `fibSwingLookback`) and the floats unchanged. **Every threshold the page prints** (existing tooltips, the
   description, the new detail lines) goes through `fmtThreshold`. It returns the value without lossy
   rounding: `Number(x.toFixed(6))` as a string, padded with zeros to at least `minDecimals` decimals. So
   0.85 → "0.85", 3 → "3.0" with minDecimals 1, 0.875 → "0.875", 2.75 → "2.75". Percentages format
   `x * 100` the same way: 0.08 → "8.0", 0.0725 → "7.25". At today's step values the printed text is
   byte-identical to today's. In `runScan`, call `rememberPreBreakoutScan(params)` immediately before
   `setResults(results)` and `rememberFibScan(fibParams)` immediately before `setFibResults(results)` — the
   **same closure values** the request was built from, so a param change while a scan is pending still
   pairs the rows with the params they were judged on.
   The page reads `const scanned = preBreakoutScanParams() ?? params` and `const fibScanned = fibScanParams()
   ?? fibParams` at render. The `?? params` fallback is only reached with no rows in memory (no scan yet this
   page load), where no threshold is displayed against a row.
   Every **existing tooltip** that prints a threshold (ATR ratio `atrCompressionRatio`, Vol ratio
   `volCompressionRatio`, Proximity `resistanceProximityPct`) and the Fib Distance cell (its tone and its
   tooltip's tolerance) read `scanned` / `fibScanned` instead of the live params. Tooltip **wording is
   unchanged**. The Pre-Breakout mode description's proximity % (M3, "close within …% of swing high") reads
   `scanned` **while Pre-Breakout rows are in memory**, because it then sits directly above rows judged on it,
   and the live params otherwise (plan round 1, F1). The **Fib description's level list** ("Stocks retracing to a key Fibonacci level (38.2%, 61.8%) …")
   is also a scan parameter (`fib_levels`; the panel lets the user pick any subset of 23.6 / 38.2 / 50.0 /
   61.8 / 78.6, and the backend measures only those). It follows the same rule (plan round 2, R2-1):
   `(fibScanned or fibParams).fibLevels.map((l) => `${l}%`).join(', ')` — `fibScanned` while Fib rows are in
   memory, the live params otherwise. The panel keeps the array sorted, so the defaults print exactly
   "38.2%, 61.8%" as today. The Pullback description prints no threshold (its rows are local state, cleared
   on every remount).
1c. **Every printed lookback and percent equals the applied value** (plan round 2):
   - R2-2: the ATR Ratio tooltip's "Current ATR ÷ 20-bar average ATR" prints `${scanned.atrAvgLookback}-bar`
     (byte-identical at the default 20). The backend averages ATR over `atr_avg_lookback`
     (`strategy_engine.py` ~L1553). The Vol tooltip's "20-bar average volume" stays: the backend's volume
     average is fixed at 20 (~L1567). `PreBreakoutParamsPanel`'s help line "Current ATR must be below this
     fraction of the 20-bar average ATR." prints `{params.atrAvgLookback}-bar` (it describes the live input
     beside it).
   - R2-3, integer keys: the page passes the panels normalising setters, not the raw `setParams` /
     `setFibParams`. They apply the panel's update, then `Math.trunc` the integer keys (`atrAvgLookback`,
     `rangeLookbackBars`, `swingLookback`; Fib `fibSwingLookback`, `emaFilterPeriod`) before storing. A typed
     10.5 is therefore stored, shown and sent as 10, which is exactly what the backend's `int()` applied to
     10.5 anyway, so no scan result changes. `Math.trunc` in `remember*` stays as a second guard.
   - R2-3, percent display: both panels show their percent input as `Number((x * 100).toFixed(6))` instead of
     `Math.round(x * 100 * 10) / 10` (`PreBreakoutParamsPanel` ~L160 proximity, `FibPullbackParamsPanel` ~L93
     tolerance). So a typed 7.25 stays "7.25", the value the request sends and the backend applies; today it
     snaps to "7.2". At every 0.1-step value both expressions give the same number. The onChange handlers do
     not change.
1b. **Set Alert uses the row's own direction** (plan round 1, F2; pre-existing defect). Today all three
   tables call `setAlertSymbol(row.symbol)` and the dialog gets the page's current `direction`, so after a
   Bullish scan, a switch to Bearish on Step 3 and a return, the kept Bullish rows would save a **Bearish**
   composite watch. Change: the alert state holds `{ symbol, direction }` from the clicked row
   (`row.direction`; every row type carries it), and `CompositeAlertDialog` receives that direction. The
   dialog itself is not edited. For a row from the current context this is the same value as today.
2. Restructure the JSX into the target layout: `<aside className={styles.side} aria-label="Scan">` holding a
   "Scan" card (textarea, Run Scan, then the current mode's parameters exactly as today — the Pullback
   `<details>` block moved verbatim; the two panels as they are) and a "What you can do" card; the main
   column a card per the current mode (description, error line, table, empty state) in today's order. Keep
   one textarea/Run Scan element rendered (the current mode's), as today. Card titles:
   `<h2 className={styles.cardTitle}><Text size={14} weight={500}>Scan</Text></h2>` /
   "What you can do".
3. **How this page works** (M14), directly under the header, collapsed:
   `<details className={styles.pageExplanation}><summary>How this page works</summary><Text size={12}
   tone="secondary">Three scans. Results are for watching and alerts; there is no trade card for this scanner
   (exits not designed yet).</Text></details>` — text verbatim from `preview.html`.
4. **What you can do** (M15): `<Text size={12} tone="secondary">☆ Watch, 📈 Open in Chart (new tab), Set
   Alert. No trade card.</Text>` — the preview's sentence without its component-name annotation.
5. CSS: `.layout`, `.stack`, `.side`, `.panel`, `.cardTitle`, `.pageExplanation` (+ summary rules) as in P4;
   the three table grids to `minmax(0, …)fr` tracks; `.inputRow` stacks (textarea full width, Run Scan
   full width) inside the side card. Existing button/table classes otherwise unchanged.

**Tests first (must fail before the change)** — render the page with `jest.mock('@/lib/api')`,
`next/navigation` mocked, `CompositeAlertDialog` and the chart mocked as needed:
- "How this page works" is a `<summary>`; its text is present.
- Inside `getByRole('complementary', { name: 'Scan' })`: the textarea (placeholder text as today), "Run
  Scan", and the current mode's parameters (Pre-Breakout: the panel's summary; Pullback: "Scan parameters"
  and "Reset to defaults"; Fib: the Fib panel's summary). "What you can do" text present. Tables are **not**
  inside the aside.
- **Thresholds tied to the scan (the gate case):** run a Pre-Breakout scan (mock `api.prebreakoutScan`
  resolving one row with `metrics.atr_ratio: 0.62`) after changing ATR compression to 0.70 via the panel;
  assert the request carried `atr_compression_ratio: 0.7`; **unmount and re-render** (params reset to the
  default 0.85); the ATR Ratio cell's `title` says "Must be below 0.70 to pass" (not 0.85). Same for Fib:
  tolerance changed to 0.02, scan, remount → the Distance tooltip says "≤2.0%" and a row at 1.8% is `pass`
  toned. With no scan this page load, the tooltip reads the live params (as today).
- **Off-step values (F3):** ATR compression typed 0.875, range bars 10.5, range × ATR 2.75, proximity 0.0725 →
  after the scan, the request carried them as typed, and the ATR tooltip says "below 0.875", the proximity
  tooltip "within 7.25%". `scanThresholds.test.tsx` pins `fmtThreshold` (0.85 / 3 → "3.0" / 0.875 / 2.75 /
  0.0725×100 → "7.25") and `Math.trunc` on the integer keys (10.5 → 10, 10.9 → 10).
- **Round-2 cases:** Fib levels set to [50] → scan → remount → the description reads "(50%)"; with no Fib
  rows it reads "(38.2%, 61.8%)". ATR average lookback 30 → scan → remount → the ATR tooltip says
  "30-bar average ATR"; the panel help line reads "30-bar". Range bars typed 10.5 → the input shows 10 and
  the request carries `range_lookback_bars: 10`. Proximity typed 7.25 → the input keeps "7.25", the request
  carries 0.0725, the tooltip says "within 7.25%". Fib tolerance typed 1.25 → the input keeps "1.25". The
  existing `PreBreakoutParamsPanel` / `FibPullbackParamsPanel` tests (if any) stay green unedited.
- **Description follows the scan (F1):** proximity 0.12 → scan → remount → the description reads "12.0%"
  while the rows show; with no rows it reads the live default "8.0%".
- **Alert direction (F2):** Bullish scan with one row → remount with the scan context direction Bearish →
  "Set Alert" on that row → the mocked `CompositeAlertDialog` receives `direction="Bullish"`. Same for the
  Fib "+" button.
- A param change while a scan is pending: start a scan with ATR 0.70 (deferred promise), change ATR to 0.80,
  resolve → the effect cleared the rows before the resolve; after the resolve the row's tooltip says 0.70.
- `p3aScanSizing.test.tsx` and all other existing suites stay green **without edits**.

**Commit:** `feat(prebreakout): Options layout, how-to and actions card; thresholds follow the scan (STOCK-PRES-P5-PREBREAKOUT T2)`

### Task 3 — Row details: Why it's a setup, confidence breakdown, Fib swing, mini chart

**Files:** `step-4-prebreakout/page.tsx`, `page.module.css`, new `step-4-prebreakout/PreBreakoutRowDetails.tsx`
(or two small components in that folder), new `__tests__/rowDetails.test.tsx`.

**Change:**
1. Pre-Breakout and Fib tables get one trailing column with a toggle button per row:
   `<button type="button" aria-expanded={open} aria-label={`${open ? 'Hide' : 'Show'} details for ${symbol}`}>`
   showing ▾ / ▸. Local state `expanded: string | null` (one open row per table; opening another closes the
   first; changing mode or a new result set closes it). The Pullback table gets no column (D8 / preview: "No
   row details were approved for this mode").
2. **Pre-Breakout details** (`row`, `scanned` from T2):
   - **"Why it's a setup"** — four lines, each `value · threshold`, values from `row.metrics`, thresholds from
     `scanned`; a line whose metric is `null`/absent shows "—" for the value and keeps its threshold:
     - `ATR ratio {atr_ratio.toFixed(2)} · must be below {fmtThreshold(scanned.atrCompressionRatio, 2)}`
     - `Range ratio {range_ratio.toFixed(2)} · {scanned.rangeLookbackBars}-bar range must be below {fmtThreshold(scanned.rangeAtrMult, 1)} × ATR`
       (`rangeLookbackBars` is already the truncated, backend-applied integer)
     - `Volume ratio {vol_ratio.toFixed(2)} · must be below {fmtThreshold(scanned.volCompressionRatio, 2)}`
     - Bullish: `{proximity_pct.toFixed(1)}% from swing high ${swing_level.toFixed(2)} · within {fmtThreshold(scanned.resistanceProximityPct * 100, 1)}%`;
       Bearish: same with "swing low".
     (Row *values* keep today's display rounding; only the *thresholds* must equal what the backend applied.)
     Then the dim note "Same facts as the hover tooltips." (the preview's note, shortened to what is true on the
     page). No trend-filter line (not in the approved mockup).
   - **"Confidence {row.confidence}%"** — when `row.confidence_breakdown` is present: one row per entry of
     `components`, in the order proximity, atr, vol, fib (only those present), label Proximity / ATR
     compression / Volume quiet / Fib level, sub-label `{Math.round(weight*100)}% of confidence`, a bar
     (width = score %, clamped 0–100) and `Math.round(score)`. Absent → the dim line "Confidence breakdown is
     not in this result — re-run the scan." No arithmetic beyond rounding for display; nothing re-derives
     `confidence`.
   - **"Chart"** — the mini chart (item 4) with one price line `{ price: metrics.swing_level, title: Bullish ?
     'Swing high' : 'Swing low' }`.
3. **Fib details:** **"Swing measured from"** — when `row.fib_swing?.low` and `.high` are finite:
   `Swing low $… · Swing high $… · {fib_level_hit}% level $…`, the level price computed exactly as
   `strategy_engine.py:192-205` (Bullish `high − r × (high − low)`, Bearish `low + r × (high − low)`,
   `r` from a local copy of `_FIB_RATIOS` keyed by `Number(fib_level_hit)`; an unknown label → the level price
   is omitted, never guessed). Absent/null swing → "Swing low/high is not in this result — re-run the scan."
   Then **"Chart"** with price lines for swing low, swing high and the level (when computed).
4. **Mini chart:** fetched on expand with `api.getCandles(symbol)` (the call `InlineChartPanel` uses),
   rendered as `<CandlestickChart data={candles} height={180} showToggles={false} defaultIndicators={[]}
   priceLines={…} />`; while loading "Loading chart…", on failure "Chart unavailable" (InlineChartPanel's
   wording). A response for a row that is no longer expanded is ignored (request token), so a slow answer
   for AMZN never draws under CRM. Under it the dim note "📈 Open in Chart and Set Alert stay on the row."
5. Nothing in the details mentions entry, stop, target, exit or position (D14 / ticket 10).

**Tests first (must fail before the change):**
- Pre-Breakout row `{ symbol: 'AMZN', direction: 'Bullish', confidence: 53, metrics: { atr_ratio: 0.62,
  range_ratio: 1.84, vol_ratio: 0.71, proximity_pct: 0.9, swing_level: 201.4 }, confidence_breakdown:
  { fib_used: false, weights: { atr: 0.3, vol: 0.25, proximity: 0.45 }, components: { atr: { score: 27.06,
  weight: 0.3, contribution: 8.12 }, vol: { score: 21.11, weight: 0.25, contribution: 5.28 }, proximity:
  { score: 88.75, weight: 0.45, contribution: 39.94 } }, unrounded: 53.34, confidence: 53 } }` (scores = today's formula on these metrics at the default thresholds) with default
  scanned params: expand → the four exact lines (`ATR ratio 0.62 · must be below 0.85`, `Range ratio 1.84 ·
  10-bar range must be below 3.0 × ATR`, `Volume ratio 0.71 · must be below 0.90`, `0.9% from swing high
  $201.40 · within 8.0%`); breakdown rows "Proximity / 45% of confidence / 89", "ATR compression / 30% … /
  27", "Volume quiet / 25% … / 21"; the mocked chart receives `priceLines=[{ price: 201.4, title: 'Swing
  high' }]`. A Bearish row says "swing low" and "Swing low".
- With scanned params from a remembered scan (ATR 0.70, proximity 0.05) the lines say 0.70 and 5.0%.
- Row without `confidence_breakdown` → the re-run line; no crash. `metrics.range_ratio` absent → "Range ratio
  — · …".
- Fib row Bullish `{ fib_level_hit: '61.8', fib_swing: { low: 152.1, high: 171.8 } }` → "Swing low $152.10 ·
  Swing high $171.80 · 61.8% level $159.63" (171.8 − 0.618 × 19.7 = 159.6254); Bearish same swing →
  "$164.27" (152.1 + 12.1746 = 164.2746); label '99' → no level price; `fib_swing: null` → the re-run line.
  The expected prices are cross-checked by the coordinator against the Python helper before the ticket ships.
- Toggle semantics: one open row; `aria-expanded` flips; Pullback rows have no toggle.
- Stale chart response ignored: expand AMZN (deferred candles), expand CRM, resolve AMZN → the chart is not
  given AMZN's candles.
- No text matching `/\b(entry|stop|target|exit|position)\b/i` inside an expanded details region.

**Commit:** `feat(prebreakout): row details — why it's a setup, confidence breakdown, Fib swing, mini chart (STOCK-PRES-P5-PREBREAKOUT T3)`

## Coordinator checks after the build (not tickets)

1. Walk M1–M15 against the built page (code + tests); record on #150.
2. Cross-check T3's Fib level prices with `_fibonacci_pullback_detail` (Python 3.11) on a synthetic window.
3. `cd frontend && npm run typecheck && npm run test` (full); no backend change, so no pytest.
4. Visual check against `preview.html` at 1280 / 1440 / 1920, light + dark: no browser here → "Needs Kenneth".
5. `git merge origin/main`, re-run 3, then code audit round 1 on `origin/main..HEAD`.

## Bookkeeping (PROJECT_STATE.json; coordinator only)

- The backlog item `STOCK-PRES-P5-PREBREAKOUT` moves from `task_backlog.items` into `phases[]` (not
  duplicated): status `in_progress`, `audit_rounds` 0, `tracking_issue` 150, this plan, branch; `active_phase`
  → this phase.
- Probe: `kind: absent`, path `frontend/app/(frame)/screener/step-4-prebreakout/__tests__/rowDetails.test.tsx`
  (T3, the last ticket), pattern `Why it's a setup`. PRESENCE ONLY.
- After the last ticket: `built`; after a clean code round: `audit_clean: true`; `shipped` only on merge.

## Audit record

- Plan round 1 (2026-10-11): fresh independent gate auditor, plan at 4358b7a2 — **3 gate findings**, all fixed in this revision:
  - F1: the Pre-Breakout description kept the live proximity % above rows judged on another one → it reads `scanned` while rows show.
  - F2: a pre-existing defect. After a direction switch and a remount, Set Alert would save a watch in the wrong direction → the dialog receives the clicked row's direction.
  - F3: the remembered or printed thresholds could differ from the backend's (`int()` truncation, lossy `toFixed`) → effective values are remembered and `fmtThreshold` prints them exactly; off-step tests added.
- Plan round 2 (2026-10-11): fresh independent gate auditor on the round-1 fixes — **3 gate findings**, all fixed in this revision (T2 items 1 and 1c):
  - R2-1: the Fib description's levels are a scan parameter → the description prints the scanned levels while rows show.
  - R2-2: the ATR tooltip hardcoded "20-bar" against the applied `atr_avg_lookback` → it prints the scanned lookback, and so does the panel help line.
  - R2-3: the panels displayed off-step percents rounded (7.25 → "7.2") and stored decimal integer keys the backend truncates → display `Number((x*100).toFixed(6))` and integer keys truncated on store. This is a display-only scope extension to the two panel files.
  - Round 3 is the plan stage's last allowed round.
