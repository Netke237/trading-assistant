# Adversarial Code Audit: Stop Percentage Units and Clamping (APP-AUDIT-B-STOP-PERCENT-UNITS)

**Target Diff:** `origin/main` (55519e05) .. `HEAD` (9b9033bd)  
**Plan:** `docs/superpowers/plans/2026-10-21-app-audit-b-stop-percent-units-plan.md`  
**Auditor:** Independent Adversarial Subagent (`bmad-review-adversarial-general` - `subagent:e1fa7f94-2583-44e3-a01a-392152991d04`)  

---

### Inspected Files & Scope
1. `frontend/app/(frame)/screener/step-3-direction/page.tsx`
2. `frontend/app/(frame)/screener/step-3-direction/__tests__/paramDefaults.stopPercentUnits.test.tsx`
3. `docs/superpowers/plans/2026-10-21-app-audit-b-stop-percent-units-plan.md`
4. `docs/superpowers/PROJECT_STATE.json`
5. Downstream consumers & integrations:
   - `frontend/lib/executionParamDefaults.ts`
   - `frontend/lib/tradeCardOverride.ts`
   - `frontend/lib/resolveStockScanRequest.ts`
   - `frontend/lib/resolveOptionsScanRequest.ts`
   - `frontend/lib/searchProfilesStore.ts`
   - `backend/app/routers/contracts.py`
   - `backend/app/services/config_loader.py`

---

### What Was Checked Against THE GATE

1. **User Number Display & Unit Scaling (`page.tsx`):**
   - Verified `PARAM_DEFS` definitions for `rr_bullish_invalidation_pct` and `rr_bearish_invalidation_pct`:
     - Added `scale: 100`, `min: 0.5`, `max: 100`, `step: 0.5`, `unit: '%'`.
   - Verified `formatDefault(val, def)`:
     - Correctly scales canonical default `0.03` by 100 to return `"3"`.
     - In the UI, the default column renders as `3%` matching the row hint (`Default: 3%`), eliminating the prior bug where `0.03%` was shown to users.
   - Verified `inputValue` calculation:
     - Uses `formatNumberValue(val)` where `scaled = def.scale ? val * def.scale : val; String(Number(scaled.toFixed(4)))`.
     - Displays `3` for default, `4` for stored fraction `0.04`, `0.5` for minimum `0.005`, and `100` for maximum `1.0`. Trailing decimal precision is cleanly handled without floating-point artifacts.

2. **Broker Orders & Invalidation Calculation (`onChange` / `onBlur`):**
   - Verified that user typing `3` (intending 3%) converts via `3 / 100 = 0.03`, matches default `0.03` within `1e-6`, and removes the override.
   - Verified user typing `4` converts via `4 / 100 = 0.04`, storing canonical decimal fraction `0.04` in `scanOverrides`.
   - Verified `onBlur` clamping:
     - `minStored = 0.5 / 100 = 0.005` (0.5%), `maxStored = 100 / 100 = 1.0` (100%).
     - Out-of-bounds input (e.g. typing `150`) clamps on blur to `1.0` (100%).
     - Sub-minimum input (e.g. typing `0.1`) clamps on blur to `0.005` (0.5%).
     - Clamping rounds to 6 decimal places (`toFixed(6)`), preventing floating-point drift.
     - Crucially, this resolves Finding C7 where typing `3` formerly clamped to `def.max = 1.0` (100% stop distance, which wiped out stop losses on broker trade orders).

3. **Persisted Data Integrity (Search Profiles):**
   - Verified `searchProfilesStore.ts` and `localStorage` snapshot handling:
     - `scanOverrides` persists canonical decimal fractions (e.g. `0.04`).
     - Legacy/existing stored profiles containing `{ rr_bullish_invalidation_pct: 0.04 }` hydrate directly into `scanOverrides` without data migration or corruption, and render as `4` in the UI.
     - Saving newly modified profiles continues to persist canonical fractions, keeping backwards and forwards compatibility intact.

4. **Downstream API & Scoring Contract Invariants:**
   - `backend/app/routers/contracts.py` enforces `Field(default=None, gt=0, le=1.0)`.
   - `backend/app/services/config_loader.py` caps overrides at `1.0`.
   - `buildStockScanRequestBody`, `buildOptionsScanRequestBody`, and `rrOverridesFrom` all forward the canonical fraction `0.04` directly from `scanOverrides`. Neither the scan requests nor the trade card recompute plans receive out-of-range whole percentages.

5. **Override Badges & Active Count:**
   - In `countActiveOverrides`, scaled parameters compare `Math.abs(ov - defaults[d.key]) >= 1e-6`.
   - Overrides equal to default do not increment the badge count; actual changes increment it cleanly.

6. **Automated Verification & State Tracking:**
   - Frontend Jest suite (`npm test -- --testPathPattern=stopPercentUnits` and related suites): 87 tests passing.
   - Frontend typecheck (`npm run typecheck`): 0 errors.
   - Backend pytest suites (`test_config_loader.py`, `test_stock_stop_resolution.py`): 77 tests passing.
   - `py scripts/state.py`: No drift reported; verify probe `key: .rr_bullish_invalidation_pct..*scale: 100` matches `page.tsx`.

---

GATE FINDINGS: 0
