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

- **Numeric Gate:** Prevent wrong scores (e.g. 3235 instead of 67, or 100x inflation for 1%) from reaching scan results, candidate rankings, and position cards.
- **Persistence Gate:** Saved Search Profiles in `localStorage` and Scan Schedules in `scan_schedule.yaml` must not be corrupted. Legacy entries with whole percentages (e.g., 40, 1) or fractions (0.40) must load, migrate, and evaluate cleanly.
- **Options Mode Invariant:** Only the overridden weight is changed; untouched weights retain their horizon defaults without recalibration.
- **Stocks Mode Invariant:** Overridden weights are normalized before event-zeroing and sum renormalization (`weights = {k: v / total_w for k, v in weights.items()}`).
- **Scorer Test Parity:** Existing unit tests in `backend/tests/test_overrides.py` passing fractions (`0.9`, `0.123`, `0.5`, `1`) continue to pass without regression.
- **Audit Verification:** The audit fixture in `docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/controls/backend-parameters.py` checks `score({'weight_trend': 40}) == 67` and must PASS.

---

## 3. Implementation Design

### A. Backend Scorer Normalization (`backend/app/scoring/stock_scorer.py`)
In `stock_scorer.py`:
1. Define a normalization helper:
   ```python
   def _normalize_weight(val: float | int | None) -> float:
       if val is None:
           return 0.0
       f = float(val)
       if f > 1.0:
           return f / 100.0
       return max(0.0, f)
   ```
   Properties:
   - For percentage values `val > 1.0` (e.g. `40` from `backend-parameters.py`, `100`), maps to `val / 100.0` (`0.40`, `1.0`).
   - For canonical fractions `val <= 1.0` (e.g. `0.01` for 1%, `0.40` for 40%, `0.9`, `0.123`, `0.5`, `1.0` for 100%), returns the fraction unchanged.
   - Idempotent: `_normalize_weight(_normalize_weight(x)) == _normalize_weight(x)`.
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
To ensure canonical unit propagation into API payloads:
1. In `frontend/lib/resolveStockScanRequest.ts` and `frontend/lib/resolveOptionsScanRequest.ts`:
   Step 3 sliders and number inputs define score weights with `min: 0, max: 100, step: 1, unit: '%'`. In `scanStore.scanOverrides`, user values are whole percentage numbers `[0, 100]`.
   Define and apply a weight normalization helper:
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
     return Math.max(0, val / 100.0);
   }
   ```
   Mapping:
   - `0` (0%) -> `0.0`
   - `1` (1%) -> `0.01`
   - `40` (40%) -> `0.40`
   - `100` (100%) -> `1.0`
   Apply `normalizeWeightOverride` when populating `stocksOverrides` in `buildStockScanRequestBody` and `effectiveOverrides` in `buildOptionsScanRequestBody`.
2. Test fixtures in frontend tests:
   - In `frontend/lib/__tests__/stockScanRequestPins.test.ts` and `frontend/lib/__tests__/a5AnalysisMirrorsScan.test.tsx`, mock `STEP3.weight_trend: 50` so that `50%` normalizes to `0.5`, preserving the existing test assertions `toEqual({ weight_trend: 0.5 })`.
   - In `frontend/lib/__tests__/p3aMinStockScore.test.ts`, update line 48 expectation from `30` to `0.3`.
3. `frontend/lib/scanScheduleResolve.ts` calls `buildOptionsScanRequestBody` and `buildStockScanRequestBody` directly; it must NOT apply a separate redundant normalization pass on `profile.scanOverrides`.

### C. Schedule Migration & Legacy Compatibility (`backend/app/services/scan_schedule_store.py`)
In `scan_schedule_store.py`:
1. Bump schema version: `_SCHEMA_VERSION = 3`.
2. Update `_migrate_entry`:
   Support migrating both `mode == "stocks"` and `mode == "options"`:
   ```python
   SCORE_WEIGHT_KEYS = {"weight_trend", "weight_pullback", "weight_trigger", "weight_event", "weight_vol"}

   @staticmethod
   def _migrate_entry(entry: object) -> object:
       """v1 -> v2: stocks entry drops strategy fields, sets params_horizon.
          v2 -> v3: weight overrides in resolved_request are normalized to canonical fractions."""
       if not (isinstance(entry, dict) and isinstance(entry.get("resolved_request"), dict)):
           return entry

       e = dict(entry)
       req = dict(e["resolved_request"])
       
       # v1 -> v2 stocks migration
       if e.get("mode") == "stocks":
           from app.services.horizon_profiles import migrate_saved_stock_request
           req = migrate_saved_stock_request(req)

       # v2 -> v3 weight normalization for both stocks and options
       ov = req.get("overrides")
       if isinstance(ov, dict):
           updated_ov = dict(ov)
           changed = False
           for k in SCORE_WEIGHT_KEYS:
               v = updated_ov.get(k)
               if isinstance(v, (int, float)) and v > 0:
                   # Legacy Step-3 saved unnormalized percentages [1..100]
                   if v >= 1.0:
                       updated_ov[k] = float(v) / 100.0
                       changed = True
           if changed:
               req["overrides"] = updated_ov

       e["resolved_request"] = req
       return e
   ```
3. Existing backup-before-migration and atomic write under lock in `_load()` will safely back up any version-2 file to `.bak` and persist the migrated version-3 file.

---

## 4. Verification & Testing Plan

1. **Audit Fixture Test:**
   Run `backend/.venv/Scripts/python.exe docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/controls/backend-parameters.py`.
   Assert `"40 percent trend weight unit"` passes.
2. **Backend Unit Tests:**
   Create `backend/tests/test_weight_units.py`:
   - Test all 5 score weight controls with 40% override in Options mode against fixed components (`Trend 80, Pullback 60, Trigger 40, Event 20, Vol 100`):
     - `weight_trend: 40` -> 67 (contribution 32)
     - `weight_pullback: 40` -> 71 (contribution 24)
     - `weight_trigger: 40` -> 65 (contribution 16)
     - `weight_event: 40` -> 64 (contribution 8)
     - `weight_vol: 40` -> 89 (contribution 40)
   - Test Stocks mode renormalization with 40% weight override (`unrounded_score == 67.368`, rounded to `67`).
   - Test backend direct-caller inputs:
     - `weight_trend: 40` -> normalized to 0.40
     - `weight_trend: 100` -> normalized to 1.0
     - `weight_trend: 0.01` -> preserved as 0.01 (1% weight)
     - `weight_trend: 0.40` -> preserved as 0.40
     - `weight_trend: 1.0` -> preserved as 1.0 (100% weight, matching `test_overrides.py:77`)
     - `weight_trend: 0.123` -> preserved as 0.123 (matching `test_overrides.py:37`)
   - Test schedule store migration:
     - v2 entry with `{weight_trend: 40}` in both stocks and options modes upgrades to v3 with `{weight_trend: 0.40}`.
     - v2 entry with `{weight_trend: 1}` upgrades to v3 with `{weight_trend: 0.01}`.
     - v2 entry with `{weight_trend: 100}` upgrades to v3 with `{weight_trend: 1.0}`.
3. **Frontend Tests:**
   Add tests in `frontend/lib/__tests__/resolveWeightOverrides.test.ts` verifying:
   - `buildStockScanRequestBody` normalizes Step 3 percentages: 0 -> 0.0, 1 -> 0.01, 40 -> 0.40, 100 -> 1.0.
   - `buildOptionsScanRequestBody` normalizes Step 3 percentages: 0 -> 0.0, 1 -> 0.01, 40 -> 0.40, 100 -> 1.0.
   - Scheduled scan requests produced via `scanScheduleResolve` carry normalized decimal fractions.
4. **Regression Tests:**
   - `backend/tests/test_overrides.py`
   - `backend/tests/test_stock_scan_overrides.py`
   - `backend/tests/test_scan_schedule_recovery.py`
   - `npm run typecheck`
   - `npm run test`
   - `python scripts/state.py` (zero drift)
