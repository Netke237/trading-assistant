# Pre-Breakout presentation V2 preservation crosswalk — PB-BASE-01 (#258)

Documentation reconciliation, 13 October 2026. This records implementation inputs; it does not clear an implementation audit or declare downstream tickets complete.

## Baseline and authority

- Current main and continuation base: `3b144eed7503ef655da36c5bae3cb538fb78abec` (Stocks shipped-state #280; Stocks implementation #279 at `1484131b6455314024a6030598b2616711a7f45e`).
- Open predecessor #150 / PR #224: exact inspected head `5e8a2d2690cfbdc25a5c97288d6a570a25d0de61`, branch `board/stock-pres-p5-prebreakout-f3563f64`. Both remained OPEN during reconciliation. Its source is reference/provenance, not a merge prerequisite or permission to close it.
- Approved sources: `docs/superpowers/specs/2026-10-13-approved-screener-designs/README.md`, `prebreakout-presentation-tickets.md`, `prebreakout-layout-amendment.md`, and `scan-log-isolation-tickets.md`. Frozen original and revision audit evidence remain unchanged; register the successor phase separately without resetting predecessor counters.
- Shared switch stays in `frontend/app/(frame)/screener/layout.tsx`, above step content. Self-contained Step 4 remains; no steps 5–7, position/broker handoff, invented exits or TP probabilities.
- Below, page means `frontend/app/(frame)/screener/step-4-prebreakout/page.tsx` at the baseline. Predecessor paths are the same directory unless stated otherwise. Application ports must be selective, tested and included in the successor integrated code audit; do not cherry-pick predecessor state or its older whole-page replacement over current report integration.

## Controls, inputs and lifetimes

| Current source / mechanism | Approved destination and preservation requirement |
|---|---|
| Page header Setup Scanner; universe display labels (sector ETFs, SP500/NDX100/DOW30/SPY, fallback raw pick); inherited direction `context?.direction ?? 'Bullish'` | Header above controls; preserve true scope and direction. Do not turn bearish regime into bullish/PASS. |
| Local sub-mode buttons Pre-Breakout, Pullback to EMA N, Fib Pullback; `aria-pressed`; default prebreakout | In-page controls, independent of shared mode switch; retain all three modes and dynamic EMA title. |
| Current `MinWidthGate` defaults to 1280px on this Step 4 route; the two Step 7 workspaces alone have 1200px exceptions | Preserve this existing guard. Validate Pre-Breakout content at 1280px and wider, and the resize explanation below its boundary. The generic AGENTS.md description predates the route-specific exceptions; inspect the actual guard. |
| Manual textarea and Run Scan / Scanning… disabled state | Scan controls; split whitespace/comma/semicolon, uppercase, ticker regex `^[A-Z][A-Z0-9.\-]{0,5}$`; retain valid-entry precedence over Custom, then Watchlist, then server universe. Invalid-only override falls through to universe; displayed “manual symbols” currently follows nonblank text. Do not silently change parser or precedence. |
| Empty Custom / Watchlist / no-symbol errors, caught API/sizing errors; pre/fib/pullback empty-result copy | Local error/loading/empty states independent of selected chart/context/news. Pre empty message currently also appears on error; preserve information without fabricating “zero rejected.” |
| PreBreakoutParamsPanel details + sections + explanatory higher/lower text; Reset | Control area. Preserve compression, range, volume and directional swing explanations and units. ATR denominator is configured lookback, not always 20. |
| FibPullbackParamsPanel details + checkbox explanatory text; last selected level cannot be unchecked; sorted additions; Reset | Control area. Preserve all five level choices and disabled last-choice guard; EMA 0 = off label and behavior. |
| Pullback details, signal/trend EMA labels; 4% directional proximity explanation; trend relationship and higher/lower descriptions; Reset | Control area; no additional strategy picker or execution controls. |
| Parameter/universe/direction effect skips first mount, then clears all three tables and table-run IDs | Retain table invalidation on those dependencies. It currently does not clear on sub-mode, override text, customRaw, horizon, risk or watchlist changes. Saved reports survive every such change. Selection must clear when no longer represented. |
| Pre/Fib results in scanStore; Pullback results local; params and mode local | Pre/Fib survive in-session page remount, but are **not persisted** by scanStore `partialize`; Pullback does not survive remount. Do not assert durable table rows. Historical/optional-field rows remain supported. Existing `bamendjou-scan-store` v19/migrations, watchlist keys and all unrelated persisted fields stay intact. Any breaking persisted shape needs migration; new keys use colon form. |
| `runScan` asynchronous request captures parameters; baseline has no request token/abort guard for candidates | Add the approved stale-response/selection protection: distinguish current request symbol/direction/horizon/mode and snapshot, ignore superseded responses. Do not describe this as a guard already present. Failed scans retain prior rows; do not relabel them as the failed attempt's rows. |

### Exact panel values and request mapping

Ranges and steps below are HTML input constraints; they are not a license to add backend clamps, round typed values to a step, or alter engine qualification.

| Control | Default; min/max/step | Sent field |
|---|---|---|
| ATR compression ratio | .85; .1/1/.05 | `atr_compression_ratio` |
| ATR average lookback (bars) | 20; 5/50/1 | `atr_avg_lookback` |
| Range / ATR multiplier | 3; .1/5/.1 | `range_atr_mult` |
| Range lookback bars | 10; 3/30/1 | `range_lookback_bars` |
| Volume compression ratio | .9; .1/1/.05 | `vol_compression_ratio` |
| Proximity percent | stored .08, displayed 8%; 1/20/.5 percent | `resistance_proximity_pct`, entered percent /100 |
| Swing lookback bars | 50; 10/100/5 | `swing_lookback` |
| Fib levels | [38.2,61.8]; choices 23.6/38.2/50/61.8/78.6 | `fib_levels`, percentage labels unchanged |
| Fib swing lookback | 100; 20/200/5 | `fib_swing_lookback` |
| Fib tolerance percent | stored .015, displayed 1.5%; .5/5/.1 percent | `fib_tolerance_pct`, entered percent /100 |
| Fib EMA filter | 20; 0/200/1 | `ema_filter_period` |
| Pullback signal EMA | 50; 5/200/1 | `pullback_ema_period` |
| Pullback trend EMA | 100; 20/500/5 | `pullback_trend_ema` |

Pre/Fib use `api.prebreakoutScan` / `api.fibPullbackScan` with symbols, direction, params_override and optional universe. Pullback uses `api.postStockScan`, category `pullback`, universe-or-symbols, `_horizonEnum(context?.horizon)`, strategy `pullback_ema`, and explicit snake-case `account_size` / `risk_pct` from `scanSizingFromRisk`. Keep zero-risk refusal and actual sizing. Reset restores only its mode's above defaults.

## Result fields, evidence, tooltips and actions

| Baseline/prior source | Destination / numeric contract |
|---|---|
| Pre symbol, row direction arrow/tone, confidence, ATR ratio, volume ratio, proximity | Pre table columns. Confidence-descending order remains; confidence is setup score, not profit probability. Preserve numeric zero versus missing, existing table rounding (ATR/volume 2dp, proximity 1dp) and more precise hover observations (3dp/3dp/2dp). |
| Pre confidence tooltip and `strategy_engine.breakout_setup_signal` | Explain actual weighted score: non-Fib ATR 30%, volume 25%, proximity 45%; optional Fib weights 24/20/36/20 from returned evidence. Range is a gate, not a score component. Engine also has trend filtering; “four gates” copy must not imply no trend filter. No recalculation of row confidence from rounded metrics. |
| Pre returned `metrics` | Disclosure retains `range_ratio`, `swing_level`, `current_atr`, optional `fib_at_level`, `fib_level_hit`, `fib_dist_pct`, plus other returned metrics; retain units and null distinctions even when not columns. ATR = current ATR(14) / configured average ATR; range = N-bar high-low / current ATR; volume = last bar / preceding 20-bar volume average; proximity already percent, denominator swing level, direction selects high/low. |
| Pre `confidence_breakdown` and `fib_swing` already supplied by main backend/types | Preserve components score/weight/contribution, weights, fib_used, unrounded and returned confidence in inspectable evidence. Missing evidence explicitly unavailable. Optional Pre Fib swing also remains available, not only standalone Fib swing. |
| Pullback symbol/company/direction/stock_score/price/confidence, score and confidence tooltips | Pullback table, authoritative company from its PositionCardData; preserve stock-score coloring (`statusForScore`), price $2dp, nullable confidence dash, historical confidence source and qualification. Retain every PositionCardData conditional evidence/status when exposed downstream; do not map it to Pre ratios or infer setup confidence from score. Preserve response ordering (stock score). |
| Fib symbol/direction/string fib_level_hit/nullable fib_dist_pct/at_level/confidence | Fib columns: append % once to string label; distance 1dp, missing dash; compare percent distance to applied fractional tolerance ×100. At-level YES/no and explanations preserved. Source backend order: at-level first, then ascending distance with missing last. Confidence only proximity; it does not assert volatility/volume/trend qualification even though endpoint applies EMA filtering separately. |
| WatchStar all modes; chart shortcut currently Pre/Fib; Alert text Pre/Pullback and + Fib | First identity column groups one watch star, one clicked-row new-tab `/chart?symbol=…`, symbol and authoritative company/unavailable fallback. Add chart action for Pullback as approved. Trailing column retains Alert only. No chart-area duplicated watch/chart/alert actions. Stop propagation when required to avoid selecting another row. Preserve symmetric star persistence. |
| CompositeAlertDialog baseline symbol + ambient direction; prior #224 `alertTarget` | Use clicked-row symbol **and row direction**; prior source exact head above. Keep dialog conditions, close/dismiss/reset and existing alert semantics. Never auto-create a watch/alert or invent levels. |
| Prior `scanThresholds.ts` | Selectively preserve applied request snapshots, integer truncation toward zero (`Math.trunc` matches router `int`), copied Fib level arrays, remount lifetime matching in-memory rows, unknown snapshot unavailable. Snapshot only with corresponding successful rows, retain report callbacks. Do not show defaults/live controls as scanned thresholds. |
| Prior `fmtThreshold`, panel percentage display changes | Preserve off-step .875 ratio, 7.25% proximity, 1.55% tolerance without lossy display rounding; prior helper is bounded to six decimal places, so do not claim arbitrary precision. Integer bars display applied truncated values. No forced step rounding or changed request value. |
| Prior `PreBreakoutRowDetails.tsx` | Move facts/evidence to selected-row disclosure/context while retaining discoverability and unavailable explanations. “Why it's a setup” exposes range and scanned thresholds. Prior component shows rounded score/weight bars but not all contribution/unrounded fields; extend disclosure to retain complete returned evidence. |
| Prior Fib row details and CandlestickChart `priceLines` addition | Selected mini chart keeps swing low/high and matching Fib level: known ratios .236/.382/.5/.618/.786, bullish high−r×(high−low), bearish low+r×(high−low); unknown label no guessed line. Pre chart shows returned swing high/low. Finite-only lines, cleanup on change/unmount; no orders, targets/stops or qualification recalculation. |
| Prior MiniChart request token; ranking chart/header patterns | Selected symbol plus interval/indicator controls where supported; stale results ignored and chart failure isolated from table. Prior MiniChart is daily candles, no toggles. `api.getCandles` baseline only symbol; do not advertise unsupported interval fetching. |

## Selected context and amended layout

Sentiment/regime and selected-symbol fundamental health belong after scan controls, above results. Table left and selected mini chart right; five stock component cards and news below. Market scope and selected-stock scope remain explicit. Keep total/raw score, component weight/contribution/notes/status and qualification/safety content wherever a compatible source exists. Setup score, stock score, historical confidence, sentiment and fundamentals remain distinct.

The Options ranking page's selected candidate and score cards are layout references only, never a data fallback. Verify same symbol, direction, horizon, strategy and snapshot compatibility of a supported analysis response before rendering its five components; incompatible/missing context is unavailable with a reason. Fetching context must not rerun or reorder the user's scan. `api.getNews(symbols)` supplies selected-symbol headlines/publisher/date; current backend/TypeScript NewsItem contracts discard original article URLs. #265 must retain provider-supplied links through an additive optional URL field in `backend/app/data/market.py`, `backend/app/schemas/__init__.py` and `frontend/types/domain.ts`, then render valid HTTP(S) original links with local loading/error/empty and stale guards. Missing or invalid links stay explicitly unavailable; no constructed publisher links. This fulfills the frozen original-link requirement without changing scores or existing news callers. Industry mapping/feed remains unavailable until supported; do not invent it. Company data is authoritative existing response data or unavailable; this amendment creates no mandatory description service.

## Durable reports and diagnostics prerequisite

Existing main already contains `frontend/lib/scanReports.ts`, API report request/response metadata handling, `SavedScanReportInspector`, and backend `scan_report_lifecycle.py`, `scan_reports.py`, router/models. Preserve these contracts rather than replacing them with the older #224 page:

- Five separate categories `options`, `stocks`, `prebreakout`, `pullback`, `fib`; immutable run_id and category generation; frozen request/effective configuration, resolution/exclusions, trigger/status/start/end/persistence.
- System retrieval through `/api/scan-reports/latest/{category}`, `/api/scan-reports/runs/{run_id}`, `/api/scan-reports/legacy`. Pre/Fib list callers retain list shape and metadata headers; Pullback response report_run_id retained. Page callbacks supply ephemeral `tableRunIds`; durable retrieval does not depend on browser memory.
- Analysis log becomes matching-run Filter Breakdown/inspector surface. Keep category selector and Legacy/unclassified, refresh, latest attempt/previous saved report, recorded values/exclusions/raw evidence, frozen-input mismatch warning, effective-configuration incomplete message, diagnostics-unavailable state, unsaved-current-run warning and separate durable evidence identity. Do not relabel previous saved evidence as current candidates. Inspector already aborts fetches/guards category and generation and supports drawer keyboard/focus handling.
- Parameter changes, navigation/remount/reload/restart and other-category scans do not erase saved reports. Table invalidation is separate. API update metadata is ephemeral and generation guarded. Do not delete report history or rename storage keys.
- **PB-PRES-05 remains required**: current Pre/Fib accepted-list pipelines do not supply authoritative mutually exclusive terminal outcomes/rule observations for every symbol. Existing report persistence/configuration/accepted/exclusion observations do not establish complete rejected counts. Generic omission and silent no-setup/EMA rejection cannot be named as a particular rule failure. Reuse/add to matching-run recording with list compatibility, deduplication/candidate parity, unknown/legacy unavailable; never second-scan diagnostics or universe-minus-survivors. Pullback has its own stock pipeline and must retain its actual schema. PB-PRES-06 depends on this reviewed data work; a truthful unavailable state alone does not complete it.

## Scope changes, prerequisites and concurrency

No substantive scoring/qualification/trading plan change is authorized by this reconciliation. Approved destinations plus selective predecessor preservation are within PB-BASE/PB-PRES scope. Implementation must explicitly accommodate current report integration (absent from predecessor page), no snapshot on legacy rows, and stale scan replies. If source verification cannot supply compatible selected-stock context, complete an independently reviewed additive source contract before calling PB-PRES-04 complete. PB-PRES-05 similarly needs reviewed diagnostic design/data parity before its UI ticket. A new source contract, changed scoring, changed table/report persistence or changed exclusion semantics is substantive plan scope and must be reconciled/audited before building.

Observed claims: coordinator owns `PREBREAKOUT-PRESENTATION-V2` on `board/prebreakout-presentation-v2-c89f5fa0`; other live tasks `BROKER-PATH-RESIDUALS`, `MEAS-LIVE-DB-ISOLATION`, and newly observed `LAN-ACCESS` on main. Leave their broker/runtime/DB/network work untouched, recheck ledger before shared-file work. No live predecessor claim was listed, but this does not authorize merging/closing #224. Shared frontend edits remain serial. Source ports and fresh build tickets belong to the successor code audit; preserve the original and layout revision plan audit evidence/counters.

## Verification record

Documentation-only reconciliation: source inspected at exact commits above; no application files, old state/audit fields, GitHub issues or PRs mutated. Frontend typecheck is required before this document commit; coordinator records its result and reviews this crosswalk before phase registration/downstream build. Tests-first is inapplicable to this documentation inventory; runtime parity, action/race/units tests and integrated independent audit remain implementation gates.

### Downstream file/scope allocation

This allocation implements existing ticket requirements; it adds no scoring or execution decision. Helpers may be split within the owning page directory to keep each build small.

| Ticket | Concrete source scope / dependency |
|---|---|
| #259 PB-PRES-01 | Page and page.module.css; selected-row shell/request guards and controls. Add selectively ported `scanThresholds.ts`, its focused tests and exact percentage formatting changes in the two parameter panel index.tsx files. Preserve current report callbacks/inputs and shared layout. |
| #260 PB-PRES-02 | Page mode tables and selected evidence helper (adapt predecessor `PreBreakoutRowDetails.tsx`), field/unit/legacy tests. Complete confidence evidence includes contributions/unrounded metadata, optional Fib swing and all metrics; do not require chart port here. Depends on #259. |
| #261 PB-PRES-03 | Page action/alert target handling; selected chart helper; CandlestickChart index.tsx additive priceLines and focused lifecycle tests. Selectively adapt predecessor lines/stale token tests, retain existing chart callers. Depends on shell/table; clicked-row direction belongs here if not needed earlier for safe shell refactor. |
| #262 PB-PRES-04 | Selected context helper/page and narrowly required API/types/source contract if independently approved; score/evidence identity tests. `api.analyzeStock` is a live independently evaluated response, not the original setup run's score. Carry its symbol/direction/horizon/strategy/request identity and label separately fetched context with its own scope; if compatibility cannot be established show unavailable. Never display its score as scan rank/setup confidence, and never borrow an Options candidate. |
| #263 PB-PRES-05 | Backend stock_scan/scan-report collector/lifecycle and focused contract/parity tests; additive terminal-outcome observations on the existing evaluated run, preserving accepted-list transport, report run identity and category schemas. Detailed design/audit needed before implementation. |
| #264 PB-PRES-06 | Page filter/log trigger and existing SavedScanReportInspector extension only as necessary for #263's actual outcomes. Depends on reviewed data contract; preserve all existing report disclosure content and separate table/run identity. |
| #265 PB-PRES-07 | Selected news helper/page and CSS, api.getNews reuse, additive optional original URL projection/schema/type and provider contract tests, stale/error/link tests. No industry feed invention. |
| #266 PB-PRES-08 | Coordinator preservation/validation/audit records and integrated checks; maintain this crosswalk continuously. No state audit counter edits by implementers. |

Typecheck result for this documentation commit: `npm --prefix frontend run typecheck` passed (exit 0).

The PB-PRES-04 requirement to verify snapshot compatibility means live analysis cannot masquerade as matched scan evidence. Any supplementary live analysis must be explicitly labeled separately fetched with fetch time, source, requested strategy and direction/horizon, validated same-symbol, and remain distinct from original setup-run evidence (which is unavailable from that response). `_analyze_core` calls `score_stock` independently of requested strategy; later strategy/backtest results are separate. A global last Stocks request is not a compatible request source. The reconciliation auditor should verify that this separate-context interpretation satisfies the frozen plan; otherwise retain unavailable matched-snapshot cards until a supported source contract exists.

## Implementation record (PB-PRES-08 / #266, coordinator)

Maintained by the takeover coordinator on `board/prebreakout-presentation-v2-f78dd25f`, 14 October 2026. This maps each allocation row above to the commit that implemented it. It records builds and per-ticket verification only. It is **not** an audit: the integrated independent code audit over `origin/main..<branch>` is still required, and plan rounds 2 / code rounds 0 are carried forward unchanged.

| Ticket | Commit | Destination delivered (per allocation) |
|---|---|---|
| #258 PB-BASE-01 | `c6b140ff` | This crosswalk |
| #259 PB-PRES-01 | `a35da6c7` | Selected-setup shell, request token/stale-reply guards, scoped applied-threshold snapshots (`scanThresholds.ts`), exact percentage display in both parameter panels; report callbacks/`tableRunIds` retained |
| #260 PB-PRES-02 | `1b840255` | Mode-specific tables with existing orders/units, complete selected evidence disclosure (`PreBreakoutRowDetails.tsx`), legacy rows without evidence shown unavailable |
| #261 PB-PRES-03 | `b8379697` | Selected mini chart (`SelectedSetupChart.tsx`, additive CandlestickChart `priceLines`), identity column watch/chart/symbol/company in all modes, row Alert with clicked-row symbol and direction |
| #262 PB-PRES-04 | `ea923796` | Separately labelled live stock context (`SelectedStockContext.tsx`) with request identity; sentiment/fundamentals after controls, five component cards below results; no Options/Stocks borrowing |
| #263 PB-PRES-05 | `ca7addbf` | Additive `diagnostics.terminal_outcomes` v1 (same evaluated run, dedup before evaluation and counting, mutually exclusive terminals, unknown/partial, list transport unchanged) for prebreakout/fib/pullback |
| #264 PB-PRES-06 | `44ece365` | "Filter breakdown" beside each mode's candidates heading. It opens the existing saved-report inspector, whose former "Analysis log" content is fully kept. Terminal counts come only from the saved report. Saved-run vs table-run identity is shown, with units verified against the backend |
| #265 PB-PRES-07 | `253c43f1` | Optional provider-only `NewsItem.url`; selected-symbol news below stock cards with stale guard, isolated states, no sentiment, industry feed explicitly unavailable |
| #266 PB-PRES-08 | `26d71cb` + this record | Integrated presence marker `data-presentation="prebreakout-v2"` on the page root; this crosswalk record; integrated checks below |

Preservation checks against the tables above:
- The shared Options / Stocks / Pre-Breakout switch is unchanged in `screener/layout.tsx` (this branch has no diff to that file).
- Step 4 remains self-contained, with no steps 5–7 and no broker handoff.
- No persisted store shape or storage key changed (this branch has no diff to `scanStore.ts` / `watchlistStore.ts` persistence).
- Pre/Fib list responses and Pullback `report_run_id` are retained.
- Saved reports are not deleted on parameter or mode change.

Integrated verification results are recorded in the `PROJECT_STATE.json` phase entry (`integrated_verification`).
