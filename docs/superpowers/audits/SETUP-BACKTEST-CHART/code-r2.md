# Code Audit Round 2: SETUP-BACKTEST-CHART (#391)

**Reviewer:** Independent Subagent (Adversarial General Reviewer `3d9cddb9-7314-4424-a0a5-91a2093e211a`)
**Base / Target:** `3ca330ff..HEAD` (post-merge commits 539236f2 and 6aa0d66a) evaluated in interaction with `origin/main..HEAD`
**Target Issue:** #391 (SETUP-BACKTEST-CHART: backtest curve on Chart for Pre-Breakout and Fib Pullback)

---

## 1. Scope & Commits Audited

### Commits in Focus (`3ca330ff..HEAD`):
- `539236f2` — `test(chart): update chartActions and useOriginalBacktest for setup backtests (#391)`
- `6aa0d66a` — `test(prebreakout): update evidence tests for backtest artifact status (#391)`

### Modified Files Inspected:
1. `backend/tests/test_stock_pres_p1_prebreakout_evidence.py`
2. `frontend/app/(frame)/screener/step-4-prebreakout/__tests__/chartActions.test.tsx`
3. `frontend/lib/__tests__/useOriginalBacktest.test.tsx`

### Core Implementation Files & Cross-System Interactions Inspected:
- `backend/app/services/strategy_backtest.py`
- `backend/app/services/strategy_backtest_details.py`
- `backend/app/routers/stock_scan.py`
- `frontend/lib/candidateChart.ts`
- `frontend/lib/useOriginalBacktest.ts`
- `frontend/components/organisms/CandidateChartWorkspace/index.tsx`
- `docs/superpowers/plans/2026-10-22-setup-backtest-chart-plan.md`
- `docs/superpowers/audits/SETUP-BACKTEST-CHART/code-r1.md`
- `docs/superpowers/PROJECT_STATE.json`

---

## 2. Check Item Verifications

### 1. In Commit 539236f2:
- **`frontend/app/(frame)/screener/step-4-prebreakout/__tests__/chartActions.test.tsx` (line 76):**
  - Updated expectation: `expect(open).toHaveBeenCalledWith(`/chart?symbol=CLICK&source=${mode}&backtest_artifact_status=original_unavailable`, '_blank');` across all three setup modes (`prebreakout`, `fib`, `pullback`).
  - *Mechanism Check:* In `candidateChart.ts`, `buildCandidateChartHref` was previously hardcoding `backtest_artifact_status=unsupported` for `prebreakout` and `fib`. With the removal of the setup restriction in Round 1, `buildCandidateChartHref` falls back to `row.backtest_artifact_status ?? 'original_unavailable'` for all sources. Because the test's mock candidates omit `backtest_artifact_status`, the query parameter correctly resolves to `original_unavailable` for all setup modes. The test assertion accurately validates this runtime behavior.
- **`frontend/lib/__tests__/useOriginalBacktest.test.tsx` (lines 19–25):**
  - Updated test: `test.each(['prebreakout','fib'] as const)('supported %s fetches original artifact', ...)` verifies that `prebreakout` and `fib` candidate contexts trigger `api.getOriginalBacktest(id, 'AAA', ...)` and transition status to `'ready'`.
  - *Mechanism Check:* Previously, `useOriginalBacktest.ts` rejected `prebreakout` and `fib` with an immediate `{status: 'unavailable', reason: 'unsupported'}`. With that guard removed, `useOriginalBacktest` actively queries the backend for the original artifact when provided an artifact ID. The updated test verifies the live query lifecycle.

