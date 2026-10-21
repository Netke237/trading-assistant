# Adversarial Code/Report Audit Report (Round 1): APP-AUDIT-ANALYTICS-DATA

**Target:** Diff between `origin/main` and `HEAD`  
**Phase ID:** `APP-AUDIT-ANALYTICS-DATA` (#356)  
**Branch:** `board/app-audit-analytics-data-3acabd5c`  
**Worktree:** `.worktrees/app-audit-analytics-data`  
**Reviewer:** Independent adversarial auditor (subagent `f4a0d407-ef5a-47ee-b648-a2aadc596f19`)  
**Skill Applied:** `bmad-review-adversarial-general`  
**Reviewed Artifacts:**
- Reconciliation Report: `docs/superpowers/audits/app-audit/APP-AUDIT-ANALYTICS-DATA/report.md`
- Execution Plan: `docs/superpowers/plans/2026-10-21-app-audit-analytics-data-plan.md`
- Source Code Across 6 Surfaces and Context Rails (`/analysis`, `/chart`, `/dashboard`, `/calendar`, `/journal`, `/validation`, `@contextRail`)
- Branch State: `docs/superpowers/PROJECT_STATE.json`

**Gate Standard:** Numeric / Persistence Gate (a finding blocks ONLY if it can put a WRONG NUMBER in front of a user or on a broker order, or CORRUPT PERSISTED DATA; a comment blocks only if a competent reader acting on it would write a wrong change).

**Status:** **CLEAN (0 Gate Findings)**

---

## 1. Audit Scope & Verification Matrix

The audit evaluated the reconciliation report and branch diff against the live codebase across all 6 analytical surfaces and parallel slots:

### 1. Analysis (`/analysis`)
- **Backend Endpoint:** `POST /api/analyze-stock` in `backend/app/routers/stock_scan.py:1285` (invoked via `api.analyzeStock` by `frontend/lib/analysisStore.ts:97`). Replays last scan request or falls back to live settings with explicit UI disclosure (`basis`).
- **Fundamental Health Scoring (`backend/app/scoring/fundamentals_scorer.py:99-256`):**
  - Bucket weights: $\text{round}(0.35 \times \text{growth} + 0.35 \times \text{quality} + 0.30 \times \text{risk})$, clamped to $[0, 100]$.
  - `_metric_score`: Normalizes values between `strong` and `weak` thresholds; handles inverted metrics (debt-to-equity, share growth); missing metrics safely default to neutral score 50.
  - Detail metrics: Exactly 8 metrics verified in `FundamentalsOut`: revenue growth YoY, EPS growth YoY, gross margin, operating margin, debt-to-equity, current ratio, share growth YoY, and safety flags (`negative_equity`, `extreme_leverage`).
  - Presentation: `FundamentalHealthCard` (`frontend/components/molecules/FundamentalHealthCard/index.tsx`) strictly applies `FUNDAMENTAL_BAND` thresholds (`PASS >= 65`, `CAUTION >= 40`, `REJECT < 40`). Correctly displays `N/A` for index tickers (`is_index: true`).
- **Sector Relative Strength (`backend/app/routers/stock_scan.py:1256-1274`):**
  - Formulas: $s_{\text{ret}} = \frac{\text{close}_{-1} - \text{close}_{-(k+1)}}{\text{close}_{-(k+1)}} \times 100$, $\text{bench}_{\text{ret}} = \frac{\text{bench}_{-1} - \text{bench}_{-(k+1)}}{\text{bench}_{-(k+1)}} \times 100$, $\text{rs} = \text{round}(s_{\text{ret}} - \text{bench}_{\text{ret}}, 2)$.
  - Lookbacks: `d1` ($k=1$), `w1` ($k=5$), `m1` ($k=21$).
  - Frontend Display (`frontend/app/(frame)/analysis/page.tsx:192-208`): $> +0.5\%$ outperforming (`pass`), $< -0.5\%$ lagging (`reject`), $[-0.5\%, +0.5\%]$ in line (`secondary`).

### 2. Chart Workspace (`/chart`)
- **lightweight-charts Time Alignment:** Daily bars use ISO date string `YYYY-MM-DD` (close of session); intraday bars use UTC epoch seconds (open of bar interval).
- **Candidate Evidence Mode (`CandidateChartWorkspace/index.tsx`):**
  - Isolates candidate backtest evidence via `useOriginalBacktest(context)`.
  - Artifact retrieval via `GET /api/backtest-artifacts/{artifact_id}` (`backend/app/routers/backtest_artifacts.py:26`).
  - Renders `CandidateBacktestWorkspace` with frozen historical metrics (`win_rate`, `total_return_pct`, `expectancy`, entry/exit markers).
  - Handles missing/expired artifacts (404/410) gracefully, displaying informative status without crashing, falling back to live `ChartWorkspace`.
- **Persistence Keys:**
  - `bamendjou:chart` (v2, `chartStore.ts:95`).
  - `bamendjou:drawings` (v1, `drawingStore.ts:96`).
  - `bamendjou:alerts` (v2, `chartAlertStore.ts:550`).

### 3. Dashboard (`/dashboard`)
- **Portfolio Totals (`frontend/lib/portfolioTotals.ts:28-44`):**
  - Deployed capital: $\text{deployed} = \sum_{p \in \text{quoted}} p.\text{currentPrice} \times (p.\text{contract.endsWith('|STOCK')} ? 1 : 100) \times (p.\text{contracts} \mathbin{??} 1)$. Correct 100x multiplier for options.
  - Open P&L %: `openPnLPct = deployed > 0 ? (openPnL / deployed) * 100 : 0`. Zero-division guard confirmed.
  - Unquoted row handling (NLQ-1): Positions with `quoteUnavailable === true` excluded from sums; count reported via `unquotedNote`. Exposure mark (`exposureMark`) falls back to `entryPrice` (never $0).
- **30-Second Refresh Cycle:** Chains `syncFromBackend` $\to$ `scanPortfolio` $\to$ `fetchPerformance` to guarantee alerts never evaluate on stale quotes.
- **Earnings Curve:** Persisted to `localStorage['bamendjou:showEarnings']`.

### 4. Calendar (`/calendar`)
- **Timezone Anchoring (`frontend/app/(frame)/calendar/page.tsx:27-28`):**
  - `TODAY = new Date(Date.UTC(_now.getFullYear(), _now.getMonth(), _now.getDate()))` anchors "today" to local day at UTC midnight, preventing premature day rollover for users west of UTC.
  - Day delta: `Math.round((selectedDate.getTime() - TODAY.getTime()) / 86_400_000)`.
- **Backend Endpoint:** `GET /api/events` (`backend/app/routers/events.py:15`). Queries `WatchlistSymbolModel` and returns empty list `[]` when watchlist is empty.

### 5. Journal (`/journal`)
- **State Architecture (`frontend/lib/journalStore.ts`):** Strictly in-memory Zustand store; deliberately omits `persist()` to prevent stale localStorage snapshots from overwriting server-authoritative trade history.
- **Concurrency Guard:** `latestSyncRequestId` monotonic counter prevents out-of-order API responses from overwriting newer filter queries.
- **Mutation Rollback:** Failed create/update/delete actions rollback optimistic local changes, re-sync with backend via `await syncEntries(lastFilters)`, and only then set error messages.
- **R-Multiple Formula (`backend/app/routers/journal.py:133-143`):**
  - Computed field `r_multiple = net_pnl / risk_dollars`.
  - Null and zero-division guards: returns `None` if `net_pnl is None` or `risk_dollars is None` or `risk_dollars == 0`.
  - Renders via `RMultipleBadge` (`frontend/components/atoms/RMultipleBadge/index.tsx`).
- **Naive Datetime Normalization:** Restamps UTC timezone (`tzinfo=timezone.utc`) on naive datetimes returned by SQLite.

### 6. Validation (`/validation`)
- **Candidate Data:** Reads active scan candidates from `useScanStore((s) => s.scanResult?.candidates)`.
- **Validation Table (`ValidationTable/index.tsx`):** Displays Rank, Symbol, Company, Direction, Trend, Pullback, Trigger, Event, Vol, Score, Confidence (`c.confidence`), Status.
- **Export Parity & Discrepancy Characterization:**
  - `exportValidationToXlsx` (`frontend/lib/export.ts:43-55`) exports Rank, Symbol, Company, Direction, Score, Status, Trend, Pullback, Trigger, Event, Vol.
  - The report accurately catalogs **DISP-1**: Candidate confidence (`c.confidence`) is displayed in the DOM table (`CONF` column) but is omitted from XLSX export. Characterized correctly as a presentation/export parity discrepancy (non-gate).

### 7. Context Rails (`@contextRail`)
- Dedicated slots: `analysis/page.tsx`, `chart/page.tsx`, `dashboard/page.tsx`.
- Fallback slot: routes without dedicated slots (`calendar`, `journal`, `validation`) render `@contextRail/default.tsx` (`RailQuickLook`).
- Accurately references and aligns with finding NAV-1 / issue #395 regarding parallel slot soft-navigation retention.

---

## 2. Examination of Required Questions

1. **Does the reconciliation report accurately describe the arithmetic, data flow, error handling, and state models of each surface?**  
   **YES.** Every formula, data flow pipeline, boundary state, and error handling mechanism matches the production code verbatim.
2. **Are all calculations verified against the actual source?**  
   **YES.** Fundamental health (35/35/30), Sector RS (1d/5d/21d returns), `openTotals` (100x multiplier and zero-division guard), `r_multiple` (`net_pnl / risk_dollars` with null/zero guards), and Calendar `TODAY` UTC midnight anchoring were directly inspected in the source code and confirmed.
3. **Is the validation table vs export disparity correctly identified and characterized?**  
   **YES.** The omission of `c.confidence` from `exportValidationToXlsx` despite being rendered in `ValidationTable` is cataloged as DISP-1 and classified under presentation/export parity.
4. **Are persistence keys and behaviors faithfully audited?**  
   **YES.** All keys (`bamendjou:chart`, `bamendjou:drawings`, `bamendjou:alerts`) and the unpersisted in-memory architecture of `useJournalStore` were verified.
5. **Did this audit phase modify any application code or introduce any unintended mutations?**  
   **NO.** `git diff origin/main..HEAD` confirms 0 application code files modified. Only documentation (`report.md`, `plan-r*.md`, execution plan) and `PROJECT_STATE.json` were committed.

---

## 3. Verification Commands & Evidence

- **Frontend Typecheck:** `npm run typecheck` (`tsc --noEmit`) $\to$ **Exit code: 0 (Clean)**
- **Calendar Timezone Anchoring Jest Suite:** `npm test -- --testPathPattern=calendar` $\to$ **4 passed, 4 total (PASS)**
- **State Probe Check:** `python scripts/state.py` $\to$ **"No drift: every declared status matches the code."**
- **Git Working Tree:** Clean.

---

## 4. Verdict

The code and reconciliation report for phase **APP-AUDIT-ANALYTICS-DATA** (#356) are completely accurate, technically sound, and introduce zero regressions or mutations.

**GATE FINDINGS: 0**  
**AUDIT STATUS: CLEAN**
