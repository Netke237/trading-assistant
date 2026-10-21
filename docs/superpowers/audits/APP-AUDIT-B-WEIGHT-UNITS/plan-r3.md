# Adversarial Audit (Round 3): APP-AUDIT-B-WEIGHT-UNITS Plan

**Target:** `docs/superpowers/plans/2026-10-21-app-audit-b-weight-units-plan.md`  
**Review Type:** Independent adversarial review of Round 2 fixes (F2-1, F2-2, F2-3) and their interactions  
**Auditor:** Independent subagent `ae3ebafc-3ea4-4a06-a080-e10dd5ed2478`  
**Gate:** Numeric / Persistence Gate (0 gate findings required for clean exit)

---

## 1. Audit Scope & Verification Method

The Round 2 findings and their proposed fixes were cross-examined against the codebase:
1. **Fix for F2-1 (Frontend Request Resolver Normalization):**
   - Verified `frontend/lib/resolveStockScanRequest.ts` and `frontend/lib/resolveOptionsScanRequest.ts`.
   - Verified `frontend/app/(frame)/screener/step-3-direction/page.tsx` parameter definitions (`PARAM_DEFS:55-64`) and `PARAM_DEFAULTS_PER_HORIZON` in `frontend/lib/executionParamDefaults.ts`. Confirmed score weights do not use `scale: 100`, so values stored in `scanStore.scanOverrides` and Search Profiles are whole percentage integers `[0, 100]`.
   - Verified `normalizeWeightOverride(val) = Math.max(0, val / 100.0)` for all 5 score weight keys:
     - `0` (0%) -> `0.0`
     - `1` (1%) -> `0.01`
     - `40` (40%) -> `0.40`
     - `100` (100%) -> `1.0`
   - Verified that non-weight overrides (e.g. `fast_ema: 20`, `iv_abs_pass_max: 44`) are shielded by `SCORE_WEIGHT_KEYS` and remain untouched.
   - Verified that test fixtures `stockScanRequestPins.test.ts:30` and `a5AnalysisMirrorsScan.test.tsx:46` mock `STEP3.weight_trend: 50` so that `50 / 100.0 = 0.5`, cleanly satisfying existing assertions `toEqual({ weight_trend: 0.5 })` without regression.
   - Verified `p3aMinStockScore.test.ts:48` expectation update from `30` to `0.3`.
   - Verified `frontend/lib/scanScheduleResolve.ts` and `frontend/lib/analysisStore.ts` funnel through `buildStockScanRequestBody` / `buildOptionsScanRequestBody` without redundant scaling.

2. **Fix for F2-2 (Legacy Schedule Migration in `scan_schedule_store.py`):**
   - Verified `backend/app/services/scan_schedule_store.py`: `_SCHEMA_VERSION = 3`.
   - Verified `_migrate_entry`:
     - v1 -> v2: preserves `migrate_saved_stock_request(req)` for `mode == "stocks"`.
     - v2 -> v3: for both `stocks` and `options` entries, checks `req["overrides"]` for `SCORE_WEIGHT_KEYS`.
     - Any override where `isinstance(v, (int, float)) and v > 0`: if `v >= 1.0`, scales via `float(v) / 100.0`.
       - Legacy `weight_trend: 1` (1%) -> `0.01`
       - Legacy `weight_trend: 40` (40%) -> `0.40`
       - Legacy `weight_trend: 100` (100%) -> `1.0`
       - Legacy `weight_trend: 0` (0%) -> preserved as `0`
     - Preserves backup copy (`_backup()`) and atomic rewrite under lock in `_load()`.
     - Confirmed that once rewritten under version 3, subsequent loads evaluate `version_int < _SCHEMA_VERSION` as `False`, so entries are never re-migrated.
     - Confirmed existing tests in `backend/tests/test_scan_schedule_recovery.py` import `_SCHEMA_VERSION` directly and remain green.

3. **Fix for F2-3 (Disentanglement of Backend and Frontend Tests):**
   - Verified Section 4 test specifications:
     - Frontend resolver tests in `resolveWeightOverrides.test.ts` test UI percentage mapping `0 -> 0.0`, `1 -> 0.01`, `40 -> 0.40`, `100 -> 1.0`.
     - Backend direct-caller tests in `test_weight_units.py` test:
       - Direct percentages `> 1.0`: `40 -> 0.40`, `100 -> 1.0` (matching `backend-parameters.py` line 35).
       - Direct fractions `<= 1.0`: `0.01 -> 0.01` (1%), `0.40 -> 0.40`, `1.0 -> 1.0` (100%, matching `test_overrides.py:77`), and `0.123 -> 0.123` (matching `test_overrides.py:37`).
     - Elimination of the previous contradiction between testing `1%` mapping to `0.01` and asserting that `1` passes directly as `1.0` without modification.

4. **Scorer Arithmetic & Invariant Checks:**
   - **Audit fixture:** `score({'weight_trend': 40}) == 67` under `backend-parameters.py` passes cleanly (32 + 12 + 10 + 3 + 10 = 67).
   - **Stocks mode renormalization:** With 40% Trend weight override, remaining non-event weights sum to `0.95`, yielding weighted score `64 / 0.95 = 67.368` (rounded to `67`).
   - **Options mode controls:** Explicit contributions verified for Pullback 40% (71), Trigger 40% (65), Event 40% (64), Vol 40% (89).

---

## 2. Findings

None. All Round 2 findings have been thoroughly and correctly addressed. No new failure modes, numerical errors, or data corruption paths were identified.

---

GATE FINDINGS: 0