### 2. In Commit 6aa0d66a:
- **`backend/tests/test_stock_pres_p1_prebreakout_evidence.py` (lines 208–212, 237–242):**
  - In `test_prebreakout_endpoint_carries_breakdown_and_swing`: updated `assert set(row) == {"symbol", "confidence", "direction", "metrics", "confidence_breakdown", "fib_swing", "backtest_artifact_status"}`.
  - In `test_fib_pullback_endpoint_carries_swing`: updated expected candidate dictionary to include `"backtest_artifact_status": "original_unavailable"`.
  - *Mechanism Check:* In `backend/app/routers/stock_scan.py`, both `_prebreakout_scan_core` and `_fib_pullback_scan_core` unpack `**_artifact` into the emitted candidate dictionary. Because the fixture bars in `test_fib_pullback_endpoint_carries_swing` omit timestamps (`"time"` key), `_run_backtest_with_details` safely handles the missing time dimension and `_original_artifact` yields `{"backtest_artifact_status": "original_unavailable"}`. The test correctly validates this contract.

---

## 3. Invariance & Gate Verifications

1. **Numerical & Runtime Invariance:**
   - The commits in `3ca330ff..HEAD` contain test-only modifications.
   - In `backend/app/routers/stock_scan.py`, candidate metrics (`confidence`, `metrics`, `fib_swing`, `fib_dist_pct`, `at_level`) are calculated prior to backtest execution.
   - Candidate sorting (by `confidence` descending for prebreakout; by `not at_level` then `fib_dist_pct` ascending for fib-pullback) remains completely independent of backtest execution or artifact availability.
   - In `backend/tests/test_setup_backtest_chart.py`, pinned tests assert exact equality across all summary metrics (`n_trades`, `win_rate`, `total_return_pct`, `max_drawdown_pct`, `expectancy`, `sharpe`, `confidence`, `passes_gate`, `summary_text`, `n_time_exits`) with and without `detail_collector`.
   - Backtest reconciliation (`ending_return == summary.total_return_pct`) is pinned within `1e-7`.

2. **Backward Compatibility:**
   - Scan responses from `/api/scan/prebreakout` and `/api/scan/fib-pullback` preserve all existing fields and types. The added fields (`backtest_artifact_status` and optional `backtest_artifact_id`) are purely additive and optional.
   - `PreBreakoutResultRow` and `FibPullbackResultRow` in `frontend/types/stockDomain.ts` extend `BacktestArtifactReference` with optional fields, maintaining full backward compatibility with existing consumers.

3. **Store Persistence, Broker Orders, & Chart Integrity:**
   - Neither `prebreakout` nor `fib` setups route to broker order placement or automated execution.
   - Adding optional fields to scan result rows in Zustand stores does not alter store schema versioning or cause hydration errors.
   - Artifact retrieval via `GET /api/backtest-artifacts/{id}?symbol={sym}` and `useOriginalBacktest` strictly enforces validation: `schema_version === 1`, `provenance === 'original'`, and `identity.symbol === symbol`. In the event of mismatch, missing artifacts, or errors, the UI displays clear, plain-language explanations (`formatUnavailableReason`) while falling back to the live chart without substituting false or corrupted historical data.

4. **Test Suite Verification:**
   - `backend/tests/test_stock_pres_p1_prebreakout_evidence.py`: 14 passed.
   - `backend/tests/test_setup_backtest_chart.py`: 6 passed.
   - `backend/tests/test_prebreakout_params.py` & `test_strategy_engine_fib.py`: 12 passed.
   - Jest (`chartActions.test.tsx`, `useOriginalBacktest.test.tsx`): 34 passed.
   - Jest (`candidateChart.test.ts`, `setupCandidateBacktest.test.ts`, `auditPrebreakoutLaneE.test.ts`, `CandidateChartWorkspace.test.tsx`): 34 passed.
   - TypeScript `tsc --noEmit`: Clean (0 errors).
   - `python scripts/state.py`: Clean ("No drift: every declared status matches the code").

---

## 4. Findings

No findings meet the gate floor (no incorrect numbers displayed or sent to brokers; no data corruption; no mechanism misstatements in comments or tests).

**GATE FINDINGS: 0**
