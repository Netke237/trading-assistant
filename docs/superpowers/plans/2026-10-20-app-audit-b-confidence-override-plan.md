# Plan: APP-AUDIT-B-CONFIDENCE-OVERRIDE (#383)

## 1. Problem Statement
Issue #383 (remediation of Finding C5 from `#350` / `docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/controls/findings.md`):
When a user edits the Step 3 panel's `confidence_caution_below` or `confidence_reject_below` thresholds (or applies a Search Profile with custom confidence thresholds, including an explicit `0`), the Stocks scan request completely ignores these overrides.
Instead, `frontend/lib/resolveStockScanRequest.ts` unconditionally copies `confidenceGate.cautionBelow` and `confidenceGate.rejectBelow` from `settingsStore` whenever `confidenceGate.enabled` is true.

## 2. Root Cause Analysis
In `frontend/lib/resolveStockScanRequest.ts`:
- Top-level `confidence_caution_below` and `confidence_reject_below` are correctly excluded from `STOCKS_SCORER_KEYS` (lines 17–29) because they are top-level `StockScanRequest` fields rather than entries in `overrides: dict[str, Any]`.
- However, when constructing the return object in `buildStockScanRequestBody` (lines 174–175):
  ```typescript
  confidence_caution_below: confidenceGate.enabled ? confidenceGate.cautionBelow : undefined,
  confidence_reject_below: confidenceGate.enabled ? confidenceGate.rejectBelow : undefined,
  ```
  The builder never consults `rawOverrides.confidence_caution_below` or `rawOverrides.confidence_reject_below`.
- In contrast, Options-mode request resolution (`frontend/lib/resolveOptionsScanRequest.ts`, lines 124–133) properly checks `typeof cautionOv === 'number'` and `typeof rejectOv === 'number'`, falling back to `gate.cautionBelow` / `gate.rejectBelow` only when the override is omitted.
- Furthermore, explicit `0` is a valid threshold (e.g. Setting caution below to 0% to effectively disable cautioning while keeping rejection active). Using a simple falsy check like `rawOverrides.confidence_caution_below || gate.cautionBelow` would erroneously drop `0`. A strict `typeof ... === 'number' && Number.isFinite(...)` check preserves `0`.

## 3. Proposed Changes

### File: `frontend/lib/resolveStockScanRequest.ts`
Update `buildStockScanRequestBody` to respect `rawOverrides.confidence_caution_below` and `rawOverrides.confidence_reject_below` when `confidenceGate.enabled` is `true`:

```typescript
    confidence_caution_below: confidenceGate.enabled
      ? (typeof rawOverrides.confidence_caution_below === 'number' && Number.isFinite(rawOverrides.confidence_caution_below)
          ? rawOverrides.confidence_caution_below
          : confidenceGate.cautionBelow)
      : undefined,
    confidence_reject_below: confidenceGate.enabled
      ? (typeof rawOverrides.confidence_reject_below === 'number' && Number.isFinite(rawOverrides.confidence_reject_below)
          ? rawOverrides.confidence_reject_below
          : confidenceGate.rejectBelow)
      : undefined,
```

### Behavioral Invariants:
1. **Gate Enabled + Overrides Present**: If `confidenceGate.enabled === true` and `rawOverrides.confidence_caution_below` / `confidence_reject_below` is a finite number, the override is sent directly (including `0`).
2. **Gate Enabled + Overrides Absent/Null/Undefined**: If `confidenceGate.enabled === true` and no valid numeric override is present, fallback to `confidenceGate.cautionBelow` and `confidenceGate.rejectBelow`.
3. **Gate Disabled**: If `confidenceGate.enabled === false`, `confidence_caution_below` and `confidence_reject_below` are both `undefined`, disabling the confidence gate at the backend level (which leaves them `None`).
4. **Scope Isolation**: `STOCKS_SCORER_KEYS` remains unchanged; `confidence_caution_below` and `confidence_reject_below` remain top-level request parameters and are not dumped into the `overrides` dictionary.
5. **Shared Consumers**: Manual scans (`stockScan.ts`), scheduled scans (`scanScheduleResolve.ts`), search profile resolution (`searchProfilesStore.ts`), and analysis queries (`analysisStore.ts`) all use `buildStockScanRequestBody` and immediately benefit from this fix without additional code changes.

## 4. Verification & Testing Strategy

### Unit Tests
Create / extend unit tests in `frontend/lib/__tests__/resolveStockScanRequest.confidence.test.ts`:
1. **Explicit Overrides (non-zero)**: `confidence_caution_below: 65`, `confidence_reject_below: 45` with gate at 50/35 -> sends 65 and 45.
2. **Explicit Zero**: `confidence_caution_below: 0`, `confidence_reject_below: 0` with gate at 50/35 -> sends 0 and 0.
3. **One Override Present, One Absent**: `confidence_caution_below: 60`, `confidence_reject_below: undefined` with gate at 50/35 -> sends 60 and 35.
4. **Null / Non-Numeric Overrides**: `confidence_caution_below: null` -> falls back to 50.
5. **Gate Disabled**: `confidenceGate.enabled: false` -> both are `undefined`, regardless of overrides.
6. **Scheduled Scan Parity**: `resolveProfileToScanRequest` with stocks profile carrying confidence overrides outputs identical request thresholds.
7. **Regression Pins**: Existing tests in `stockScanRequestPins.test.ts` and `a5AnalysisMirrorsScan.test.tsx` pass without regressions.

### State & Typecheck
- Verify `python scripts/state.py` passes with zero drift once built.
- Verify `npm run typecheck` (`tsc --noEmit`) passes with 0 errors.

## 5. Numeric / Persistence Gate Evaluation
- **No Wrong Numbers**: Correctly routes the user's configured confidence threshold to the backend scoring pipeline rather than substituting stale settings store values.
- **No Data Corruption**: Pure request mapping function; does not mutate persisted stores or disk state.
- **Mechanism Accuracy**: Matches documented schema in `StockScanRequest` and mirrors Options mode parity in `resolveOptionsScanRequest.ts`.
