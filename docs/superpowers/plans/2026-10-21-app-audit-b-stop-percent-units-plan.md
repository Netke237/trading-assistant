# Implementation Plan: Fix Stop Percentage Units and Clamping (APP-AUDIT-B-STOP-PERCENT-UNITS)

**Goal:** Fix Finding C7 from audit #350 (Issue #385) so that Step 3 "Reward/Risk" invalidation stop percentages (`rr_bullish_invalidation_pct` and `rr_bearish_invalidation_pct`) render, accept input, and clamp in whole percentage units (e.g. default 3%, range 0.5%–100%) in the UI, while preserving canonical decimal fraction storage and payloads (`0.005`–`1.0`) across `scanOverrides`, saved Search Profiles, and backend APIs.

---

## 1. Problem & Root Cause

### Finding C7 Mechanism
- In `frontend/app/(frame)/screener/step-3-direction/page.tsx`, `PARAM_DEFS` defines:
  ```tsx
  { key: 'rr_bullish_invalidation_pct', label: 'Bullish stop %', type: 'number', section: 'all', subGroup: 'Reward/Risk', min: 0.005, max: 1.0, step: 0.005, unit: '%', ... }
  { key: 'rr_bearish_invalidation_pct', label: 'Bearish stop %', type: 'number', section: 'all', subGroup: 'Reward/Risk', min: 0.005, max: 1.0, step: 0.005, unit: '%', ... }
  ```
- In `frontend/lib/executionParamDefaults.ts`, the default value across all horizons is `0.03` (the backend fraction representing 3%).
- In `ParamRow`:
  - `formatDefault(defaultVal)` prints raw `0.03`. With `unit: '%'` in the row, the default displays as `0.03%` (3 basis points), contradicting the hint: "Default: 3%".
  - The input renders with `value="0.03" min="0.005" max="1" step="0.005"`.
  - When a user enters `3` intending 3%, `onBlur` clamps `3` to `def.max = 1.0`.
  - The clamped value `1.0` is stored in `scanOverrides` and sent to the backend, which treats `1.0` as a **100% stop distance** (`price * (1 - 1.0) = 0`), wiping out the stop loss entirely.

### Core Invariants & Gate Requirements
- **Backend contract:** `backend/app/routers/contracts.py` validates `rr_bullish_invalidation_pct: float | None = Field(default=None, gt=0, le=1.0)`. `backend/app/services/config_loader.py` enforces `_RR_OVERRIDE_CAPS = 1.0` and `0 < val <= 1.0`. Backend calculations (`backend/app/scoring/exit_plan.py`, `backend/app/scoring/stock_scorer.py`, `backend/app/routers/scan.py`) compute `price * (1 - invalidation_pct)`. Thus, backend requires decimal fractions in `(0, 1.0]`.
- **Persisted Search Profiles:** Existing profiles in `localStorage` (`searchProfilesStore.ts`) store fractions such as `{ rr_bullish_invalidation_pct: 0.04 }`. Altering the stored representation to whole numbers would corrupt persisted profiles or misread 0.04 as 0.04% (0.0004).
- **The Gate:** Prevent any wrong numbers in front of the user (e.g. displaying 0.03% instead of 3%), wrong broker orders (100% stop instead of 3%), or persisted data corruption.

---

## 2. Proposed Design & Changes

### 2.1 Add `scale` Factor to `ParamDef`
In `frontend/app/(frame)/screener/step-3-direction/page.tsx`:
```ts
interface ParamDef {
  key: string;
  label: string;
  type: 'number' | 'boolean' | 'select' | 'display';
  section: 'stocks' | 'options' | 'all';
  subGroup: string;
  options?: string[];
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
  hint?: string;
  redundant?: true;
  deprecated?: true;
  visibleFor?: string[];
  scale?: number; // Scaling factor between stored canonical representation and UI display/input (e.g. 100 for percentage fractions)
}
```

### 2.2 Configure `rr_bullish_invalidation_pct` and `rr_bearish_invalidation_pct`
Update their `PARAM_DEFS` definitions:
- `scale: 100`
- `min: 0.5` (representing 0.5% in UI, 0.005 in storage)
- `max: 100` (representing 100% in UI, 1.0 in storage)
- `step: 0.5` (representing 0.5% in UI, 0.005 in storage)
- `unit: '%'`
- `hint` preserved: "Default: 3%"

### 2.3 Update Display and Input in `ParamRow`
In `frontend/app/(frame)/screener/step-3-direction/page.tsx`:
1. **`formatDefault(val, def)`**:
   - If `def?.scale && typeof val === 'number'`, compute `Number((val * def.scale).toFixed(4))`.
   - For `val = 0.03`, returns `"3"`.
2. **`inputValue` computation**:
   - If `currentOverride !== undefined`:
     - If `def.scale && typeof currentOverride === 'number'`, use `String(Number((currentOverride * def.scale).toFixed(4)))`.
     - Else `String(currentOverride)`.
   - Else:
     - If `def.scale && typeof defaultVal === 'number'`, use `String(Number((defaultVal * def.scale).toFixed(4)))`.
     - Else `String(defaultVal)`.
