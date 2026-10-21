# APP-AUDIT-ANALYTICS-DATA — Lane H Execution Plan

**Tracking:** Issue #356, Programme #348  
**Phase ID:** `APP-AUDIT-ANALYTICS-DATA`  
**Branch:** `board/app-audit-analytics-data-3acabd5c`  
**Worktree:** `.worktrees/app-audit-analytics-data`  
**Source Baseline:** Frozen at `origin/main` commit `84937152`  
**Report Destination:** `docs/superpowers/audits/app-audit/APP-AUDIT-ANALYTICS-DATA/report.md`  

---

## 1. Goal and Deliverables

Verify data integrity, presentation parity, and boundary behavior across the six non-screener analytical routes in the application:
1. **Analysis** (`/analysis`)
2. **Chart Workspace** (`/chart`)
3. **Dashboard** (`/dashboard`)
4. **Calendar** (`/calendar`)
5. **Journal** (`/journal`)
6. **Validation** (`/validation`)
... along with their corresponding `@contextRail` parallel slots and underlying data adapters.

The audit establishes exact parity between authoritative backend responses and rendered frontend displays, ensures timestamps and timezones are honest, verifies that exported validation data matches on-screen calculations, and produces reproducible evidence with separately logged defect issues.

**Audit Boundaries:**
- Audit and report scope only. No application code, thresholds, or database schemas are modified during this audit phase.
- Discovered defects are cataloged into structured findings; each actionable defect becomes a separate board remediation ticket.
- No live broker orders, external notifications, destructive database operations, or shared scheduled jobs are triggered.

---

## 2. Scope & Target Surfaces

### A. Analysis (`frontend/app/(frame)/analysis/`, `analysisStore.ts`, `POST /api/analyze-stock`)
- Endpoint: `POST /api/analyze-stock` in `backend/app/routers/stock_scan.py:1285`, invoked via `api.analyzeStock` by `frontend/lib/analysisStore.ts`.
- Single-symbol deep dive: price header, quote freshness, change metrics, trend regime alignment.
- Fundamental health scorecard: Growth (35%), Quality (35%), Risk (30%), overall score (0–100), health grade, D/E ratio, operating margin, debt-to-equity, Piotroski F-score, Altman Z-score (`backend/app/scoring/fundamentals_scorer.py`).
- Sector Relative Strength: `(stock_ret - bench_ret)` computed in `stock_scan.py`.
- Embedded candlestick chart: bar rendering, moving averages (EMA 20/50/200), volume oscillator.
- State variants: Valid symbol, invalid symbol (404), empty fundamentals, unvalidated regime, loading shimmer, network failure.

### B. Chart Workspace (`frontend/app/(frame)/chart/`, `chartStore.ts`, `drawingStore.ts`, `chartAlertStore.ts`, `CandlestickChart`, `CandidateChartWorkspace`)
- Full-page TradingView lightweight-charts workspace (`frontend/components/organisms/ChartWorkspace/index.tsx`): symbol switcher, interval selector (1m, 5m, 15m, 1h, 1D, 1W), date navigation.
- Candidate backtest evidence mode (`frontend/components/organisms/CandidateChartWorkspace/index.tsx`):
  - Auditing candidate query context parsing (`source`, `backtest_artifact_id`, `backtest_artifact_status` via `parseCandidateChartContext`).
  - Historical backtest artifact retrieval (`GET /api/backtest/artifacts/{id}` via `useOriginalBacktest`).
  - Candidate backtest metrics presentation: win rate, return, trade markers, entry/exit fills, benchmark long comparison, and `FreshBacktestControls`.
- Overlays & indicators: EMA lines (20, 50, 200), VWAP, volume histogram.
- Interactive tools: Trendline, horizontal level, ray, rectangle, fibonacci retracement.
- Persistence: `drawingStore` (`'bamendjou:drawings'`), `chartStore` (`'bamendjou:chart'`), `chartAlertStore` (`'bamendjou:alerts'`).
- Alert markers: Placement, price dragging, threshold triggers, websocket broadcast integration.
- Timezone & time axis: NY market hours (09:30–16:00 ET) vs UTC vs local browser time; weekend gaps; unclosed intraday bar handling.

