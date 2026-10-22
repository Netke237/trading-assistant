# Independent Adversarial Audit Report: Code Round 1

**Target:** `APP-AUDIT-B-STOCK-FILTERS` (#380 / remediation from #350 finding C2)  
**Auditor Conversation:** `6301d815-f150-43b6-a55a-a48d0d5b5d49`  
**Reviewed Diff:** `542fceb99a5a3ce19edd4d96ce8a91db6ad201a4..e0a49254`  
**Plan:** `docs/superpowers/plans/2026-10-20-app-audit-b-stock-filters-plan.md`  
**Skill Applied:** `bmad-review-adversarial-general`  
**The Gate:** Blocks ONLY if it can put a WRONG NUMBER in front of a user or on a broker order, or CORRUPT PERSISTED DATA. A comment blocks only if a competent reader acting on it would write a wrong change (misstates mechanism). Wording, test hygiene, dead code, style, illustrative figures, latent defects with no reachable path are not reported.

---

### What Was Checked

1. **Number Parsing & Preservation (`frontend/lib/resolveStockScanRequest.ts:126-130`)**:
   - `parseFilterNumber` correctly handles:
     - Explicit zero (`'0'`, `'0.0'`): returns numeric `0`.
     - Whitespace-only, empty string `''`, and `undefined`: returns `undefined`.
     - Non-finite strings (`'abc'`, `'NaN'`, `'Infinity'`, `'-Infinity'`): returns `undefined`.
     - Decimals (`'10.5'`): preserved accurately as `10.5`.
   - Verified that `parseFilterNumber('   ')` safely trims whitespace before evaluation, avoiding JavaScript's `Number(' ') === 0` coercion pitfall.

2. **Market Cap Scaling & Key Omission (`frontend/lib/resolveStockScanRequest.ts:161-176`)**:
   - Cap multiplier: `ctx.capUnit === 'M' ? 1e6 : 1e9` correctly scales millions (`'25'` with `'M'` → `25_000_000 USD`) and billions (`'2.5'` with `'B'` → `2_500_000_000 USD`), defaulting to `1e9` when `capUnit` is unspecified.
   - Zero cap (`'0'` with `'M'` or `'B'`): evaluates to numeric `0`.
   - Conditional spread (`minPrice !== undefined ? { min_price: minPrice } : {}`):
     - Preserves explicit `0` (`0 !== undefined` is `true`, yielding `{ min_price: 0 }`).
     - Omits absent/empty filters entirely (`undefined !== undefined` is `false`, omitting keys so `'min_price' in body === false`).
   - Field names and types match backend `StockScanRequest` (`backend/app/schemas/stock_scan.py:46-49`) field-for-field (`min_price`, `max_price`, `min_cap_usd`, `max_cap_usd`).

3. **Call Sites & Data Propagation**:
   - `frontend/lib/stockScan.ts:338-361`: `runStockScanWithContinuation` reads `minPriceRaw`, `maxPriceRaw`, `minCapRaw`, `maxCapRaw`, and `capUnit` from `useUniverseStore.getState()` at scan execution time and passes them into `buildStockScanRequestBody`.
   - `frontend/lib/scanScheduleResolve.ts:136-140`: `resolveProfileToScanRequest` forwards all five filter fields from `profile.universe` to `buildStockScanRequestBody`, matching options profile resolution behavior.
   - `frontend/lib/currentScanReportInputs.ts:29`: forwards all five filter fields from `useUniverseStore` when building inputs for `category === 'stocks'`.
   - `frontend/lib/analysisStore.ts:66-70`: `analysisRequestFor` forwards all five filter fields from `useUniverseStore.getState()` when falling back to `current-settings` basis, and preserves them when reading from prior scan snapshot (`last-scan` basis).

4. **Safety & Invariants**:
   - Order execution / sizing: `accountSize` and `riskPct` computation in `scanSizingFromRisk()` is completely untouched. No broker order numbers or quantities are altered.
   - Persistence: No database or localStorage migrations or store shape mutations. `useUniverseStore` remains in-memory.
   - Backend compatibility: Validated against `StockScanRequest` and `StockAnalysisRequest` schema definitions; `min_price` and `max_price` are correctly consumed by candidate filtering in `backend/app/routers/stock_scan.py:975-978, 1485-1490`.

5. **Runtime & Static Verification**:
   - `npm run typecheck` passes with zero errors.
   - Jest test suite (`npm run test -- --testPathPattern="resolveStockScanRequest|scanScheduleResolve|stockScan|currentScanReportInputs|analysisStore"`): 9 suites, 99 tests passed cleanly.
   - `python scripts/state.py`: probe verified, 0 drift.

---

### Findings

None. All checks passed the numeric and persistence gate.

---

GATE FINDINGS: 0