3. **`onChange` handler**:
   - When user inputs `raw`:
     - If `raw === ''`: delete override from `scanOverrides`.
     - Else parse `num = Number(raw)`. If `!Number.isNaN(num)`:
       - If `def.scale`:
         - Convert to stored fraction: `const storedVal = Number((num / def.scale).toFixed(6));`
         - If `typeof defaultVal === 'number' && Math.abs(storedVal - defaultVal) < 1e-6`:
           delete override from `scanOverrides`.
         - Else:
           `setScanOverrides({ ...scanOverrides, [def.key]: storedVal });`
       - Else:
         - If `raw === String(defaultVal)`: delete override.
         - Else `setScanOverrides({ ...scanOverrides, [def.key]: num });`
4. **`onBlur` clamping**:
   - When user blurs:
     - If `def.scale`:
       - Stored value `current = scanOverrides[def.key]`.
       - Min stored bound = `def.min / def.scale` (0.005).
       - Max stored bound = `def.max / def.scale` (1.0).
       - Clamp `current` within `[minStored, maxStored]`, rounded to `Number(clamped.toFixed(6))`.
       - If `clamped !== current`: update `scanOverrides[def.key] = clamped`.
5. **`countActiveOverrides`**:
   - When comparing `ov !== defaults[d.key]`:
     - If `d.scale && typeof ov === 'number' && typeof defaults[d.key] === 'number'`:
       return `Math.abs(ov - (defaults[d.key] as number)) >= 1e-6`.

---

## 3. End-to-End Flow & Boundary Verification

1. **Default State:**
   - Default column displays `3`.
   - Input shows `3` with `%` suffix. Row displays "Bullish stop %3%".
   - `scanOverrides.rr_bullish_invalidation_pct` is `undefined`.
   - Scans and recompute use default `0.03` (3%).
2. **User Enters 4 (4%):**
   - User types `4`.
   - Converted to `4 / 100 = 0.04`.
   - Stored in `scanOverrides.rr_bullish_invalidation_pct` as `0.04`.
   - Not clamped (since `4 <= 100`).
   - Scan request receives `overrides: { rr_bullish_invalidation_pct: 0.04 }`.
   - Recompute plan receives `rr_bullish_invalidation_pct: 0.04`.
3. **Boundary Value Min (0.5%):**
   - User types `0.5`.
   - Stored in `scanOverrides` as `0.005`.
   - Scan request and backend receive `0.005` (0.5%).
4. **Boundary Value Max (100%):**
   - User types `100`.
   - Stored in `scanOverrides` as `1.0`.
   - Scan request and backend receive `1.0` (100%).
5. **Out-of-Bounds Clamping:**
   - User types `150`: on blur, clamped to `100` (stored as `1.0`).
   - User types `0.1`: on blur, clamped to `0.5` (stored as `0.005`).
6. **Clearing Override:**
   - User types `3` (matching default `0.03`): override key deleted from `scanOverrides`.
   - User clears input to `""`: override key deleted from `scanOverrides`.
7. **Search Profile Preservation:**
   - Existing profile with `0.04` in `localStorage`:
     - Snapshot load sets `scanOverrides.rr_bullish_invalidation_pct = 0.04`.
     - Step 3 UI renders input as `4`.
     - Backend requests send `0.04`.
     - Zero data corruption or format incompatibility.

---

## 4. Verification & Testing

1. **New Automated Suite:**
   Create `frontend/app/(frame)/screener/step-3-direction/__tests__/paramDefaults.stopPercentUnits.test.tsx` verifying:
   - Default rendered text and input values for both `rr_bullish_invalidation_pct` and `rr_bearish_invalidation_pct`.
   - Typing whole percentages (e.g. `4`) sets store fraction (`0.04`).
   - Typing boundary values (`0.5` → `0.005`, `100` → `1.0`).
   - Clamping out-of-bounds inputs on blur (`150` → `100`/`1.0`, `0.1` → `0.5`/`0.005`).
   - Restoring default removes override from store.
   - Profile hydration with fraction `0.04` renders as `4` in UI.
   - Scan request and recompute builders (`resolveStockScanRequest`, `resolveOptionsScanRequest`, `rrOverridesFrom`) carry the uncorrupted fraction `0.04`.
2. **Regression Check:**
   - Run `frontend/lib/__tests__/executionParamDefaults.rrDefaults.test.ts`.
   - Run `frontend/app/(frame)/screener/step-7-trade-card/__tests__/rr-overrides-from-scan.test.tsx`.
   - Run `frontend/lib/__tests__/tradeCardOverride.rrOverrides.test.ts`.
   - Run `frontend/lib/__tests__/searchProfilesTargetMigration.test.ts`.
   - Run full frontend Jest test suite (`npm test`).
   - Run TypeScript typecheck (`npm run typecheck`).
3. **Adversarial Audit:**
   - Independent plan audit (Round 1).
   - Independent code audit (Round 1).
   - `python3 scripts/state.py` zero drift verification.
