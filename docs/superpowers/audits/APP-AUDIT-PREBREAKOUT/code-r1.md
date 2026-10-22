# Adversarial Code/Report Audit Report (Round 1): APP-AUDIT-PREBREAKOUT

**Target:** Diff between `origin/main` and `HEAD` (`214b03aa`)  
**Phase ID:** `APP-AUDIT-PREBREAKOUT` (#353)  
**Branch:** `board/app-audit-prebreakout-b4f0d823`  
**Worktree:** `.worktrees/app-audit-prebreakout`  
**Reviewer:** Independent Adversarial Auditor (Subagent `883e1a89-a631-41e8-9ea0-c15d61c6a6c7`)  
**Skill Applied:** `bmad-review-adversarial-general`  
**Target Destination:** `docs/superpowers/audits/APP-AUDIT-PREBREAKOUT/code-r1.md`  
**Reviewed Artifacts:**
- Reconciliation Report: `docs/superpowers/audits/app-audit/APP-AUDIT-PREBREAKOUT/report.md`
- Defects Register: `docs/superpowers/audits/app-audit/APP-AUDIT-PREBREAKOUT/defects.json`
- Execution Provenance: `docs/superpowers/audits/app-audit/APP-AUDIT-PREBREAKOUT/provenance.json`
- Execution Plan: `docs/superpowers/plans/2026-10-21-app-audit-prebreakout-plan.md`
- Plan Audits: `docs/superpowers/audits/APP-AUDIT-PREBREAKOUT/plan-r1.md` & `plan-r2.md`
- Backend Verification Suite: `backend/tests/test_audit_prebreakout_lane_e.py`
- Frontend Verification Suite: `frontend/app/(frame)/screener/step-4-prebreakout/__tests__/auditPrebreakoutLaneE.test.ts`
- Live Source Code:
  - `frontend/app/(frame)/screener/step-4-prebreakout/page.tsx`
  - `frontend/app/(frame)/screener/step-4-prebreakout/scanThresholds.ts`
  - `frontend/app/(frame)/screener/step-4-prebreakout/scanChartLines.ts`
  - `frontend/app/(frame)/screener/step-4-prebreakout/SelectedStockContext.tsx`
  - `frontend/components/organisms/PreBreakoutParamsPanel/index.tsx`
  - `frontend/components/organisms/FibPullbackParamsPanel/index.tsx`
  - `frontend/lib/candidateChart.ts`
  - `frontend/lib/useOriginalBacktest.ts`
  - `backend/app/routers/stock_scan.py`
  - `backend/app/services/strategy_engine.py`
  - `backend/app/services/strategy_backtest.py`
  - `backend/app/routers/backtest_artifacts.py`

**Gate Standard:** Project Numeric & Persistence Gate (A finding blocks ONLY if it can put a WRONG NUMBER in front of a user or on a broker order, or CORRUPT PERSISTED DATA; a comment blocks only if a competent reader acting on it would write a wrong change by misstating mechanism).

**Status:** **1 Gate Finding (NOT CLEAN)**

---

## Executive Summary

Round 1 independent adversarial code and report audit was executed against the exact diff between `origin/main` (`b9a4e087`) and `HEAD` (`214b03aa`) in `.worktrees/app-audit-prebreakout`.

The reconciliation report, defects register, and verification test suites thoroughly map and pin the Step 4 Pre-Breakout subsystem across Pre-Breakout (`scanMode === 'prebreakout'`), Fibonacci Pullback (`scanMode === 'fib'`), and Pullback (`scanMode === 'pullback'`) sub-modes. State snapshot isolation (`WeakMap` snapshots), integer parameter truncation parity (`truncPreBreakoutInts`, `truncFibInts`), monotonic network request token invalidation (`requestToken.current += 1`), setup price line boundaries (`scanChartLines`), and Candidate Chart handoff contracts (`candidateChart.ts`, `useOriginalBacktest.ts`) were all verified against live backend and frontend implementations.

However, an algorithmic mechanism misstatement was discovered in `report.md` Section 3.1 and mirrored in `backend/tests/test_audit_prebreakout_lane_e.py:84`: the audit report defines Pre-Breakout component scores ($S_{ATR}, S_{Vol}, S_{Prox}$) and the final composite `Confidence` score as using `round(...)`, and the backend test asserts `sig.confidence == round(expected_score)`. In reality, `backend/app/services/strategy_engine.py:1604-1650` maintains component scores as unrounded floats and truncates the final confidence score using Python integer truncation (`confidence = int(unrounded)`), which truncates towards zero. Under the Project Numeric & Persistence Gate (comment-truth exception), a developer acting on `report.md` would refactor `strategy_engine.py` to `round(unrounded)`, altering user-facing scores on the candidate table for any setup with fractional confidence $\ge 0.5$ (e.g. 74.8 -> 75 vs 74).

---

## Gate Findings

### Finding F-1: Pre-Breakout Confidence Synthesis and Component Scores Misstated as `round(...)` Instead of Float / Integer Truncation (`int(...)`)

- **location**: `docs/superpowers/audits/app-audit/APP-AUDIT-PREBREAKOUT/report.md:53, 67, 73, 80, 83` and `backend/tests/test_audit_prebreakout_lane_e.py:84`
- **trigger_condition**: `report.md` Section 3.1 defines component scores $S_{ATR}, S_{Vol}, S_{Prox}$ as rounded integers via `round(...)` and defines total confidence as `Confidence = round(0.30 * S_ATR + 0.25 * S_Vol + 0.45 * S_Prox)` (and `round(...)` for Fib-enabled). Furthermore, `backend/tests/test_audit_prebreakout_lane_e.py:84` tests this with `assert sig.confidence == round(expected_score)`.
  In reality, `backend/app/services/strategy_engine.py:1604-1650` defines:
  ```python
  atr_score  = max(0, 100 * (1 - atr_ratio / atr_compression_ratio))
  vol_score  = max(0, 100 * (1 - vol_ratio / vol_compression_ratio))
  prox_score = max(0, 100 * (1 - prox / resistance_proximity_pct)) if resistance_proximity_pct > 0 else 50
  ...
  unrounded = atr_score * 0.30 + vol_score * 0.25 + prox_score * 0.45
  confidence = int(unrounded)
  ```
  Intermediate component scores are raw unrounded floats, and total confidence is truncated via `int(unrounded)` (Python float truncation toward zero), NOT `round(unrounded)`. The backend test only passed because the synthetic bar values in `_build_contracting_bars(60)` produced `unrounded = 74.350143...`, where `int(74.35) == round(74.35) == 74`.
- **guard_snippet**:
  1. In `docs/superpowers/audits/app-audit/APP-AUDIT-PREBREAKOUT/report.md`:
     Update Section 3.1 lines 53, 67, 73 to remove `round(...)`:
     $$S_{ATR} = \min\left(100, \, \max\left(0, \, 100 \times \left(1 - \frac{R_{ATR}}{\text{atr\_compression\_ratio}}\right)\right)\right)$$
     $$S_{Vol} = \min\left(100, \, \max\left(0, \, 100 \times \left(1 - \frac{R_{Vol}}{\text{vol\_compression\_ratio}}\right)\right)\right)$$
     $$S_{Prox} = \min\left(100, \, \max\left(0, \, 100 \times \left(1 - \frac{D}{\text{resistance\_proximity\_pct}}\right)\right)\right)$$
     Update Section 3.1 lines 80 and 83 to specify integer truncation:
     $$\text{Confidence} = \text{int}\left(0.30 \times S_{ATR} + 0.25 \times S_{Vol} + 0.45 \times S_{Prox}\right)$$
     $$\text{Confidence} = \text{int}\left(0.24 \times S_{ATR} + 0.20 \times S_{Vol} + 0.36 \times S_{Prox} + 0.20 \times S_{Fib}\right)$$
     Add an explicit note highlighting that `breakout_setup_signal` truncates via `int(unrounded)` (truncation toward zero), distinguishing it from Fibonacci pullback (`stock_scan.py:2293, 2295`) which uses `round(...)`.
  2. In `backend/tests/test_audit_prebreakout_lane_e.py:84`:
     Change:
     ```python
     assert sig.confidence == int(expected_score)
     ```
     (or `assert sig.confidence == int(sig.confidence_breakdown["unrounded"])`).
- **potential_consequence**: A competent developer or tester acting on the report's formula would modify `strategy_engine.py:1644, 1650` from `int(unrounded)` to `round(unrounded)`, altering user-facing scores on the Pre-Breakout table for any setup with fractional confidence $\ge 0.5$ (e.g. 74.8 -> 75 vs 74). Alternatively, authoring unit tests assuming `round()` will result in test failures whenever test fixture scores have fractional values $\ge 0.5$.

---

## Surface-by-Surface Verification

### 1. Pre-Breakout Sub-Mode (`scanMode === 'prebreakout'`)
- **UI & Controls:** `frontend/components/organisms/PreBreakoutParamsPanel/index.tsx:6-24` defines `PREBREAKOUT_DEFAULTS`: `atrCompressionRatio: 0.85`, `atrAvgLookback: 20`, `rangeAtrMult: 3.0`, `rangeLookbackBars: 10`, `volCompressionRatio: 0.9`, `resistanceProximityPct: 0.08`, `swingLookback: 50`. Aligns with backend YAML `backend/config/strategy_params.yaml:603-618`.
- **Endpoint Route:** `POST /api/scan/prebreakout` (`PreBreakoutScanRequest`) handled by `_prebreakout_scan_core` in `backend/app/routers/stock_scan.py:2319-2420`.
- **Formula Checks:**
  - True Range rolling SMA: `_atr_series(bars, period=14)` computes rolling 14-period Simple Moving Average of True Range starting at bar index 1 (`len(atrs) == len(bars) - 1`), not Wilder exponential smoothing. Verified.
  - ATR Compression Ratio: $R_{ATR} = ATR_{\text{current}} / \text{avg\_atr} \le \text{atr\_compression\_ratio}$. Verified.
  - Range Consolidation Gate: $\text{Range}_K \le \text{range\_atr\_mult} \times ATR_{\text{current}}$. Acts strictly as a qualification gate (`return None`), not a confidence component. Verified.
  - Volume Contraction: $R_{Vol} = V_{\text{current}} / \text{avg\_vol} \le \text{vol\_compression\_ratio}$. Verified.
  - Resistance Proximity: Distance $D \le \text{resistance\_proximity\_pct}$. Verified.
  - Trend Filter: Close relative to 20 EMA. Verified.
  - Confidence Weights: Base 30% ATR, 25% Vol, 45% Proximity; Fib-enabled 24% ATR, 20% Vol, 36% Proximity, 20% Fib. Verified.

### 2. Fibonacci Sub-Mode (`scanMode === 'fib'`)
- **UI & Controls:** `frontend/components/organisms/FibPullbackParamsPanel/index.tsx:6-20` defines `FIB_PULLBACK_DEFAULTS`: `fibSwingLookback: 100`, `fibLevels: [38.2, 61.8]`, `fibTolerancePct: 0.015`, `emaFilterPeriod: 20`.
- **Endpoint Route:** `POST /api/scan/fib-pullback` (`FibPullbackScanRequest`) handled by `_fib_pullback_scan_core` in `backend/app/routers/stock_scan.py:2160-2317`.
- **Formula Checks:**
  - Swing Identification: $H_{\text{swing}} = \max(H)$, $L_{\text{swing}} = \min(L)$ over `fib_swing_lookback` (backend min 10). Impulse range $R = H_{\text{swing}} - L_{\text{swing}}$. Verified.
  - Standard Levels: $P_{lvl} = H_{\text{swing}} - R \times (lvl / 100)$ (Bullish) or $L_{\text{swing}} + R \times (lvl / 100)$ (Bearish) across `{23.6, 38.2, 50.0, 61.8, 78.6}`. Verified.
  - EMA Trend Gate: Bullish close $> EMA$; Bearish close $< EMA$. Verified.
  - Piecewise Confidence:
    - `dist_pct is None` $\to 0$.
    - Within tolerance ($dist \le tol$): $\max(60, \text{round}(100 - (dist / tol) \times 40))$.
    - Outside tolerance ($dist > tol$): $\max(0, \text{round}(60 - ((dist - tol) / tol) \times 30))$.
    - Verified in `stock_scan.py:2288-2295`.
  - Sorting: Sorted by `not at_level` (at-level hits sort first) then `fib_dist_pct` ascending. Verified.

### 3. Pullback Sub-Mode (`scanMode === 'pullback'`)
- **API Request:** `POST /api/stock-scan` with `category: 'pullback'`, `strategy: 'pullback_ema'`.
- **Sizing Integration:** `scanSizingFromRisk()` in `frontend/app/(frame)/screener/step-4-prebreakout/page.tsx:158` validates account size and risk percentage.
- **Backtest Execution:** `run_strategy_backtest` (`backend/app/services/strategy_backtest.py:831`).
- **Artifact Generation:** Generates frozen `BacktestArtifact` with unique UUID `artifact_id` and status `'available'`. Verified.

### 4. Snapshot, State Isolation & Parameter Truncation
- **Integer Truncation:** `truncPreBreakoutInts` and `truncFibInts` in `scanThresholds.ts:8-25` truncate integer fields via `Math.trunc`, matching backend `int()` coercion in `stock_scan.py:2201, 2361`. Verified.
- **Snapshot Isolation:** `rememberScan` and `scanSnapshot` use an in-memory `WeakMap<object, ScanSnapshot>` keyed by the result array. Adjusting sliders post-scan does not alter displayed thresholds for rendered candidates. Verified.
- **Request Invalidation:** `requestToken.current += 1` increments on every scan dispatch, discarding out-of-order responses. Verified.
- **Supplementary Analysis Isolation:** `SelectedStockContext` triggers `api.analyzeStock` in separate state, strictly verified for ticker and direction identity. Verified.

### 5. Candidate Chart Handoff Contracts
- **URL Construction:** `frontend/lib/candidateChart.ts`:
  - `prebreakout` and `fib`: sets `backtest_artifact_status = 'unsupported'` and omits `backtest_artifact_id`. Verified.
  - `pullback`: passes `backtest_artifact_id` and `backtest_artifact_status`. Verified.
- **Workspace Resolution:** `frontend/lib/useOriginalBacktest.ts` & `CandidateChartWorkspace`:
  - Pre-Breakout and Fib return `{ status: 'unavailable', reason: 'unsupported' }`, showing live candlestick chart without substituting synthetic backtest curves. Verified.
  - Pullback fetches `GET /api/backtest-artifacts/{artifact_id}?symbol={symbol}` with schema version (1), symbol match, and provenance check (`'original'`). Verified.

### 6. Setup Chart Overlays
- **Module:** `frontend/app/(frame)/screener/step-4-prebreakout/scanChartLines.ts:1-41`.
- **Behavior:**
  - `pullback` returns `[]`.
  - `prebreakout` plots `Scan swing high`/`low` and Fib swing extremes.
  - `fib` plots swing high, swing low, and hit level `Scan Fib {lvl}%`.
  - Strictly plots returned setup evidence; contains NO entry, stop, target lines, or ATR bands. Verified.

### 7. Verification Test Suite Execution
- **Backend Tests:**
  - `backend/tests/test_audit_prebreakout_lane_e.py`: 5 passed.
  - `backend/tests/test_prebreakout_params.py`: 3 passed.
  - `backend/tests/test_prebreakout_universe.py`: 10 passed.
  - `backend/tests/test_fib_pullback_endpoint.py`: 14 passed.
  - `backend/tests/test_fibonacci_signal.py`: 7 passed.
  - `backend/tests/test_strategy_engine_fib.py`: 9 passed.
  - `backend/tests/test_stock_pres_p1_prebreakout_evidence.py`: 15 passed.
  Total backend suite: 63 tests passing.
- **Frontend Tests:**
  - `frontend/app/(frame)/screener/step-4-prebreakout/__tests__/auditPrebreakoutLaneE.test.ts`: 7 passed.
  - `npm run typecheck` (`tsc --noEmit`): clean (0 errors).
- **State Integrity:**
  - `python scripts/state.py`: clean (0 drift).

---

## Verdict & Recommendation

Phase `APP-AUDIT-PREBREAKOUT` Round 1 code/report review identified **1 Gate Finding** (Finding F-1).
Under the Project Numeric & Persistence Gate standard, `report.md` and `test_audit_prebreakout_lane_e.py:84` must be corrected to reflect raw float component scores and integer truncation (`int(...)`) in Pre-Breakout confidence synthesis.

Once Finding F-1 is remediated, the target will be ready for Code Audit Round 2.
