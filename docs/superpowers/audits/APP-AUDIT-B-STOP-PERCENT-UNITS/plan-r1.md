# Adversarial Audit Report: Stop Percentage Units and Clamping Plan (APP-AUDIT-B-STOP-PERCENT-UNITS)

**Target Plan:** `docs/superpowers/plans/2026-10-21-app-audit-b-stop-percent-units-plan.md`  
**Auditor:** Independent Adversarial Subagent (`bmad-review-adversarial-general` - `subagent:0d2f7c8c-06d3-4cf7-87da-cf8f3fcbdc0e`)  
**Scope Checked:**
- `docs/superpowers/plans/2026-10-21-app-audit-b-stop-percent-units-plan.md`
- `frontend/app/(frame)/screener/step-3-direction/page.tsx` (lines 205–235, 237–250, 405–455)
- `frontend/lib/executionParamDefaults.ts` (lines 68–71, 95–97)
- `frontend/lib/tradeCardOverride.ts` (lines 185–225)
- `frontend/lib/resolveStockScanRequest.ts` (lines 15–30, 140–190)
- `frontend/lib/resolveOptionsScanRequest.ts` (lines 100–160)
- `backend/app/routers/contracts.py` (lines 440–445, 490–515)
- `backend/app/services/config_loader.py` (lines 430–497)
- `docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/controls/findings.md` (item C7)
- `docs/superpowers/PROJECT_STATE.json`

---

## Audit Analysis & Verification

### 1. UI Display & Input Transformation (Finding C7)
- **Mechanism in Plan:** Adding `scale?: number` to `ParamDef` (set to `100` for `rr_bullish_invalidation_pct` and `rr_bearish_invalidation_pct`), with `min: 0.5`, `max: 100`, `step: 0.5`, `unit: '%'`.
- **Default Column Display:** In `ParamRow`, `formatDefault(defaultVal, def)` scales `0.03` by 100, formatting to `"3"`. Aligns with row hint `"Default: 3%"` and unit `"%"` (fixes `0.03%` display bug).
- **Controlled Input Display:** `inputValue` scales existing overrides or defaults (`0.03` → `"3"`, `0.04` → `"4"`).
- **Typing & Store Mutation:** User typing whole percentage `4` is converted via `4 / 100 = 0.04` and stored in canonical fraction format in `scanOverrides`. Typing `3` matches `defaultVal` within `1e-6` and deletes the override from `scanOverrides`, reverting cleanly to default.

### 2. Clamping & Boundary Invariants
- **Out-of-Bounds Clamping:** On blur, `minStored` (`0.5 / 100 = 0.005`) and `maxStored` (`100 / 100 = 1.0`) clamp the stored fraction within `[0.005, 1.0]`. Out-of-bounds input (e.g. `150%`) clamps to `1.0` (100%), and input below minimum (e.g. `0.1%`) clamps to `0.005` (0.5%).
- **Backend Contract Alignment:**
  - `backend/app/routers/contracts.py` enforces `Field(default=None, gt=0, le=1.0)`.
  - `backend/app/services/config_loader.py` enforces `_RR_OVERRIDE_CAPS = 1.0` and `0 < val <= 1.0`.
  - `backend/app/scoring/exit_plan.py` computes `price * (1 - invalidation_pct)`.
  - Preventing values $> 1.0$ or $\le 0$ guarantees no 422 validation rejections, no negative stop prices, and prevents accidental 100% stop wipes.

### 3. Persisted Data Integrity & Profile Compatibility
- **Search Profiles Store:** `frontend/lib/searchProfilesStore.ts` and `searchProfileSnapshot.ts` persist `scanOverrides` directly to `localStorage`.
- Because the plan keeps `scanOverrides` stored as canonical decimal fractions (`0.005` to `1.0`), existing persisted profiles (e.g. `{ rr_bullish_invalidation_pct: 0.04 }`) remain completely valid and untouched:
  - Hydration into `scanOverrides` renders as `4%` in Step 3.
  - New profile snapshots save `0.04`.
  - No migration required, avoiding persisted profile corruption.

### 4. Downstream Scan & Execution Payloads
- **Options Scan Request:** `frontend/lib/resolveOptionsScanRequest.ts` passes `scanOverrides` through `scoreOnlyOverrides` into `overrides`, carrying decimal fractions (e.g. `0.04`).
- **Stocks Scan Request:** `frontend/lib/resolveStockScanRequest.ts` filters `STOCKS_SCORER_KEYS` (which includes `rr_bullish_invalidation_pct` and `rr_bearish_invalidation_pct`) and includes them in `overrides: stocksOverrides`.
- **Trade Card / Broker Execution:** `frontend/lib/tradeCardOverride.ts` (`rrOverridesFrom`) extracts `rr_*` keys from `scanOverrides` as numbers and forwards them to `recomputePlan`.
- All downstream consumers receive canonical fractions `(0, 1.0]`.

### 5. Verification Probe Parity
- Checked `PROJECT_STATE.json` defect marker probe:
  - Pattern: `key: .rr_bullish_invalidation_pct..*min: 0\\.005, max: 1\\.0` in `frontend/app/(frame)/screener/step-3-direction/page.tsx`.
  - Updating `min: 0.5, max: 100` satisfies and clears the defect marker probe.

---

GATE FINDINGS: 0
