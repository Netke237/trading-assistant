# Implementation Plan: APP-AUDIT-B-WEIGHT-UNITS (Score-weight percent overrides unit normalization)

## 1. Overview & Context

- **Issue:** #382 (`APP-AUDIT-B-WEIGHT-UNITS`, size:L, complexity:4)
- **Defect:** Defect C4 from audit #350 (`docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/controls/findings.md`)
- **Root Cause:**
  Step 3 labels score weight inputs `%` with bounds 0–100 (`weight_trend`, `weight_pullback`, `weight_trigger`, `weight_event`, `weight_vol`). When a user sets a weight override (e.g., `weight_trend: 40` for 40%), the request sends `overrides.weight_trend: 40`.
  In `backend/app/scoring/stock_scorer.py:1131-1135`, the scorer assigns `w["trend"] = float(val)` directly to the horizon weights config. The YAML weights config uses decimal fractions (`trend: 0.30`, `pullback: 0.20`, `trigger: 0.25`, `event: 0.15`, `vol: 0.10`).
  Consequently, `w["trend"]` becomes `40.0` instead of `0.40`. A component score of 80 contributes `80 * 40.0 = 3200` points to the weighted composite score, inflating the total score to 3235 instead of 67. In Stocks mode, event weight is zeroed and remaining weights are renormalized by `sum(weights)`, causing Trend to command 98.6% of the composite score.
- **Goal:**
  Normalize score-weight overrides across requests, legacy schedules, and direct scorer invocations so that percentage values (0–100) are converted to canonical decimal fractions (0.0–1.0), while preserving existing decimal fractions (<= 1.0) passed by unit tests and internal callers.

---

## 2. Gate Compliance & Invariants

- **Numeric Gate:** Prevent wrong scores (e.g. 3235 instead of 67) from reaching scan results, candidate rankings, and position cards.
- **Persistence Gate:** Saved Search Profiles in `localStorage` and Scan Schedules in `scan_schedule.yaml` must not be corrupted. Legacy entries with whole percentages (e.g., 40) or fractions (0.40) must load and evaluate cleanly.
- **Options Mode Invariant:** Only the overridden weight is changed; untouched weights retain their horizon defaults without recalibration.
- **Stocks Mode Invariant:** Overridden weights are normalized before event-zeroing and sum renormalization (`weights = {k: v / total_w for k, v in weights.items()}`).
- **Scorer Test Parity:** Existing unit tests in `backend/tests/test_overrides.py` passing fractions (`0.9`, `0.123`, `0.5`, `1`) continue to pass without regression.
- **Audit Verification:** The audit fixture in `docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/controls/backend-parameters.py` checks `score({'weight_trend': 40}) == 67` and must PASS.

---

## 3. Implementation Design

### A. Backend Scorer Normalization (`backend/app/scoring/stock_scorer.py`)
In `stock_scorer.py`:
1. Define a helper:
   ```python
   def _normalize_weight(val: float | int | None) -> float:
       if val is None:
           return 0.0
       f = float(val)
       if f > 1.0:
           return f / 100.0
       return max(0.0, f)
   ```
2. In `score_stock` override handling (lines 1130–1136):
   Apply `_normalize_weight(val)` when assigning:
   ```python
   if   key == "weight_trend":            w["trend"]      = _normalize_weight(val)
   elif key == "weight_pullback":          w["pullback"]   = _normalize_weight(val)
   elif key == "weight_trigger":           w["trigger"]    = _normalize_weight(val)
   elif key == "weight_event":             w["event"]      = _normalize_weight(val)
   elif key == "weight_vol":               w["vol"]        = _normalize_weight(val)
   ```

### B. Frontend Request Resolvers (`frontend/lib/`)
To ensure canonical unit propagation and eliminate ambiguity between 1% (0.01) and 100% (1.0):
1. In `frontend/lib/resolveStockScanRequest.ts`, `frontend/lib/resolveOptionsScanRequest.ts`, and `frontend/lib/scanScheduleResolve.ts`:
   Normalize weight override values before attaching to `overrides`:
   ```ts
   const SCORE_WEIGHT_KEYS = new Set([
     'weight_trend',
     'weight_pullback',
     'weight_trigger',
     'weight_event',
     'weight_vol',
   ]);

   export function normalizeWeightOverride(val: unknown): unknown {
     if (typeof val !== 'number' || !Number.isFinite(val)) return val;
     if (val > 1) return val / 100;
     if (val === 1) return 0.01;
     return Math.max(0, val);
   }
   ```
   Apply `normalizeWeightOverride` to any of the 5 score weight keys present in `scanOverrides`.

### C. Schedule Migration & Legacy Compatibility (`backend/app/services/scan_schedule_store.py`)
In `scan_schedule_store.py`:
Ensure `_migrate_entry` normalizes any score-weight keys in `entry["resolved_request"]["overrides"]` if `val > 1.0`.

---

## 4. Verification & Testing Plan

1. **Audit Fixture Test:**
   Run `python docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/controls/backend-parameters.py`.
   Assert `"40 percent trend weight unit"` passes.
2. **Backend Unit Tests:**
   Create `backend/tests/test_weight_units.py`:
   - Test all 5 score weight controls with 40% override in Options mode against fixed components (`Trend 80, Pullback 60, Trigger 40, Event 20, Vol 100`):
     - `weight_trend: 40` -> 67 (contribution 32)
     - `weight_pullback: 40` -> 71 (contribution 24)
     - `weight_trigger: 40` -> 65 (contribution 16)
     - `weight_event: 40` -> 64 (contribution 8)
     - `weight_vol: 40` -> 89 (contribution 40)
   - Test Stocks mode renormalization with 40% weight override.
   - Test boundary values: 0%, 100%, 0.5%, 1%, default.
   - Test existing fractions (`0.9`, `0.123`) passed directly.
3. **Frontend Tests:**
   Add tests in `frontend/lib/__tests__/resolveWeightOverrides.test.ts` verifying:
   - `buildStockScanRequestBody` normalizes 40 -> 0.40, 1 -> 0.01, 100 -> 1.0, 0 -> 0.
   - `buildOptionsScanRequestBody` normalizes 40 -> 0.40, 1 -> 0.01, 100 -> 1.0, 0 -> 0.
   - `scanScheduleResolve` propagates normalized fractions into scheduled scan requests.
4. **Regression Tests:**
   - `backend/tests/test_overrides.py`
   - `backend/tests/test_stock_scan_overrides.py`
   - `npm run typecheck`
   - `npm run test`
   - `python scripts/state.py` (zero drift)
