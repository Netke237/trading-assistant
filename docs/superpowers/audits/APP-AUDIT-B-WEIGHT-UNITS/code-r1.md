# Adversarial Code Audit Report: APP-AUDIT-B-WEIGHT-UNITS

**Target:** Diff between `origin/main` (03d94520) and `HEAD` (d2c4c0f1)  
**Plan:** `docs/superpowers/plans/2026-10-21-app-audit-b-weight-units-plan.md`  
**Reviewer:** Independent adversarial auditor (subagent `d31a6e35-c050-43be-8685-1d5a1d3897ed`)  
**Gate:** Numeric / Persistence Gate (wrong number in front of user/broker order, or data corruption)  

---

## 1. Audit Scope & Trace Paths Checked

The complete diff (`origin/main..HEAD`) spanning 14 files was inspected against the gate criteria:

1. **Backend Scorer Weight Normalization (`backend/app/scoring/stock_scorer.py`):**
   - Traced `_normalize_weight(val)` logic:
     - Null safety: `val is None -> 0.0`.
     - Percentage scaling: `f > 1.0 -> f / 100.0`.
     - Decimal fraction preservation: `0.0 <= f <= 1.0` returns `f` unchanged.
     - Negative clamping: `f < 0.0` returns `0.0`.
   - Verified integration in `score_stock` override parsing (lines 1146–1150) across all 5 score weight keys (`weight_trend`, `weight_pullback`, `weight_trigger`, `weight_event`, `weight_vol`).
   - Verified composite score weighting in both Options mode (independent addition) and Stocks mode (event-zeroing + sum renormalization by remaining weights).

2. **Backend Persistence & Migration (`backend/app/services/scan_schedule_store.py`):**
   - Verified schema version bump `_SCHEMA_VERSION = 3`.
   - Verified `_migrate_entry`:
     - Preserves v1 -> v2 migration for `mode == "stocks"`.
     - Applies v2 -> v3 weight normalization for both `stocks` and `options` entries:
       - Identifies target keys via `_SCORE_WEIGHT_KEYS`.
       - For `isinstance(v, (int, float)) and v > 0`: normalizes `v >= 1.0` to `float(v) / 100.0` (e.g. `1 -> 0.01`, `40 -> 0.40`, `100 -> 1.0`).
       - Preserves zero (`0 -> 0`) and existing fractions (`< 1.0`).
   - Verified persistence safeguards: `_backup()` creates a timestamped copy before rewriting, and `_save_locked()` writes atomically via temporary file and rename under `_lock`.

3. **Frontend Wire Normalization (`frontend/lib/`):**
   - Verified `resolveStockScanRequest.ts` and `resolveOptionsScanRequest.ts`:
     - `SCORE_WEIGHT_KEYS` Set strictly covers all 5 score weight parameters.
     - `normalizeWeightOverride(val)` safely handles non-numbers and scales `val / 100.0`.
     - In `buildStockScanRequestBody`: applies normalization solely to `SCORE_WEIGHT_KEYS`, leaving other scorer parameters (`fast_ema`, `slow_ema`, `rs_period`, etc.) untouched.
     - In `buildOptionsScanRequestBody`: applies normalization to `SCORE_WEIGHT_KEYS`, leaving options parameters (`iv_abs_pass_max`, `shortlist_max_candidates`) untouched.
     - Confirmed that `frontend/lib/scanScheduleResolve.ts` delegates to `buildOptionsScanRequestBody` and `buildStockScanRequestBody` without double-normalization.
     - Confirmed that `frontend/lib/analysisStore.ts` routes through `buildStockScanRequestBody` and inherits normalized weights.

4. **Test Coverage & Regressions:**
   - Ran `backend/tests/test_weight_units.py`: all 9 unit tests passed (verifying 40% overrides, stocks mode renormalization, direct caller inputs, and v2->v3 schedule migration with backup).
   - Ran `backend/tests/test_overrides.py` and `backend/tests/test_stock_scan_overrides.py`: all 49 existing override tests passed.
   - Ran `backend/tests/test_scan_schedule_recovery.py`: all 8 recovery and backup tests passed.
   - Ran targeted Jest tests (`resolveWeightOverrides.test.ts`, `stockScanRequestPins.test.ts`, `a5AnalysisMirrorsScan.test.tsx`, `p3aMinStockScore.test.ts`): all 33 tests across 4 suites passed.
   - Ran `npm run typecheck`: clean (0 errors).
   - Ran `python scripts/state.py`: verified presence probe `_normalize_weight` and reported "No drift: every declared status matches the code."

---

## 2. Adversarial Scenarios Examined

- **Double-Normalization Trap:** Verified whether a weight override could be scaled twice (e.g. `40% -> 0.40 -> 0.004`). In frontend, `buildStockScanRequestBody` converts `40` to `0.40`. When sent to backend, `_normalize_weight(0.40)` checks `0.40 > 1.0` (False) and returns `0.40` unchanged. Idempotency holds.
- **Discontinuity at Boundary Values (0%, 1%, 100%):**
  - `0%`: Frontend sends `0`, backend evaluates `0.0`.
  - `1%`: Frontend converts `1` to `0.01` (1%), backend preserves `0.01`.
  - `100%`: Frontend converts `100` to `1.0` (100%), backend preserves `1.0`.
- **Search Profile Preservation:** Verified that Search Profiles in `localStorage` store raw UI percentage integers (`40`) so Step 3 UI continues to display `40%` without shrinking on reload. Normalization only occurs at the wire/request builder layer.
- **Legacy Schedule Compatibility:** Verified that legacy version 1 and 2 schedules with `weight_trend: 1` or `weight_trend: 40` migrate to `0.01` and `0.40` respectively upon server startup, avoiding 100x score inflation in unattended cron runs.
- **Direct Python Callers:** Verified that internal and test callers passing fractions (`0.123`, `0.5`, `1` / `1.0` as in `test_overrides.py:77`) remain compatible without breakage.

---

## 3. Findings

No gate-level findings identified. The implementation strictly matches the approved plan and solves defect C4 without numerical errors or data corruption.

---

GATE FINDINGS: 0
