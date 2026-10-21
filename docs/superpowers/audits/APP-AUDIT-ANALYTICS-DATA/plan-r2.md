# APP-AUDIT-ANALYTICS-DATA (Lane H, #356) — Plan Audit Round 2 Report

**Target Plan:** `docs/superpowers/plans/2026-10-21-app-audit-analytics-data-plan.md`  
**Branch:** `board/app-audit-analytics-data-3acabd5c`  
**Worktree:** `.worktrees/app-audit-analytics-data`  
**Auditor:** Independent Subagent (`999b77c7-e9da-40f3-940d-9e6d7cf01226`)  
**Skill Applied:** `bmad-review-adversarial-general`  
**Status:** **NOT CLEAN — 4 Findings**

---

## 1. Audit Scope & Verification of Round 1 Fixes

The Round 2 audit reviewed the changes in `git -C .worktrees/app-audit-analytics-data diff ea68a39e..HEAD` (commit `5d166bae`) and cross-checked each of the 10 Round 1 fixes against the live codebase:

1. **Analysis Endpoint & Service Wiring:** Verified. Section 2.A correctly specifies `POST /api/analyze-stock` in `backend/app/routers/stock_scan.py:1285`, invoked via `api.analyzeStock` by `frontend/lib/analysisStore.ts`.
2. **Chart Candidate Evidence Mode:** Verified. Added `CandidateChartWorkspace` (`frontend/components/organisms/CandidateChartWorkspace/index.tsx`) to Section 2.B scope, auditing `parseCandidateChartContext`, `useOriginalBacktest`, and `FreshBacktestControls`.
3. **Dashboard Real Metrics & Polling:** Verified. Corrected portfolio summary cards to match `frontend/app/(frame)/dashboard/page.tsx` and `openTotals` in `frontend/lib/portfolioTotals.ts` (Deployed, Open P&L, Return %, Positions), Delta / Theta per contract, toggleable `EarningsChart` curve (`usePerformanceStore`), and 30s background cycle running `syncFromBackend` and `scanPortfolio`.
4. **Calendar Local State & Endpoints:** Verified. Scoped to `frontend/app/(frame)/calendar/page.tsx` local state, `GET /api/events` (`backend/app/routers/events.py`), 6-month side-by-side grid, and earnings/dividend dates for watchlist symbols with `eventProximityGateTooltip`.
5. **Calendar Timezone Anchoring:** Verified. Section 2.D explicitly includes verification of `TODAY = new Date(Date.UTC(_now.getFullYear(), _now.getMonth(), _now.getDate()))` and `isoForUTC` in `frontend/app/(frame)/calendar/page.tsx` to prevent date rollover for timezones west of UTC.
6. **Journal Endpoints & R-Multiple Calculation:** Verified. Corrected Journal scope to backend router `/journal` (`backend/app/routers/journal.py`) with `GET /journal/entries`, `POST /journal/entries`, `PUT /journal/entries/{id}`, `DELETE /journal/entries/{id}`, and the computed field `r_multiple = net_pnl / risk_dollars` rendered via `RMultipleBadge`.
7. **Journal State Architecture:** Verified. Task 3 replaced "Journal entry draft persistence" with verifying that `useJournalStore` maintains unpersisted in-memory integrity without localStorage corruption.
8. **Validation Candidate Source & Pagination:** Verified. Replaced phantom `validationStore.ts` with `useScanStore((s) => s.scanResult?.candidates)`, `exportValidationToXlsx` in `frontend/lib/export.ts`, and pagination over `safeCandidates` (10 per page) in `ValidationTable/index.tsx`.
9. **Validation Export Parity & Disparity:** Verified. Task 2.4 updated to check actual columns (Rank, Symbol, Company, Direction, Score, Status, Trend, Pullback, Trigger, Event, Vol) and explicitly audits the omission of Confidence from XLSX export despite being displayed in DOM table.
10. **Arithmetic Parity:** Verified. Task 2.1 now verifies actual arithmetic on target surfaces:
    - `openPnLPct = deployed > 0 ? (openPnL / deployed) * 100 : 0` in `openTotals` (`portfolioTotals.ts`).
    - `deployed = sum(price * multiplier * contracts)` with option 100x multiplier.
    - Sector Relative Strength `(stock_ret - bench_ret)` in Analysis (`stock_scan.py:1269-1271`).
    - `r_multiple = net_pnl / risk_dollars` in Journal (`journal.py:133-143`).