### C. Dashboard (`frontend/app/(frame)/dashboard/`, `portfolioStore.ts`, `portfolioTotals.ts`, `performanceStore.ts`)
- Market overview: S&P 500, Nasdaq 100, Russell 2000, Dow Jones status and daily change.
- Regime banner: Markov / HMM classification, volatility state (VIX level and percentile).
- Portfolio summary cards:
  - Deployed capital, Open P&L, Return %, Positions count calculated via `openTotals` in `frontend/lib/portfolioTotals.ts`.
  - Individual contract Delta / Theta summary.
  - Performance curve: toggleable `EarningsChart` curve backed by `usePerformanceStore`.
- Data polling loop: 30s background interval triggering `syncFromBackend` and `scanPortfolio`.
- Unquoted row handling: exclusion of positions where `quoteUnavailable` is true.
- Option contract multiplier: exact 100x multiplier verification in `deployed = sum(price * multiplier * contracts)`.
- Empty states: zero positions, unconfigured broker, market closed.

### D. Calendar (`frontend/app/(frame)/calendar/`, `events.py`)
- Endpoint: `GET /api/events` in `backend/app/routers/events.py`, fetched via `frontend/lib/api.ts` into page local state (`frontend/app/(frame)/calendar/page.tsx`).
- 6-month side-by-side calendar grid: current month + next 5 months.
- Watchlist symbol filtering: corporate earnings (pre-market / post-market) and dividend dates for symbols in `useWatchlistStore`.
- Event proximity gate badges: `eventProximityGateTooltip` rendering caution/reject windows.
- Timezone anchoring mechanism:
  - Anchoring of `TODAY = new Date(Date.UTC(_now.getFullYear(), _now.getMonth(), _now.getDate()))` and `isoForUTC` in `frontend/app/(frame)/calendar/page.tsx`.
  - Verification that dates do not roll over prematurely for users in timezones west of UTC.
- Fallback context rail: behavior when navigating to/from calendar (default rail fallback).

### E. Journal (`frontend/app/(frame)/journal/`, `journalStore.ts`, `backend/app/routers/journal.py`)
- Router: `/journal` with endpoints `GET /journal/entries`, `POST /journal/entries`, `PUT /journal/entries/{id}`, `DELETE /journal/entries/{id}`.
- State architecture: `useJournalStore` is deliberately in-memory and unpersisted (to prevent stale snapshot overwrites across sessions).
- Trade logs: Execution history, entry/exit price, trade duration, gross P&L, net P&L (after fees), return percentage.
- R-Multiple metric:
  - Exact formula: `r_multiple = net_pnl / risk_dollars` computed on backend and displayed via `RMultipleBadge`.
  - Verification of zero-division / null risk_dollars guards.
- Tagging and notes: Strategy tags, setup notes, review status.
- Mutation error recovery: store rollback and filter re-sync on failed create/update/delete.
- Empty states: Fresh user, no trades logged.

### F. Validation (`frontend/app/(frame)/validation/`, `ValidationTable`, `export.ts`)
- Candidate source: `useScanStore((s) => s.scanResult?.candidates)`.
- Candidate validation table (`frontend/components/organisms/ValidationTable/index.tsx`):
  - Multi-strategy scan results, signal confidence, reward/risk ratios, gate status (PASS/CAUTION/REJECT).
  - Pagination over `safeCandidates` (10 per page).
- Export fidelity:
  - XLSX export generator (`exportValidationToXlsx` in `frontend/lib/export.ts`).
  - Table-to-export parity check: Rank, Symbol, Company, Direction, Score, Status, Trend, Pullback, Trigger, Event, Vol.
  - Audit of export discrepancy: `Confidence` (`c.signalConfidence`) is displayed in the DOM table (`CONF` column) but is omitted from `exportValidationToXlsx` columns.

