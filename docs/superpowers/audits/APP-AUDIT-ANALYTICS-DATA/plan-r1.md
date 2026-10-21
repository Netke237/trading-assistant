# APP-AUDIT-ANALYTICS-DATA (Lane H, #356) — Plan Audit Round 1 Report

**Target Plan:** `docs/superpowers/plans/2026-10-21-app-audit-analytics-data-plan.md`  
**Branch:** `board/app-audit-analytics-data-3acabd5c`  
**Worktree:** `.worktrees/app-audit-analytics-data`  
**Auditor:** Independent Subagent (`e97f7b44-0625-4e60-871f-708f8299d989`)  
**Skill Applied:** `bmad-review-adversarial-general`  
**Status:** **NOT CLEAN — 10 Gate-Level Findings**

---

### Gate Findings

- **location:** `docs/superpowers/plans/2026-10-21-app-audit-analytics-data-plan.md:34` (Section 2.A Analysis)  
  **trigger_condition:** Plan targets non-existent endpoint `/api/stock-analysis` instead of the authoritative `POST /api/analyze-stock` (`backend/app/routers/stock_scan.py:1285`).  
  **guard_snippet:** Update scope and audit instructions to target `POST /api/analyze-stock` in `backend/app/routers/stock_scan.py` called by `frontend/lib/analysisStore.ts` via `api.analyzeStock`.  
  **potential_consequence:** A reader or test harness implementing or auditing this lane will verify a non-existent route (`/api/stock-analysis` returns 404), leaving the actual `POST /api/analyze-stock` calculations (regime by horizon, sector RS, gate flags) unaudited, or implement an unintended redundant proxy endpoint.

- **location:** `docs/superpowers/plans/2026-10-21-app-audit-analytics-data-plan.md:40-47` (Section 2.B Chart Workspace)  
  **trigger_condition:** Plan completely omits `CandidateChartWorkspace` / `CandidateBacktestWorkspace` and its backtest artifact evidence mode on route `/chart`.  
  **guard_snippet:** Add `CandidateChartWorkspace` (`frontend/components/organisms/CandidateChartWorkspace/index.tsx`) to Section 2.B scope, auditing the candidate query context (`source`, `backtest_artifact_id`, `backtest_artifact_status` via `parseCandidateChartContext`), historical artifact retrieval (`/api/backtest/artifacts/{id}` via `useOriginalBacktest`), and `FreshBacktestControls`.  
  **potential_consequence:** The candidate backtest metrics (win rate, return, trade markers, entry/exit fills) displayed on `/chart` when linked from scanner results will be completely bypassed by the audit, permitting display of unverified backtest figures and regressions in artifact state transitions.

- **location:** `docs/superpowers/plans/2026-10-21-app-audit-analytics-data-plan.md:50-52` (Section 2.C Dashboard)  
  **trigger_condition:** Plan misstates Dashboard portfolio metrics as "Net liquidation value, open P&L, day P&L, margin utilization, Greeks (Delta, Gamma, Theta, Vega)" and claims a "sector performance heatmap" and "broker connection indicator" are present.  
  **guard_snippet:** Revise Dashboard portfolio audit scope to match actual components in `frontend/app/(frame)/dashboard/page.tsx`: Deployed, Open P&L, Return %, Positions (via `openTotals` in `frontend/lib/portfolioTotals.ts`), individual contract Delta/Theta display, toggleable `EarningsChart` curve (`usePerformanceStore`), and 30s live quote/alert polling loop (`syncFromBackend`, `scanPortfolio`).  
  **potential_consequence:** An auditor acting on the plan will audit non-existent metrics and report false defects against the real dashboard implementation, while failing to verify the actual arithmetic of `openTotals`, unquoted row exclusion (`quoteUnavailable`), and option contract 100x multiplier calculations.

- **location:** `docs/superpowers/plans/2026-10-21-app-audit-analytics-data-plan.md:55-58` (Section 2.D Calendar)  
  **trigger_condition:** Plan asserts existence of non-existent `calendarStore.ts` and `/api/calendar` endpoint, and claims "Horizon filtering", "Impact badges", and "FOMC meetings / economic releases" exist.  
  **guard_snippet:** Correct Calendar scope to use `frontend/app/(frame)/calendar/page.tsx` local state, `GET /api/events` (`backend/app/routers/events.py`), the 6-month side-by-side calendar grid, and earnings/dividend events for watchlist symbols with proximity gate badges (`eventProximityGateTooltip`).  
  **potential_consequence:** An auditor or engineer acting on the plan will write tests against non-existent endpoints and non-existent stores, or erroneously attempt to introduce a redundant store or filter controls that conflict with the page's current 6-month grid architecture.