---

## 2. Findings

- **location:** `docs/superpowers/plans/2026-10-21-app-audit-analytics-data-plan.md:46` (Section 2.B Chart Workspace)  
  **trigger_condition:** Endpoint path for historical backtest artifact retrieval is specified as `GET /api/backtest/artifacts/{id}` instead of the actual FastAPI router endpoint `GET /api/backtest-artifacts/{artifact_id}` (`backend/app/routers/backtest_artifacts.py:9, 26` and `frontend/lib/api.ts:430`).  
  **guard_snippet:** Update Section 2.B line 46 to reference `GET /api/backtest-artifacts/{artifact_id}` (or `GET /api/backtest-artifacts/{id}`) via `api.getOriginalBacktest` / `useOriginalBacktest`.  
  **potential_consequence:** Anyone testing, scripting, or auditing the artifact retrieval endpoint directly over HTTP using the plan's path `/api/backtest/artifacts/{id}` will receive a 404 Not Found error from FastAPI.

- **location:** `docs/superpowers/plans/2026-10-21-app-audit-analytics-data-plan.md:37` (Section 2.A Analysis)  
  **trigger_condition:** Section 2.A asserts that `backend/app/scoring/fundamentals_scorer.py` evaluates `Piotroski F-score` and `Altman Z-score`, neither of which exists in `fundamentals_scorer.py`, `edgar.py`, or anywhere in the codebase.  
  **guard_snippet:** Remove `Piotroski F-score, Altman Z-score` from Section 2.A line 37 and align with the actual scored detail metrics in `fundamentals_scorer.py`: revenue growth YoY, EPS growth YoY, gross margin, operating margin, debt-to-equity, current ratio, share growth YoY, and safety flags (`negative_equity`, `extreme_leverage`).  
  **potential_consequence:** An auditor or engineer checking arithmetic parity on `/analysis` against `fundamentals_scorer.py` will attempt to verify or implement non-existent financial metrics, reporting false defects against correct code.

- **location:** `docs/superpowers/plans/2026-10-21-app-audit-analytics-data-plan.md:95, 128` (Section 2.F and Task 2.4 Validation)  
  **trigger_condition:** Plan refers to the candidate confidence property as `c.signalConfidence`, but the actual property on `TradeCardData` rendered in `ValidationTable/index.tsx:101` is `c.confidence` (and `c.confidenceText`) (`frontend/types/domain.ts:733`).  
  **guard_snippet:** Replace `c.signalConfidence` with `c.confidence` in Section 2.F line 95 and Task 2.4 line 128.  
  **potential_consequence:** Test harnesses or scripts written according to the plan will query `candidate.signalConfidence` which evaluates to `undefined`, creating false parity mismatch errors against the rendered Confidence badge.

- **location:** `docs/superpowers/plans/2026-10-21-app-audit-analytics-data-plan.md:134` (Section 3, Task 3 Boundary Handling)  
  **trigger_condition:** Task 3 prescribes testing "No upcoming earnings/events on Calendar for selected filters", lingering from the pre-Round-1 assumption of calendar filters, whereas Calendar has no filter controls (`frontend/app/(frame)/calendar/page.tsx`).  
  **guard_snippet:** Update Task 3 line 134 to "No upcoming earnings/events on Calendar when watchlist is empty or symbols have no scheduled events".  
  **potential_consequence:** Auditors or testers will waste time attempting to test non-existent UI filter states on `/calendar`.

---

## 3. Verdict

The Round 1 fixes substantially improved plan accuracy, but because the above 4 mechanism/route/property mismatches remain in the plan, the plan is **NOT CLEAN (4 findings)**. These 4 findings can be addressed in a single revision to enable a clean Round 3 plan audit.