### G. Context Rails (`frontend/app/(frame)/@contextRail/`)
- Dedicated rail slots: `analysis`, `chart`, `dashboard`, `portfolio`, `screener`, `watchlist`.
- Fallback slot: routes without dedicated rail slots (`calendar`, `journal`, `validation`, `settings`) fall back to `@contextRail/default.tsx`.
- Soft navigation vs hard reload state consistency (interaction with #395 findings).

---

## 3. Detailed Tasks & Execution Methodology

### Task 1: Surface & Route Inventory Reconciliation
- Verify all 6 routes, pages, layouts, modals, and rail slots against Lane A (`APP-AUDIT-INVENTORY`) catalog.
- Document exact source files, Zustand store attachments, and backend API endpoints for each of the 6 target routes.
- Record component tree hierarchy and state models (normal, empty, loading, failed, error boundary).

### Task 2: Data & Arithmetic Parity Audit (The Gate)
1. **Portfolio & Quote Arithmetic:**
   - Verify `openPnLPct = deployed > 0 ? (openPnL / deployed) * 100 : 0` in `openTotals` (`portfolioTotals.ts`).
   - Verify `deployed = sum(price * multiplier * contracts)` with option 100x multiplier.
   - Verify Sector Relative Strength `(stock_ret - bench_ret)` in Analysis (`stock_scan.py`).
   - Verify `r_multiple = net_pnl / risk_dollars` in Journal (`journal.py`).
2. **Fundamental Scoring:**
   - Verify health score weightings: Growth 35% + Quality 35% + Risk 30% = 100% in `fundamentals_scorer.py`.
   - Check handling of missing XBRL tags or non-reporting entities (e.g. recent IPOs, foreign filers).
3. **Chart Series & Time Axes:**
   - Verify OHLCV bar time alignment. Confirm whether bars are stamped at open or close.
   - Verify lightweight-charts bar times in UTC unix timestamp vs ET market hours.
   - Ensure drawings and alerts remain pinned to exact coordinate prices after interval switch and browser reload.
   - Verify CandidateBacktestWorkspace artifact metrics (`win_rate`, `total_return_pct`, `expectancy`) match underlying backtest artifact JSON.
4. **Validation Export Parity:**
   - Execute `exportValidationToXlsx`.
   - Compare cell-by-cell numerical values against the underlying scan candidate store.
   - Check number formatting and document any column omissions (e.g. `signalConfidence` displayed in DOM but omitted in XLSX).

### Task 3: Boundary, Error & State Handling
- Test absent/zero/null data across each surface:
  - Symbol not found (404) on Analysis and Chart.
  - No positions on Dashboard.
  - No upcoming earnings/events on Calendar for selected filters.
  - Zero candidates in Validation table.
- Test network/server failure handling:
  - 500 error / backend unavailable. Verify user-facing error message, no uncaught exceptions or infinite loading spinners.
- Test hydration and reload persistence:
  - Chart active symbol, interval, and drawn annotations after hard reload.
  - Verify `useJournalStore` maintains unpersisted in-memory integrity without localStorage corruption.

### Task 4: Findings Synthesis & Audit Report
- Assemble the comprehensive audit report at `docs/superpowers/audits/app-audit/APP-AUDIT-ANALYTICS-DATA/report.md`.
- Classify findings into:
  - **Gate-Level Defects** (Wrong numbers, data loss, state corruption).
  - **Usability & UI Findings** (Alignment, missing empty state hints, layout inconsistencies).
- File any identified actionable defects as dedicated GitHub issues under programme #348.

---

## 4. Independent Audits & Self-Merge Protocol

1. **Plan Audit (Round 1 & 2):**
   - Round 1 completed: 10 gate findings recorded in `docs/superpowers/audits/APP-AUDIT-ANALYTICS-DATA/plan-r1.md`.
   - Round 2: Fresh independent auditor evaluates revised plan against `audit_rule`.
   - Report recorded to `docs/superpowers/audits/APP-AUDIT-ANALYTICS-DATA/plan-r2.md`.
2. **Execution & Evidence Assembly:**
   - Execute Tasks 1–4, generating runtime evidence, sample calculations, and export comparisons.
   - Record artifacts and findings in `docs/superpowers/audits/app-audit/APP-AUDIT-ANALYTICS-DATA/`.
3. **Code / Report Audit (Round 1):**
   - Fresh independent code auditor reviews `origin/main..HEAD` diff.
   - Checks that report claims match verified code behavior, no unintended mutations were introduced, and all gate criteria pass.
   - Report recorded to `docs/superpowers/audits/APP-AUDIT-ANALYTICS-DATA/code-r1.md`.
4. **PR & Self-Merge:**
   - Commit, push, open PR referencing `Closes #356`.
   - Run CI checks, verify mergeability and 0 drift on `python scripts/state.py`.
   - Self-merge under Step 7 conditions.
