# Adversarial Code Review: APP-AUDIT-B-STRATEGY-VALIDATION (#373)

**Scope**: git diff `origin/main` (3ef4a9ef1885c18694640dfb7a8e631618b68a14) .. `HEAD` (401de618)
**Plan Checked Against**: `docs/superpowers/plans/2026-10-19-app-audit-b-strategy-validation-plan.md`
**Reviewer**: Fresh independent subagent `3b2baac3-e6cf-4e7a-95d0-716c617253f8`

## Inspected Files
- `frontend/lib/strategyScanValidation.ts`
- `frontend/lib/scanParamsStore.ts`
- `frontend/lib/searchProfilesStore.ts`
- `frontend/lib/searchProfileSnapshot.ts`
- `frontend/lib/resolveStockScanRequest.ts`
- `frontend/lib/stockScan.ts`
- `frontend/app/(frame)/settings/page.tsx`
- `frontend/components/organisms/SearchProfileBar/index.tsx`
- `frontend/lib/__tests__/strategyScanValidation.test.ts`
- `frontend/lib/__tests__/strategyScanStoreValidation.test.ts`
- `frontend/app/(frame)/settings/__tests__/StrategyScanForm.validation.test.tsx`
- `frontend/components/organisms/SearchProfileBar/__tests__/SearchProfileBar.validation.test.tsx`
- `frontend/lib/__tests__/stockScan.test.ts`

---

## Checks Executed & Invariants Verified

1. **Backend Schema & Boundary Alignment (`StockScanRequest` vs `strategyScanValidation.ts`)**:
   - Compared against `StockScanRequest` in `backend/app/schemas/stock_scan.py`:
     - `pullback_tolerance_pct`: schema `Field(None, gt=0, le=1.0)`. Checked `validatePullbackToleranceOverride`: enforces finite float, `val <= 0 || val > 1.0` rejected, fractions in `(0, 1.0]` accepted.
     - `ma_crossover_lookback`: schema `Field(None, gt=0)` (integer). Checked `validateMaCrossoverLookbackOverride`: enforces `Number.isInteger(val)` and `val < 1` rejected, integers `>= 1` accepted.
     - `breakout_volume_mult`: schema `Field(None, gt=1.0)` (strict lower bound > 1.0). Checked `validateBreakoutVolumeMultOverride`: enforces finite float, `val <= 1.0` rejected, floats `> 1.0` accepted.
   - Tested offline against Python 3.11.15 using actual `StockScanRequest.model_validate` over boundary cases (`pullback_tolerance_pct` at 0.08, 0.004, 1.0, 0.0, -0.01, 1.01; `ma_crossover_lookback` at 1, 30, 0, -1; `breakout_volume_mult` at 1.01, 4.0, 1.0, 0.9). All boundaries produced byte-for-byte identical acceptance/rejection between client validation and Pydantic validation.

2. **Persistence & Store Mutation Atomicity (`scanParamsStore.ts`, `searchProfilesStore.ts`)**:
   - `setParam`: validates `pullbackTolerancePct`, `maCrossoverLookback`, and `breakoutVolumeMult` before `set(...)`. Rejection throws `StrategyScanValidationError` and leaves store state intact. Unrelated fields (`btMinWinRate: 0`, `btMinTrades: 5`, etc.) pass through unblocked, preserving legitimate zero values.
   - `loadParams`: validates all three overrides atomically before `set({ ...NO_OVERRIDES, ...p })`. Any invalid override leaves the existing store state completely unmodified.
   - `saveProfile` and `updateProfile`: validates `snapshot.strategyParams` overrides before modifying `profiles` array or writing to localStorage.
   - `migrateScanParams`: no version bump or migration overwrite; invalid legacy state is preserved until explicit user edit, satisfying the fail-closed persistence requirement.

3. **Search Profile Bar & Selection Atomicity (`SearchProfileBar/index.tsx`, `searchProfileSnapshot.ts`)**:
   - Verified resolution of Plan F1: `handleSelect` invokes `applySearchProfile` before `setSelectedId`. If the chosen profile fails validation, error is caught, `error` state is populated with the validation message, `selectedId` remains on the prior profile (or `null`), and active parameters in `scanParamsStore`/`scanStore` remain untouched.
   - Verified that `Update "{profile.name}"` cannot be rendered for an invalid profile when choosing it while another profile is active.
   - `handleUpdate` and `onSave` catch validation errors, display actionable messages in `role="alert"`, and keep stored profiles intact.

4. **Request Builder & Manual Scan Boundary (`resolveStockScanRequest.ts`, `stockScan.ts`)**:
   - `buildStockScanRequestBody` calls `assertStrategyScanOverrides` at its entry point, blocking direct consumers (manual scans, schedules, analysis, report inputs) from sending invalid strategy overrides.
   - `runStockScanWithContinuation` identifies `err instanceof StrategyScanValidationError`, sets `isValidationError = true`, displays `err.message` in `stockScanError` and `stockScanFeedback`, does not log spurious `STOCK_SCAN_SETTINGS_INVALID` console errors, re-enables the Run button by transitioning to `FAILED`, and does not post to `/api/stock-scan`.
   - `resyncScheduleEntriesForProfile`: caught resolution failures mark referencing entries in `staleScheduleEntryIds` instead of silently succeeding.

5. **Settings UI Draft State & Accessibility (`settings/page.tsx`)**:
   - `OverrideInput` initializes `error` on mount if stored value is schema-invalid, rendering an initial accessible alert.
   - Schema-valid legacy values outside the editing range (e.g. breakout multiplier 4.0 or pullback 0.004) are not retroactively rejected or wiped.
   - In-progress invalid drafts (e.g. typing "0") stay in local state with `aria-invalid="true"` and an active `role="alert"` without updating `scanParamsStore`.
   - Valid edits commit immediately as exact numerical fractions without rounding.
   - Clear button sets store to `null` and resets draft and error. External reset to defaults correctly synchronizes and resets draft.

6. **Regression Tests and Static Analysis**:
   - `npm run typecheck` (`tsc --noEmit`): clean, 0 errors.
   - Focused test suites (`strategyScanValidation.test.ts`, `strategyScanStoreValidation.test.ts`, `StrategyScanForm.validation.test.tsx`, `SearchProfileBar.validation.test.tsx`, `stockScan.test.ts`): 9 test suites, 100 passing tests.
   - `scripts/state.py`: clean exit, no drift detected.

---

GATE FINDINGS: 0
