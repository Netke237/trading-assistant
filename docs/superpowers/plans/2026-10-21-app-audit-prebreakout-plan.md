# APP-AUDIT-PREBREAKOUT — Lane E Execution Plan

**Tracking:** Issue #353, Programme #348  
**Phase ID:** `APP-AUDIT-PREBREAKOUT`  
**Branch:** `board/app-audit-prebreakout-b4f0d823`  
**Worktree:** `.worktrees/app-audit-prebreakout`  
**Source Baseline:** Frozen at `origin/main` commit `b9a4e087`  
**Report Destination:** `docs/superpowers/audits/app-audit/APP-AUDIT-PREBREAKOUT/report.md`  

---

## 1. Goal and Deliverables

Verify Pre-Breakout, Fibonacci, and Pullback end to end across the screener's Step 4 Pre-Breakout surface (`frontend/app/(frame)/screener/step-4-prebreakout/`), its backend endpoints, signal engines, candidate evidence, supplementary context, and Candidate Chart workspace handoff.

The audit establishes:
1. **Mathematical & Signal Parity**: Independent verification of setup detection, ATR compression, volume ratio, swing proximity, Fibonacci retracements, EMA trend filters, and confidence formulas.
2. **State & Evidence Integrity**: Bounded snapshot capture (`rememberScan`, `scanSnapshot`), integer parameter truncation (`truncPreBreakoutInts`, `truncFibInts`), candidate selection isolation, supplementary analysis scoping (`useSelectedStockContext`), and readable raw evidence preservation.
3. **Setup-Origin Chart Handoff**: Exact contract verification for candidate chart navigation (`buildCandidateChartHref`, `parseCandidateChartContext`, `useOriginalBacktest`), confirming explicit `unsupported` handling for Pre-Breakout/Fibonacci vs verified artifact hydration (`GET /api/backtest-artifacts/{artifact_id}?symbol={symbol}`) for Pullback.
4. **Boundary & Error Behavior**: Handling of empty universes, invalid symbols, network failures, missing historical bars, parameter validation, and mode transitions.
5. **Reconciliation with Lane A**: Alignment with route and disclosure inventories from `APP-AUDIT-INVENTORY` (#349).

**Audit Boundaries:**
- Audit and report scope only. No application code, algorithm weights, or database schemas are modified during this audit phase.
- Discovered defects are cataloged into structured findings; each actionable defect becomes a separate board remediation ticket.
- No live broker orders, external notifications, destructive database operations, or shared scheduled jobs are triggered.

---

## 2. Scope & Target Surfaces

### A. Sub-Mode 1: Pre-Breakout Scan (`scanMode === 'prebreakout'`)
- **Parameter Controls**: `PreBreakoutParamsPanel` (`PREBREAKOUT_DEFAULTS`, `PreBreakoutParams` in `frontend/components/organisms/PreBreakoutParamsPanel/index.tsx:6-24` and `backend/config/strategy_params.yaml:603-618`):
  - `atrCompressionRatio` (default **0.85**, range `0.1–1.0`, step `0.05`)
  - `atrAvgLookback` (default **20**, range `5–50`, step `1`)
  - `rangeAtrMult` (default **3.0**, range `0.1–5.0`, step `0.1`)
  - `rangeLookbackBars` (default **10**, range `3–30`, step `1`)
  - `volCompressionRatio` (default **0.90**, range `0.1–1.0`, step `0.05`)
  - `resistanceProximityPct` (default **0.08** [8%], range `0.01–0.20` [1%–20%], step `0.005` [0.5%])
  - `swingLookback` (default **50**, range `10–100`, step `5`)
- **API Request & Routing**: `POST /api/scan/prebreakout` (`PreBreakoutScanRequest`) handled by `_prebreakout_scan_core` in `backend/app/routers/stock_scan.py:2319-2420`.
- **Core Signal Detection**: `breakout_setup_signal` in `backend/app/services/strategy_engine.py:1516-1660`:
  - ATR calculation: 14-period Simple Moving Average (SMA) of True Range via `_atr_series(bars, period=14)` (`backend/app/services/strategy_engine.py:95-104`), compared against N-period SMA of ATR (`atr_avg_lookback`). Note: It uses rolling True Range SMA, not Wilder exponential smoothing (which is used in `stock_scorer.py:_atr`).
  - Range consolidation gate: N-bar high - low bounded by `range_atr_mult * ATR`. (Note: Range is a qualification gate, not a confidence component).
  - Volume contraction: last bar volume / 20-bar SMA of volume.
  - Proximity to swing level: distance to N-bar swing high (Bullish) or swing low (Bearish).
- **Confidence Computation**:
  - Base components: ATR compression (**30%**), volume compression (**25%**), resistance proximity (**45%**).
  - Scaled components when Fib enabled (`fib_enabled=True`): ATR compression (**24%**), volume compression (**20%**), resistance proximity (**36%**), Fibonacci retracement (**20%**).
  - Total confidence score (0–100): weighted sum of component scores.
- **Sorting & Delivery**: Candidates sorted strictly by `confidence` descending.

### B. Sub-Mode 2: Fibonacci Pullback Scan (`scanMode === 'fib'`)
- **Parameter Controls**: `FibPullbackParamsPanel` (`FIB_PULLBACK_DEFAULTS`, `FibPullbackParams` in `frontend/components/organisms/FibPullbackParamsPanel/index.tsx:6-20` and `backend/app/routers/stock_scan.py:2142-2149`):
  - `fibSwingLookback` (default **100**, range `20–200`, step `5`; backend validation bound: `>= 10`)
  - `fibLevels` (default **`[38.2, 61.8]`**; allowed levels: `23.6, 38.2, 50.0, 61.8, 78.6`)
  - `fibTolerancePct` (default **0.015** [1.5%], UI slider range `0.005–0.050` [0.5%–5.0%], step `0.001` [0.1%]; backend validation bound: `0 < tol <= 0.20`)
  - `emaFilterPeriod` (default **20**, range `0–200`, step `1`; `0` disables filter)
- **API Request & Routing**: `POST /api/scan/fib-pullback` (`FibPullbackScanRequest`) handled by `_fib_pullback_scan_core` in `backend/app/routers/stock_scan.py:2160-2317`.
- **Core Signal Detection**: `fibonacci_pullback_detail` in `backend/app/services/strategy_engine.py`:
  - Swing identification: swing high and swing low over `fib_swing_lookback`.
  - Retracement levels: calculated from impulse move (`swing_high - swing_low`).
  - EMA filter gate: close > EMA (Bullish) or close < EMA (Bearish).
- **Confidence Formula**:
  - Missing distance (`dist_pct is None`): `confidence = 0`.
  - Within tolerance (`dist_pct <= tol`, where `tol = fib_tolerance_pct * 100`):
    `confidence = max(60, round(100 - (dist_pct / tol) * 40))`.
  - Outside tolerance (`dist_pct > tol`):
    `confidence = max(0, round(60 - ((dist_pct - tol) / tol) * 30))`.
- **Sorting & Delivery**: Candidates sorted primarily by `not at_level` (at-level hits sort first), secondarily by `fib_dist_pct` ascending (closest to level first).

### C. Sub-Mode 3: Pullback Scan (`scanMode === 'pullback'`)
- **Parameter Controls**: `pullbackEmaParams` (`emaPeriod: 50`, `trendEma: 100`).
- **Sizing Integration**: `scanSizingFromRisk()` pulling `portfolioValue` and `maxLossPerTradePct` from `useRiskStore`.
- **API Request & Routing**: `POST /api/stock-scan` with `category: 'pullback'`, `strategy: 'pullback_ema'`.
- **Backtest Execution**: Vectorised backtest via `run_strategy_backtest` from `backend/app/services/strategy_backtest.py`, generating frozen `BacktestArtifact` with unique UUID `artifact_id`, win rate, expectancy, and confidence gate status.
- **Candidate Presentation**: Renders `PositionCardData` candidates with stock score, status, and backtest artifact reference.

### D. Setup Evidence, Chart & Supplementary Context
- **Candidate Selection**: Row selection state machine (`selectedSymbol`), row selection button/keyboard handling (`aria-pressed`, `Enter`/`Space`).
- **Setup Evidence Panel (`SelectedRowEvidence`)**:
  - Preserved evidence from PR #224 / #304: `RawEvidence` collapsible tree.
  - Snapshot validation: verification that displayed thresholds match `applied.pre` or `applied.fib` snapshot from the actual run, including integer parameter truncation (`truncPreBreakoutInts`, `truncFibInts`) matching backend `int()` coercion.
  - Semantic separation: explicit disclosure distinguishing setup confidence (pattern score) from stock filter score and backtest win-rate/expectancy.
- **Selected Setup Chart (`SelectedSetupChart`)**:
  - Daily candle fetching via `api.getCandles(symbol)`.
  - Overlay price lines (`scanChartLines` in `scanChartLines.ts`): setup evidence price lines only (`Scan swing high`/`Scan swing low`, Fib swings, and `Scan Fib {lvl}%`; returns `[]` for pullback). Explicitly contains NO entry/stop/target lines or ATR bands.
  - Race condition & stale protection: in-flight cancellation via `cancelled` flag and identity check against `current = state.row === row && state.scope === scope`.
- **Supplementary Stock Context (`SelectedStockContext`)**:
  - Live analysis fetch via `api.analyzeStock` with direction/horizon scoping.
  - Separation of original Pullback context vs supplementary live context.
  - Fundamental health scorecard: `FundamentalHealthCard` (Growth 35%, Quality 35%, Risk 30%).
  - Regime sentiment: conviction percentage alignment to trade direction.
- **News Feed (`SelectedStockNews`)**:
  - Ticker news via `api.getNews(symbol)` with sentiment tags.

### E. Setup-Origin Candidate Chart Workspace Handoff
- **Navigation Trigger**: Open in Chart button (↗) calling `buildCandidateChartHref(row, scanMode)`.
- **Handoff Contract (`frontend/lib/candidateChart.ts`)**:
  - Pre-Breakout / Fib: `source === 'prebreakout' | 'fib'` sets `status = 'unsupported'` and omits `backtest_artifact_id`.
  - Pullback: sets `status = row.backtest_artifact_status ?? 'original_unavailable'` and passes `row.backtest_artifact_id`.
- **Chart Workspace Resolution (`frontend/lib/useOriginalBacktest.ts` & `CandidateChartWorkspace`)**:
  - For Pre-Breakout / Fib: `useOriginalBacktest` returns `{ status: 'unavailable', reason: 'unsupported' }`. The UI renders the live chart with notice:
    *"Original backtest unavailable: unsupported. Live chart below; no historical result has been substituted."*
  - `FreshBacktestControls`: allows user to run an independent fresh backtest with separate provenance (`provenance: 'fresh'`).
  - For Pullback: `useOriginalBacktest` fetches and verifies the original artifact via `GET /api/backtest-artifacts/{artifact_id}?symbol={symbol}` verifying `schema_version === 1`, symbol match, and `provenance === 'original'`.

### F. Universe Resolution & Actions
- **Universe Resolution**: Manual ticker override (`symbolOverride`) vs `universePick === 'Custom'` (`customRaw`) vs `Watchlist` (`useWatchlistStore`) vs Presets (`SP500`, `NDX100`, Sectors).
- **Interactive Actions**:
  - `WatchStar`: adding/removing from `useWatchlistStore`.
  - `CompositeAlertDialog`: launching price/condition alert builder.
  - `SavedScanReportInspector`: inspecting saved scan reports (`tableRunId`, filter exclusions, terminal outcomes).
- **Mode Switching Lifecycle**: Resetting `selectedSymbol`, clearing results, canceling in-flight request tokens (`requestToken.current += 1`).

---

## 3. Execution Plan & Tasks

### Task 1: Mathematical & Algorithmic Parity Verification
- [ ] Independently derive 14-period True Range rolling SMA via `_atr_series` and rolling SMA lookbacks; verify against `strategy_engine.py:breakout_setup_signal`.
- [ ] Verify Pre-Breakout confidence breakdown weights: ATR (30%), Volume (25%), Proximity (45%) summing to 100% (and 24/20/36/20 when Fib enabled).
- [ ] Verify Fibonacci retracement levels (23.6%, 38.2%, 50.0%, 61.8%, 78.6%) and tolerance bands; verify EMA filter logic.
- [ ] Verify Fibonacci confidence formula for `dist_pct is None` (0), at-level (`[60, 100]`), and outside-tolerance (`[0, 60]`) bands, scaled by `tol = fib_tolerance_pct * 100`.
- [ ] Verify Pullback scan sizing arithmetic (`scanSizingFromRisk`, account size, risk percentage) and execution via `run_strategy_backtest`.

### Task 2: State Machine, Snapshot & Truncation Verification
- [ ] Verify `scanSnapshot` and `rememberScan` capture immutable execution context (direction, horizon, universe, applied params).
- [ ] Verify integer parameter truncation via `truncPreBreakoutInts` and `truncFibInts` matching backend `int()` coercion (`stock_scan.py:2201, 2361`).
- [ ] Verify that changing parameter sliders does not retroactively alter the displayed applied thresholds for already-rendered rows.
- [ ] Verify request token invalidation prevents stale or out-of-order network responses from overwriting current state.
- [ ] Verify `SelectedStockContext` correctly isolates live supplementary analysis from original scan evidence.

### Task 3: Candidate Chart Handoff & Provenance Audit
- [ ] Verify query string construction in `buildCandidateChartHref` for all three sub-modes.
- [ ] Verify `parseCandidateChartContext` strict validation (UUID checking, source whitelisting, multiple key rejection).
- [ ] Verify `useOriginalBacktest` returns `unsupported` for Pre-Breakout/Fib and prevents substitution of synthetic artifacts.
- [ ] Verify `useOriginalBacktest` artifact fetch contract includes `?symbol={symbol}` and validates schema, identity, and status.
- [ ] Verify `FreshBacktestControls` handles fresh parameter configuration without mutating original evidence.

### Task 4: UI Presentation, Accessibility & Boundary Audit
- [ ] Test all states: Normal, Selected row, Empty universe, Zero candidates found, Network error, Loading shimmer.
- [ ] Verify keyboard navigation (Enter/Space on candidate rows, Tab index traversal, ARIA button states).
- [ ] Verify theme switching (`light` / `dark`) and compact density rendering.
- [ ] Verify filter breakdown panel toggle and `SavedScanReportInspector` integration.

### Task 5: Inventory Reconciliation & Defect Catalog
- [ ] Reconcile every route disclosure against `APP-AUDIT-INVENTORY` (#349).
- [ ] Author comprehensive audit report at `docs/superpowers/audits/app-audit/APP-AUDIT-PREBREAKOUT/report.md`.
- [ ] Catalog all discovered defects in `docs/superpowers/audits/app-audit/APP-AUDIT-PREBREAKOUT/defects.json`.
- [ ] Record execution provenance in `provenance.json`.

---

## 4. Verification & Testing Methodology

- **Automated Tests**:
  - Run existing backend tests: `test_prebreakout_params.py`, `test_prebreakout_universe.py`, `test_fib_pullback_endpoint.py`, `test_fibonacci_signal.py`.
  - Run existing frontend tests: `PreBreakoutIdentityClick.test.tsx`, `chartActions.test.tsx`, `filterBreakdown.test.tsx`, `modeEvidence.test.tsx`, `readableEvidence.test.tsx`.
  - Author dedicated audit tests pinning mathematical formulas, snapshot isolation, and handoff contracts.
- **Typecheck & Lint**:
  - `npm run typecheck` (`tsc --noEmit`) in frontend.
  - Python type/syntax verification on backend routers and services.
- **State Integrity**:
  - Zero drift in `python scripts/state.py`.
