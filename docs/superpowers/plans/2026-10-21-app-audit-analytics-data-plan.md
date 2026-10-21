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

### A. Analysis (`frontend/app/(frame)/analysis/`, `analysisStore.ts`, `/api/stock-analysis`)
- Single-symbol deep dive: price header, quote freshness, change metrics, trend regime alignment.
- Fundamental health scorecard: Growth (35%), Quality (35%), Risk (30%), overall score (0–100), health grade, D/E ratio, operating margin, debt-to-equity, Piotroski F-score, Altman Z-score.
- Embedded candlestick chart: bar rendering, moving averages (EMA 20/50/200), volume oscillator.
- State variants: Valid symbol, invalid symbol (404), empty fundamentals, unvalidated regime, loading shimmer, network failure.

### B. Chart Workspace (`frontend/app/(frame)/chart/`, `chartStore.ts`, `drawingStore.ts`, `chartAlertStore.ts`, `CandlestickChart`)
- Full-page TradingView lightweight-charts workspace: symbol switcher, interval selector (1m, 5m, 15m, 1h, 1D, 1W), date navigation.
- Overlays & indicators: EMA lines (20, 50, 200), VWAP, volume histogram.
- Interactive tools: Trendline, horizontal level, ray, rectangle, fibonacci retracement.
- Persistence: `drawingStore` (`'bamendjou:drawings'`), `chartStore` (`'bamendjou:chart'`), `chartAlertStore` (`'bamendjou:alerts'`).
- Alert markers: Placement, price dragging, threshold triggers, websocket broadcast integration.
- Timezone & time axis: NY market hours (09:30–16:00 ET) vs UTC vs local browser time; weekend gaps; unclosed intraday bar handling.

### C. Dashboard (`frontend/app/(frame)/dashboard/`, `portfolioStore.ts`, `market.py`)
- Market overview: S&P 500, Nasdaq 100, Russell 2000, Dow Jones status and daily change.
- Regime banner: Markov / HMM classification, volatility state (VIX level and percentile), sector performance heatmap.
- Portfolio summary cards: Net liquidation value, open P&L, day P&L, margin utilization, Greeks (Delta, Gamma, Theta, Vega).
- Live / paper broker connection indicator.
- Empty states: zero positions, unconfigured broker, market closed.

### D. Calendar (`frontend/app/(frame)/calendar/`, `calendarStore.ts`, `/api/calendar`)
- Events feed: Corporate earnings (pre-market / after-market), dividends, FOMC meetings, economic releases (CPI, PPI, Jobs, GDP).
- Horizon filtering: Today, Next 7 Days, Next 30 Days, Next 90 Days.
- Impact badges (High, Medium, Low) and ticker association.
- Timezone honesty: Announcement time ET vs local user timezone.
- Fallback context rail: behavior when navigating to/from calendar.

### E. Journal (`frontend/app/(frame)/journal/`, `journalStore.ts`, `/api/journal`)
- Trade logs: Execution history, entry/exit price, trade duration, gross P&L, net P&L (after fees), return percentage.
- Tagging and notes: Strategy tags, setup screenshots, psychological notes, trade review status.
- Win rate, expectancy, profit factor, max drawdown statistics calculation.
- Empty states: Fresh user, no trades logged.

### F. Validation (`frontend/app/(frame)/validation/`, `validationStore.ts`, export engine)
- Candidate validation table: Multi-strategy scan results, signal confidence, reward/risk ratios, gate status (PASS/CAUTION/REJECT).
- Filtering & sorting: Score thresholds, symbol search, sector filters, pagination totals.
- Export fidelity: XLSX and CSV export generators (`exportValidationToXlsx`, `exportValidationToCsv`).
- Parity check: Exported numeric values (prices, percentages, dates, scores) vs rendered DOM table values.

### G. Context Rails (`frontend/app/(frame)/@contextRail/`)
- Rail slots for `analysis`, `chart`, `dashboard`, `portfolio`, `screener`, `watchlist`.
- Default slot fallback for routes without dedicated rails (`calendar`, `journal`, `validation`, `settings`).
- Soft navigation vs hard reload state consistency (interaction with #395 findings).

---

## 3. Detailed Tasks & Execution Methodology

### Task 1: Surface & Route Inventory Reconciliation
- Verify all routes, pages, layouts, modals, and rail slots against Lane A (`APP-AUDIT-INVENTORY`) catalog.
- Document exact source files, Zustand store attachments, and backend API endpoints for each of the 6 target routes.
- Record component tree hierarchy and state models (normal, empty, loading, failed, error boundary).

### Task 2: Data & Arithmetic Parity Audit (The Gate)
1. **Prices & Quotes:**
   - Verify bid/ask/mid/last calculations in Analysis and Dashboard.
   - Verify percentage gain/loss calculations: `(last - close_prev) / close_prev * 100` vs `(last - entry) / entry * 100`.
2. **Fundamental Scoring:**
   - Verify health score weightings: Growth 35% + Quality 35% + Risk 30% = 100%.
   - Check handling of missing XBRL tags or non-reporting entities (e.g. recent IPOs, foreign filers).
3. **Chart Series & Time Axes:**
   - Verify OHLCV bar time alignment. Confirm whether bars are stamped at open or close.
   - Verify lightweight-charts bar times in UTC unix timestamp vs ET market hours.
   - Ensure drawings and alerts remain pinned to exact coordinate prices after interval switch and browser reload.
4. **Validation Export Parity:**
   - Execute XLSX and CSV export routines.
   - Compare cell-by-cell numerical values against the underlying scan candidate store.
   - Verify that formatting (e.g. 15.4% vs 0.154, $142.50 vs 142.5) preserves numeric precision without truncation or rounding bias.

### Task 3: Boundary, Error & State Handling
- Test absent/zero/null data across each surface:
  - Symbol not found (404) on Analysis and Chart.
  - No positions on Dashboard and Journal.
  - No upcoming earnings/events on Calendar for selected filters.
  - Zero candidates in Validation table.
- Test network/server failure handling:
  - 500 error / backend unavailable. Verify user-facing error message, no uncaught exceptions or infinite loading spinners.
- Test hydration and reload persistence:
  - Chart active symbol, interval, and drawn annotations after hard reload.
  - Journal entry draft persistence.

### Task 4: Findings Synthesis & Audit Report
- Assemble the comprehensive audit report at `docs/superpowers/audits/app-audit/APP-AUDIT-ANALYTICS-DATA/report.md`.
- Classify findings into:
  - **Gate-Level Defects** (Wrong numbers, data loss, state corruption).
  - **Usability & UI Findings** (Alignment, missing empty state hints, layout inconsistencies).
- File any identified actionable defects as dedicated GitHub issues under programme #348.

---

## 4. Independent Audits & Self-Merge Protocol

1. **Plan Audit (Round 1):**
   - Fresh independent auditor evaluates this plan against `audit_rule` and Lane H acceptance criteria.
   - Reviewer checks scope completeness, numeric gate invariants, and reproducibility.
   - Report recorded to `docs/superpowers/audits/APP-AUDIT-ANALYTICS-DATA/plan-r1.md`.
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