- **location:** `docs/superpowers/plans/2026-10-21-app-audit-analytics-data-plan.md:59` (Section 2.D Calendar)  
  **trigger_condition:** Plan fails to specify the critical timezone anchoring mechanism in Calendar (`TODAY` local date converted to UTC midnight).  
  **guard_snippet:** Explicitly include verification of `TODAY = new Date(Date.UTC(_now.getFullYear(), _now.getMonth(), _now.getDate()))` and `isoForUTC` in `frontend/app/(frame)/calendar/page.tsx` to verify dates do not roll over prematurely for users in timezones west of UTC.  
  **potential_consequence:** Without auditing this mechanism, timezone handling defects that shift calendar day markers and event day-counts by +/- 1 day for non-UTC users will not be evaluated.

- **location:** `docs/superpowers/plans/2026-10-21-app-audit-analytics-data-plan.md:62-65` (Section 2.E Journal)  
  **trigger_condition:** Plan asserts existence of endpoint `/api/journal`, claims the journal calculates "Win rate, expectancy, profit factor, max drawdown statistics", and supports "setup screenshots".  
  **guard_snippet:** Correct Journal scope to backend router `/journal` (`backend/app/routers/journal.py`) with endpoints `GET /journal/entries`, `POST /journal/entries`, `PUT /journal/entries/{id}`, `DELETE /journal/entries/{id}`, and audit the actual computed field `r_multiple = net_pnl / risk_dollars` (`RMultipleBadge`) rather than non-existent summary statistics.  
  **potential_consequence:** A reader acting on this plan will write tests expecting aggregate statistics calculation in the Journal where none exists, while failing to audit the actual backend computation of `r_multiple` and its zero-division / null-handling guards.

- **location:** `docs/superpowers/plans/2026-10-21-app-audit-analytics-data-plan.md:114` (Section 3, Task 3 Boundary Handling)  
  **trigger_condition:** Plan prescribes testing "Journal entry draft persistence", contradicting `useJournalStore`'s deliberate unpersisted design.  
  **guard_snippet:** Remove "Journal entry draft persistence" from Task 3 and replace with verifying that `useJournalStore` maintains backend-authoritative state without un-persisted local storage corruption and that mutation failure recovery re-syncs filters.  
  **potential_consequence:** An implementer or auditor acting on this will attempt to add or assert `localStorage` draft persistence to `journalStore`, re-introducing the stale snapshot overwrite bugs that `journalStore.ts` explicitly documented avoiding.

- **location:** `docs/superpowers/plans/2026-10-21-app-audit-analytics-data-plan.md:68-71` (Section 2.F Validation)  
  **trigger_condition:** Plan asserts existence of `validationStore.ts`, `exportValidationToCsv`, and "Filtering & sorting: Score thresholds, symbol search, sector filters".  
  **guard_snippet:** Correct Validation scope to source candidates from `useScanStore((s) => s.scanResult?.candidates)`, test `exportValidationToXlsx` in `frontend/lib/export.ts`, and audit pagination over `safeCandidates` in `frontend/components/organisms/ValidationTable/index.tsx`.  
  **potential_consequence:** A developer or auditor will attempt to import or create a phantom `validationStore.ts` and test non-existent search/filter inputs and CSV export, failing to audit the real candidate data pipeline.

- **location:** `docs/superpowers/plans/2026-10-21-app-audit-analytics-data-plan.md:72-73, 99-102` (Section 2.F and Task 2.4 Validation Export Parity)  
  **trigger_condition:** Plan claims export parity checks "prices, percentages, dates" between export and DOM, while missing the actual fields and the missing `Confidence` (`CONF`) export disparity.  
  **guard_snippet:** Update Task 2.4 to verify the actual exported columns of `exportValidationToXlsx` (Rank, Symbol, Company, Direction, Score, Status, Trend, Pullback, Trigger, Event, Vol) against DOM table columns, and audit the omission of `Confidence` (`c.signalConfidence`) from the XLSX export despite being displayed in the DOM table.  
  **potential_consequence:** Parity check will test non-existent price/date columns in the export while missing real numerical disparity where confidence values displayed in the UI are omitted from exported files.

- **location:** `docs/superpowers/plans/2026-10-21-app-audit-analytics-data-plan.md:90-91` (Section 3, Task 2.1 Prices & Quotes)  
  **trigger_condition:** Plan instructs verifying `(last - close_prev) / close_prev * 100` vs `(last - entry) / entry * 100`, which are not used by the audited routes.  
  **guard_snippet:** Replace with verifying actual arithmetic used on the surfaces: `openPnLPct = deployed > 0 ? (openPnL / deployed) * 100 : 0` and `deployed = sum(price * multiplier * contracts)` in `openTotals` (`portfolioTotals.ts`), Sector Relative Strength `(stock_ret - bench_ret)` in Analysis (`stock_scan.py`), and `r_multiple = net_pnl / risk_dollars` in Journal (`journal.py`).  
  **potential_consequence:** The data arithmetic audit will evaluate irrelevant formulas and fail to audit the actual portfolioDeployed, openPnL, and R-multiple calculations that directly present financial numbers to the user.
