# Adversarial Audit (Round 2): APP-AUDIT-B-WEIGHT-UNITS Plan

**Target:** `docs/superpowers/plans/2026-10-21-app-audit-b-weight-units-plan.md`  
**Review Type:** Independent adversarial review of Round 1 fixes (F-1, F-2, F-3) and their interactions  
**Auditor:** Independent subagent `f53ca48c-eb15-49a7-b4cf-a17cf1e19290`  
**Gate:** Numeric / Persistence Gate (0 gate findings required for clean exit)  

---

### Context & Codebase Checked
- `backend/app/scoring/stock_scorer.py` (lines 1115–1235)
- `backend/app/services/scan_schedule_store.py` (lines 40–160)
- `frontend/lib/resolveStockScanRequest.ts` (lines 15–30, 135–227)
- `frontend/lib/resolveOptionsScanRequest.ts` (lines 100–186)
- `frontend/lib/scanScheduleResolve.ts` (lines 65–145)
- `frontend/app/(frame)/screener/step-3-direction/page.tsx` (lines 50–65, 415–505)
- `backend/tests/test_overrides.py` (lines 30–85)
- `docs/superpowers/audits/APP-AUDIT-B-WEIGHT-UNITS/plan-r1.md`
- `docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/controls/findings.md` (finding C4)
- `docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/controls/backend-parameters.py`
- `docs/superpowers/PROJECT_STATE.json`

---

## Findings

### Finding F2-1
- **File & Line:** `docs/superpowers/plans/2026-10-21-app-audit-b-weight-units-plan.md:68-76` (Frontend request resolvers in `resolveStockScanRequest.ts` and `resolveOptionsScanRequest.ts`)
- **Concrete Failing Scenario:**
  Step 3 defines all 5 score weight controls with `min: 0, max: 100, step: 1, unit: '%'` (`step-3-direction/page.tsx:55-64`). A user edits Trend weight to `1%` (an integer input representing 1%). `scanStore.scanOverrides` stores `{ weight_trend: 1 }`.
  When building the request payload, `normalizeWeightOverride(1)` executes:
  ```ts
  if (val > 1.0) return val / 100.0;
  return Math.max(0, val);
  ```
  Because `1 > 1.0` evaluates to `false`, it returns `1` unchanged. The request payload is dispatched over the wire with `overrides: { weight_trend: 1 }`.
  The backend scorer (`stock_scorer.py`) receives `1`, where `_normalize_weight(1)` also evaluates `1.0 > 1.0` as `false` and returns `1.0`.
  The scorer assigns `w["trend"] = 1.0` (100% weight) instead of `0.01` (1% weight) — a 100-fold inflation.
  - In Options mode, with Trend score 80 and other scores averaging 50, Trend contributes 80 points instead of 0.8 points, inflating composite score from 36 (CAUTION) to 115 (PASS).
  - In Stocks mode, Trend commands 64.5% of the total composite score instead of 1.78%.
  Furthermore, typing `1%` and typing `100%` produce the exact same weight (`1.0`), while typing `2%` produces `0.02` (3.4% effective weight), creating a severe discontinuity at 1%.
- **Why It Meets the Gate:**
  Puts WRONG NUMBERS (inflated candidate scores, inverted rankings, false PASS statuses) directly in front of the user in screener tables, Step 4 candidate cards, and Step 7 Trade Cards.
- **Suggested Fix:**
  Recognize that values in `scanStore.scanOverrides` originating from Step 3 are always whole percentage numbers [0, 100]. `normalizeWeightOverride` in frontend request builders must convert percentage values to decimal fractions (`val / 100.0`, e.g. `1` -> `0.01`, `40` -> `0.40`, `100` -> `1.0`). Any test fixtures in frontend tests that erroneously passed fractions like `0.5` directly into mock contexts should be updated to pass standard percentages (e.g. `50`).

---

### Finding F2-2
- **File & Line:** `docs/superpowers/plans/2026-10-21-app-audit-b-weight-units-plan.md:106-113` (Schedule migration in `backend/app/services/scan_schedule_store.py`)
- **Concrete Failing Scenario:**
  A user previously saved a scan schedule under schema version 1 or 2 using a profile that configured a 1% score weight override (`weight_trend: 1`).
  When `ScanScheduleStore._migrate_entry` runs during v2 -> v3 migration:
  ```python
  for k in SCORE_WEIGHT_KEYS:
      v = updated_ov.get(k)
      if isinstance(v, (int, float)) and v > 1.0:
          updated_ov[k] = float(v) / 100.0
          changed = True
  ```
  Because `v = 1` and `1 > 1.0` evaluates to `false`, the override is NOT divided by 100.
  The persisted entry remains saved as `weight_trend: 1` in `scan_schedule.yaml`.
  When the background schedule fires, `resolved_request["overrides"]` passes `weight_trend: 1` to `stock_scorer.py`, which evaluates it as 100% weight (`1.0`) instead of 1% (`0.01`).
  The scheduled scan executes indefinitely with 100% weight instead of 1% weight.
- **Why It Meets the Gate:**
  CORRUPTS PERSISTED DATA and schedule execution semantics by failing to migrate legacy percentage overrides equal to 1, causing scheduled scans and alert triggers to produce wrong scores.
- **Suggested Fix:**
  In `_migrate_entry`, because schema version 1 and 2 entries were saved by older clients that saved raw Step 3 percentage inputs without normalization, any non-zero numeric weight override was stored as a percentage. The migration should normalize integer/percentage overrides `v >= 1` (or `v > 0`) to canonical decimal fractions `float(v) / 100.0`.

---

### Finding F2-3
- **File & Line:** `docs/superpowers/plans/2026-10-21-app-audit-b-weight-units-plan.md:135-136` (Section 4 Verification & Testing Plan)
- **Concrete Failing Scenario:**
  Section 4 contains contradictory test requirements:
  - Line 135: "Test boundary values: 0%, 100%, 0.5%, 1%, default." (which requires 1% input to yield a normalized weight of `0.01`).
  - Line 136: "Test existing fractions (0.9, 0.123, 1) passed directly without modification." (which asserts that input `1` is kept as `1.0` without modification).
  Because in Python `1 == 1.0`, a single function `_normalize_weight` cannot simultaneously treat `1` as `0.01` and treat `1` as `1.0`. A developer following this plan will either skip the 1% boundary test to satisfy line 136, or hardcode `1 -> 1.0` and assert that 1% produces 100% weight, masking defect F2-1.
- **Why It Meets the Gate:**
  A comment/plan specification counts if a competent reader acting on it would write a wrong change (it misstates mechanism). Specifying that `1` must be passed directly without modification while also specifying that `1%` must be tested conflates the backend direct-caller compatibility with the wire/UI percentage normalization contract.
- **Suggested Fix:**
  Disentangle the test specifications: `stock_scorer._normalize_weight` in Python treats `1` as `1.0` for backwards compatibility with direct Python callers (`test_overrides.py`), whereas the frontend resolver tests in `resolveWeightOverrides.test.ts` must test that UI percentage input `1%` maps to `0.01`.

---

## Summary of Fixes Verified Clean
1. **F-1 (Redundant normalization in `scanScheduleResolve`):** The removal of the extra normalization pass from `scanScheduleResolve.ts` is verified clean — it delegates solely to `buildOptionsScanRequestBody` and `buildStockScanRequestBody`.
2. **F-3 (Schema version bump & Options mode in `scan_schedule_store.py`):** Bumping `_SCHEMA_VERSION = 3` and migrating both stocks and options entries under lock with backup is structurally verified clean.

---

GATE FINDINGS: 3
