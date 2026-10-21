# APP-AUDIT-ANALYTICS-DATA reconciliation report

**Programme:** APP-AUDIT (#348)  
**Phase ID:** `APP-AUDIT-ANALYTICS-DATA` (#356)  
**Worktree:** `.worktrees/app-audit-analytics-data`  
**Branch:** `board/app-audit-analytics-data-3acabd5c`  
**Target Surfaces:** Analysis (`/analysis`), Chart Workspace (`/chart`), Dashboard (`/dashboard`), Calendar (`/calendar`), Journal (`/journal`), Validation (`/validation`), and parallel `@contextRail` slots.  
**Baseline Commit:** Frozen at `origin/main` (`84937152`)  
**Status:** Audit Complete — Zero Gate Findings on verified logic; 1 Export Parity Discrepancy and 1 Parallel-Rail Navigation finding cataloged.

---

## 1. Executive Summary

This reconciliation report delivers the comprehensive Lane H data, arithmetic, presentation parity, and boundary audit across the six analytical and non-screener routes of Bamendjou:
1. **Analysis** (`/analysis`) — On-demand single-symbol deep dive, macro regime alignment, EDGAR fundamental health scoring, and sector relative strength.
2. **Chart Workspace** (`/chart`) — Standalone lightweight-charts workspace, candidate backtest artifact evidence isolation, indicator calculations, drawings, and chart alert markers.
3. **Dashboard** (`/dashboard`) — Market regime banner, portfolio summary metrics (`openTotals`), contract delta/theta exposure, toggleable earnings curve, and 30-second chained refresh loop.
4. **Calendar** (`/calendar`) — 6-month side-by-side corporate earnings and dividend calendar, timezone-anchored local day calculation, and event proximity gate badges.
5. **Journal** (`/journal`) — Backend-persisted trading journal, unpersisted in-memory Zustand store architecture, monotonic async race prevention, and R-Multiple (`net_pnl / risk_dollars`) calculation.
6. **Validation** (`/validation`) — Scan candidate rule breakdown table and XLSX export fidelity.
7. **Context Rails** (`@contextRail`) — Dedicated vs fallback parallel route slots, soft navigation retention, and state preservation.

All numeric derivations were verified against the project's numerical and persistence gate: no formula puts a wrong number in front of the user, no live broker order is miscalculated, and all persisted data structures adhere to exact storage conventions.

---

## 2. Surface Inventory & Architecture Matrix

| Route | Page Component | Store(s) Attached | Backend Endpoint(s) | Context Rail Slot |
|---|---|---|---|---|
| `/analysis` | `frontend/app/(frame)/analysis/page.tsx` | `useAnalysisStore`<br>`useWatchlistStore`<br>`usePortfolioStore` | `POST /api/analyze-stock`<br>`GET /api/candles/{symbol}`<br>`GET /api/news` | `@contextRail/analysis/page.tsx` (Dedicated) |
| `/chart` | `frontend/app/(frame)/chart/page.tsx`<br>`CandidateChartWorkspace`<br>`ChartWorkspace` | `useChartStore`<br>`useDrawingStore`<br>`useChartAlertStore`<br>`useStructureStore` | `GET /chart/history`<br>`WS /chart/stream/{symbol}`<br>`GET /api/backtest-artifacts/{id}`<br>`GET /chart/drawings` | `@contextRail/chart/page.tsx` (Dedicated) |
| `/dashboard` | `frontend/app/(frame)/dashboard/page.tsx` | `usePortfolioStore`<br>`useScanStore`<br>`useAlertStore`<br>`usePerformanceStore`<br>`useSettingsStore` | `GET /api/portfolio`<br>`GET /api/watchlist`<br>`GET /api/regime`<br>`GET /api/news`<br>`GET /api/performance` | `@contextRail/dashboard/page.tsx` (Dedicated) |
| `/calendar` | `frontend/app/(frame)/calendar/page.tsx` | Page local state (`useState`) | `GET /api/events` | `@contextRail/default.tsx` (Fallback: `RailQuickLook`) |
| `/journal` | `frontend/app/(frame)/journal/page.tsx`<br>`JournalEntryTable`<br>`JournalEntryForm` | `useJournalStore` (strictly in-memory, no `persist`) | `GET /journal/entries`<br>`POST /journal/entries`<br>`PUT /journal/entries/{id}`<br>`DELETE /journal/entries/{id}` | `@contextRail/default.tsx` (Fallback: `RailQuickLook`) |
| `/validation` | `frontend/app/(frame)/validation/page.tsx`<br>`ValidationTable` | `useScanStore`<br>(via `scanResult.candidates`) | None (reads active client scan session in `useScanStore`) | `@contextRail/default.tsx` (Fallback: `RailQuickLook`) |

---

## 3. Data & Arithmetic Parity Audit (The Gate)

### 3.1 Analysis (`/analysis`)

#### Fundamental Health Scoring
- **Source Module:** `backend/app/scoring/fundamentals_scorer.py:99-256`
- **Output Schema:** `FundamentalHealth` (`score`, `quality_label`, `risk_label`, `growth_score`, `quality_score`, `risk_score`, `safety_flags`, `detail`)
- **Bucket Weighting:**
  $$\text{Score} = \text{round}(0.35 \times \text{Growth} + 0.35 \times \text{Quality} + 0.30 \times \text{Risk})$$
  Clamped strictly to $[0, 100]$.
- **Metric Scoring Mechanism (`_metric_score`):**
  - Standard (higher is better): $\text{round}(100 \times \frac{\text{val} - \text{weak}}{\text{strong} - \text{weak}})$
  - Inverted (lower is better, e.g. debt-to-equity, share dilution): $\text{round}(100 \times \frac{\text{weak} - \text{val}}{\text{weak} - \text{strong}})$
  - Missing metric values safely return neutral score: $50$.
- **Metric Assignments:**
  - **Growth:** Revenue growth YoY (`revenue_growth_yoy`, strong: 0.15, weak: 0.0), EPS growth YoY (`eps_growth_yoy`, strong: 0.15, weak: 0.0). Bucket score = $\text{round}((\text{rev} + \text{eps}) / 2)$.
  - **Quality:** Gross margin (`gross_margin`, strong: 0.40, weak: 0.20), Operating margin (`operating_margin`, strong: 0.15, weak: 0.0). Bucket score = $\text{round}((\text{gm} + \text{om}) / 2)$.
  - **Risk:** Debt-to-Equity (`debt_to_equity`, strong: 0.5, weak: 2.0, inverted), Current ratio (`current_ratio`, strong: 2.0, weak: 1.0), Share growth YoY (`share_growth_yoy`, strong: 0.0, weak: 0.03, inverted). Bucket score = $\text{round}((\text{de} + \text{cr} + \text{sg}) / 3)$.
- **Safety Flags:**
  - `negative_equity`: Added if `stockholders_eq < 0` and `reject_on_negative_equity == True`.
  - `extreme_leverage`: Added if `debt_to_equity >= 3.0`.
- **Frontend Presentation:** Handled by `FundamentalHealthCard` (`frontend/components/molecules/FundamentalHealthCard/index.tsx`), applying the strict `FUNDAMENTAL_BAND` thresholds (`PASS >= 65`, `CAUTION >= 40`, `REJECT < 40`). Missing fundamentals for index symbols correctly display `N/A`.

#### Sector Relative Strength
- **Source Module:** `backend/app/routers/stock_scan.py:1256-1274` (`_sector_context`)
- **Arithmetic:**
  $$s_{\text{ret}} = \frac{\text{close}_{-1} - \text{close}_{-(k+1)}}{\text{close}_{-(k+1)}} \times 100$$
  $$\text{bench}_{\text{ret}} = \frac{\text{bench}_{-1} - \text{bench}_{-(k+1)}}{\text{bench}_{-(k+1)}} \times 100$$
  $$\text{rs} = \text{round}(s_{\text{ret}} - \text{bench}_{\text{ret}}, 2)$$
  Evaluated across lookbacks: 1-day (`d1`, $k=1$), 1-week (`w1`, $k=5$), 1-month (`m1`, $k=21$).
- **Frontend Verdict:**
  - $> +0.5\%$: Outperforming (`pass` tone, green).
  - $< -0.5\%$: Lagging (`reject` tone, red).
  - $[-0.5\%, +0.5\%]$: In line (`secondary` tone).
  Exact parity confirmed between backend float rounding and frontend display.

---

### 3.2 Chart Workspace (`/chart`)

#### Series Time Alignment & Coordinates
- **Timestamp Standard:** TradingView lightweight-charts v5:
  - Daily bars use ISO date string `YYYY-MM-DD` (`backend/app/data/market.py:11`).
  - Intraday bars use Unix timestamp in UTC seconds (`backend/app/routers/chart.py:33`).
- **Bar Time Convention:** Daily bars are stamped at close of session. Intraday bars are stamped at open of the bar interval.
- **Candidate Evidence Mode (`CandidateChartWorkspace`):**
  - Isolates candidate backtest evidence from the live workspace.
  - Queries `GET /api/backtest-artifacts/{artifact_id}` via `useOriginalBacktest`.
  - When artifact is loaded, renders `CandidateBacktestWorkspace` with exact frozen backtest metrics (`win_rate`, `total_return_pct`, `expectancy`, entry/exit markers).
  - If artifact is missing or expired (HTTP 410/404), safely displays an informative status message and falls back to live `ChartWorkspace` without crashing.

#### Persistence Conventions
- `bamendjou:chart` — Selected symbol, active interval, chart type, active indicators.
- `bamendjou:drawings` (v1) — Drawn trendlines, horizontal lines, rectangles, fibonacci retracements. Pushed to backend via `POST /chart/drawings` with optimistic local caching.
- `bamendjou:alerts` — Chart-drawn price and indicator alerts.

---

### 3.3 Dashboard (`/dashboard`)

#### Portfolio Calculation Engine (`portfolioTotals.ts`)
- **Deployed Capital:**
  $$\text{deployed} = \sum_{p \in \text{quoted}} p.\text{currentPrice} \times (p.\text{contract.endsWith('|STOCK')} ? 1 : 100) \times (p.\text{contracts} \mathbin{??} 1)$$
  Accurately applies 100x multiplier to option contracts and 1x multiplier to equity positions.
- **Open P&L & Return %:**
  $$\text{openPnL} = \sum_{p \in \text{quoted}} p.\text{pnlDollar}$$
  $$\text{openPnLPct} = \text{deployed} > 0 ? \left(\frac{\text{openPnL}}{\text{deployed}} \times 100\right) : 0$$
  Guarded strictly against zero-division when no capital is deployed.
- **Unquoted Position Safety (NLQ-1):**
  - Positions where `quoteUnavailable === true` are completely excluded from `openTotals` sums.
  - Excluded count is reported via `unquotedNote(unquoted)` (e.g. *"1 position without a live quote excluded from totals"*).
  - Risk exposure calculations (`exposureMark`) fall back to `entryPrice` (cost basis), never defaulting to $0, preventing false approval of oversize trades.

#### Polling Cycle & Performance Curve
- **30-Second Refresh Cycle:** Chains `syncFromBackend` $\to$ immediate `scanPortfolio` on fresh prices $\to$ `fetchPerformance`. Chained promise execution guarantees the alert engine never scans against stale prices.
- **Earnings Curve:** Toggleable `EarningsChart` persisted to `localStorage['bamendjou:showEarnings']`.

---

### 3.4 Calendar (`/calendar`)

#### Timezone Anchoring & Grid Generation
- **Local Day Anchoring:**
  ```typescript
  const _now = new Date();
  const TODAY = new Date(Date.UTC(_now.getFullYear(), _now.getMonth(), _now.getDate()));
  ```
  Anchors "today" to the user's local calendar day expressed at UTC midnight. Prevents premature day rollover for users in timezones behind UTC (such as US Eastern after 8:00 PM ET).
- **Day-Delta Formula:**
  $$\text{days} = \text{round}\left(\frac{\text{selectedDate} - \text{TODAY}}{86,400,000}\right)$$
- **Backend Events:** `GET /api/events` pulls watchlist symbols from `WatchlistSymbolModel`, fetching earnings and dividends via yfinance. Empty watchlist safely returns `[]`.

---

### 3.5 Journal (`/journal`)

#### Architecture & R-Multiple Derivation
- **In-Memory Store Pattern:** `useJournalStore` deliberately avoids `persist()` middleware. All state is mastered directly by the FastAPI backend to prevent stale snapshot overwrites.
- **Async Concurrency Guard:** `latestSyncRequestId` monotonic counter ensures slower out-of-order API responses cannot overwrite newer filter results.
- **R-Multiple Formula (`journal.py:133-143`):**
  $$r\_multiple = \frac{\text{net\_pnl}}{\text{risk\_dollars}}$$
  Guarded: returns `None` if `net_pnl is None` or `risk_dollars is None` or `risk_dollars == 0`.
- **UTC Datetime Normalization:** `@field_validator('entry_date', 'created_at', 'updated_at', mode='after')` restamps UTC timezone on naive datetimes returned by sqlite/aiosqlite.
- **Field Integrity:** 14 trade-only fields (`_TRADE_ONLY_FIELDS`) are strictly rejected on `entry_type == 'note'` payloads via Pydantic model validator.

---

### 3.6 Validation Table & Export Parity (`/validation`)

#### Table-to-Export Comparison
- **Source:** `useScanStore((s) => s.scanResult?.candidates)`.
- **Export Utility:** `exportValidationToXlsx` in `frontend/lib/export.ts`.
- **Column Parity Audit:**

| Metric / Field | ValidationTable (DOM) | Exported XLSX (`exportValidationToXlsx`) | Parity Status |
|---|---|---|---|
| Rank | Implicit row order | `Rank: i + 1` | Verified Match |
| Symbol | `c.symbol` | `Symbol: c.symbol` | Verified Match |
| Company | `c.company` | `Company: c.company` | Verified Match |
| Direction | `c.direction === 'Bullish' ? '↑' : '↓'` | `Direction: c.direction` | Verified Match |
| Trend | `c.stockBreakdown.trend` | `Trend: c.stockBreakdown.trend` | Verified Match |
| Pullback | `c.stockBreakdown.pullback` | `Pullback: c.stockBreakdown.pullback` | Verified Match |
| Trigger | `c.stockBreakdown.trigger` | `Trigger: c.stockBreakdown.trigger` | Verified Match |
| Event | `c.stockBreakdown.event` | `Event: c.stockBreakdown.event` | Verified Match |
| Volatility | `c.stockBreakdown.volatility` | `Vol: c.stockBreakdown.volatility` | Verified Match |
| Overall Score | `c.stockScore` | `Score: c.stockScore` | Verified Match |
| Gate Status | `c.finalStatus` | `Status: c.finalStatus` | Verified Match |
| **Confidence** | `c.confidence` (`ConfidenceBadge`) | **OMITTED** | **Discrepancy (DISP-1)** |

---

## 4. Boundary, Error & State Handling Matrix

| Surface | State Variant | Observed Behavior | Handled Gracefully? |
|---|---|---|---|
| `/analysis` | Symbol Not Found (404) | Catches HTTP 404, clears result, sets `error: "No usable data for {symbol}"` banner. | Yes |
| `/analysis` | Index Ticker (e.g. SPY) | Sets `is_index: true`, fundamentals render `N/A`, IV rank renders `N/A`. | Yes |
| `/analysis` | Missing Fundamentals | `FundamentalHealthCard` renders *"Fundamental Health — no data"*, individual scores default neutral (50). | Yes |
| `/chart` | Invalid Symbol / No Bars | WS sends `{"type": "error", "message": "No chart data..."}`, chart clears cleanly. | Yes |
| `/chart` | Missing Backtest Artifact | `CandidateChartWorkspace` renders informative error and displays live chart without crashing. | Yes |
| `/dashboard` | Empty Portfolio (0 positions) | Cards show `$0` deployed, `0%` return, *"No open positions"*, no division by zero. | Yes |
| `/dashboard` | Unquoted Position | Excluded from totals, row displays `"Quote unavailable"`, warning note shown. | Yes |
| `/dashboard` | Backend Offline | Sets `offline: true`, displays clear message *"Backend not running — start it... to load live data."* | Yes |
| `/calendar` | Empty Watchlist | `GET /api/events` returns `[]`, calendar displays month grids with 0 event dots. | Yes |
| `/journal` | Zero Trades / Fresh State | Renders empty state *"No journal entries yet. Log a trade or a daily note..."*. | Yes |
| `/journal` | Create/Update API 500 | Rolls back optimistic local mutation, re-syncs filters, displays error banner. | Yes |
| `/validation` | No Scan Executed | Table renders *"No scan data. Run a scan to see validation results."* | Yes |

---

## 5. Findings & Discrepancies Catalog

### Discrepancy DISP-1: Confidence Metric Omitted from Validation XLSX Export
- **Classification:** Presentation / Export Parity (Non-Gate)
- **Location:** `frontend/lib/export.ts:43-55` (`exportValidationToXlsx`)
- **Observed Behavior:** The DOM table (`frontend/components/organisms/ValidationTable/index.tsx:101`) renders candidate confidence via `<ConfidenceBadge confidence={c.confidence} />` under the `CONF` column. However, `exportValidationToXlsx` maps only Rank, Symbol, Company, Direction, Score, Status, Trend, Pullback, Trigger, Event, and Vol, completely omitting `Confidence`.
- **Impact:** Users exporting candidate validation tables to Excel do not receive the confidence assessment visible on screen.
- **Recommended Remediation:** Add `'Confidence': c.confidence` to `exportValidationToXlsx` in `export.ts`.

### Finding NAV-1: Calendar & Journal Fallback Context Rail Soft-Navigation Retention
- **Classification:** Route / Parallel Slot Lifecycle (Documented in Lane A, tracked under #395)
- **Location:** `frontend/app/(frame)/@contextRail/`
- **Observed Behavior:** Navigating softly from a route with a dedicated rail slot (e.g. `/dashboard` or `/portfolio`) to a route without one (`/calendar` or `/journal`) can retain the prior route's context rail until hard refresh triggers `@contextRail/default.tsx`.
- **Tracking:** Formally tracked under remediation issue [#395](https://github.com/Netke237/trading-assistant/issues/395).

---

## 6. Verification Evidence

### 6.1 Frontend Typecheck
```bash
npm run typecheck (tsc --noEmit)
# Exit code: 0 (Clean)
```

### 6.2 Focused Frontend Test Suites
```bash
# Calendar timezone anchoring
npm test -- --testPathPattern=calendar
# Tests: 4 passed, 4 total (Time: 41.684 s)

# Analysis page & context rail
npm test -- --testPathPattern=analysis
# Test Suites: 3 passed, 3 total | Tests: 23 passed, 23 total (Time: 42.287 s)

# Journal store & concurrency race prevention
npm test -- --testPathPattern=journalStore
# Test Suites: 1 passed, 1 total | Tests: 11 passed, 11 total (Time: 11.61 s)

# Candidate chart & backtest evidence isolation
npm test -- --testPathPattern=candidateChart
# Test Suites: 2 passed, 2 total | Tests: 21 passed, 21 total (Time: 20.403 s)

# Portfolio totals & store duplicate merge
npm test -- --testPathPattern=portfolioStore
# Test Suites: 2 passed, 2 total | Tests: 124 passed, 124 total (Time: 20.709 s)
```
**Total Verified Tests Across Lane H Surfaces:** 183 passed, 0 failed.

### 6.3 State Verification
```bash
python scripts/state.py
# Result: No drift: every declared status matches the code.
```
