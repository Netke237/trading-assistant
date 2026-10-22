# Implementation Plan: Stocks Universe Price and Market Cap Filters (#380)

## 1. Problem & Context
During audit of search profile and scan controls (Finding C2 in `docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/controls/findings.md` under #350), it was observed that Stocks manual scans (`stockScan.ts`) and scheduled scans (`scanScheduleResolve.ts`) omit all Step 2 universe price and market cap filters:
- When a user or profile specifies minimum price `0` and minimum market cap `25 M`, the resulting request body omits `min_price` and `min_cap_usd`.
- Expected: `min_price: 0` and `min_cap_usd: 25000000`.
- The backend `StockScanRequest` (`backend/app/schemas/stock_scan.py:46-49`) fully supports `min_price`, `max_price`, `min_cap_usd`, and `max_cap_usd`, and filters candidates accordingly (`backend/app/routers/stock_scan.py:975, 1485`).
- However, `ResolvedStockScanContext` and `StockScanRequestBody` in `frontend/lib/resolveStockScanRequest.ts` lacked these filter fields, and `buildStockScanRequestBody` did not map them.
- Furthermore, `stockScan.ts` (manual scans) and `scanScheduleResolve.ts` (scheduled scans) did not pass these universe filter properties.

## 2. Root Cause & Scope
1. **Schema & Types**:
   - `StockScanRequestBody` is missing `min_price?: number`, `max_price?: number`, `min_cap_usd?: number`, `max_cap_usd?: number`.
   - `ResolvedStockScanContext` is missing `minPriceRaw?: string`, `maxPriceRaw?: string`, `minCapRaw?: string`, `maxCapRaw?: string`, `capUnit?: CapUnit`.
2. **Resolver Logic**:
   - `buildStockScanRequestBody` needs to parse `minPriceRaw`, `maxPriceRaw`, `minCapRaw`, and `maxCapRaw`:
     - Whitespace / empty string / undefined / non-finite inputs must be omitted (the keys must not be present in the returned object).
     - Explicit `0` (e.g. `'0'`, `'0.0'`) must be preserved as numeric `0`.
     - Cap values must be multiplied according to `capUnit`:
       - `capUnit === 'M'` multiplies by `1e6` (e.g., `25 M` -> `25_000_000`).
       - `capUnit === 'B'` (or undefined/default) multiplies by `1e9` (e.g., `2 B` -> `2_000_000_000`).
       - Zero cap (`0 M` or `0 B`) evaluates to `0`.
3. **Call Sites**:
   - `frontend/lib/stockScan.ts`: `runStockScan` must retrieve `minPriceRaw`, `maxPriceRaw`, `minCapRaw`, `maxCapRaw`, and `capUnit` from `useUniverseStore.getState()` and forward them to `buildStockScanRequestBody`.
   - `frontend/lib/scanScheduleResolve.ts`: `resolveProfileToScanRequest` must forward `profile.universe.minPriceRaw`, `maxPriceRaw`, `minCapRaw`, `maxCapRaw`, and `capUnit` to `buildStockScanRequestBody`.
   - `frontend/lib/currentScanReportInputs.ts`: forward `universe.minPriceRaw`, `maxPriceRaw`, `minCapRaw`, `maxCapRaw`, and `capUnit`.
   - `frontend/lib/analysisStore.ts`: read from `useUniverseStore.getState()` and forward to `buildStockScanRequestBody` to ensure consistency.

## 3. Implementation Details

### A. Helper Parsing Logic in `frontend/lib/resolveStockScanRequest.ts`
```ts
function parseFilterNumber(raw?: string): number | undefined {
  if (raw === undefined || raw.trim() === '') return undefined;
  const num = Number(raw);
  return Number.isFinite(num) ? num : undefined;
}
```
Properties:
- `parseFilterNumber(undefined)` -> `undefined`
- `parseFilterNumber('')` -> `undefined`
- `parseFilterNumber('  ')` -> `undefined`
- `parseFilterNumber('0')` -> `0` (preserved)
- `parseFilterNumber('25')` -> `25`
- `parseFilterNumber('abc')` -> `undefined`
- `parseFilterNumber('NaN')` -> `undefined`
- `parseFilterNumber('Infinity')` -> `undefined`

### B. Cap Multiplier & Object Construction
```ts
const minPrice = parseFilterNumber(ctx.minPriceRaw);
const maxPrice = parseFilterNumber(ctx.maxPriceRaw);
const capMultiplier = ctx.capUnit === 'M' ? 1e6 : 1e9;
const minCap = parseFilterNumber(ctx.minCapRaw);
const maxCap = parseFilterNumber(ctx.maxCapRaw);

return {
  ...
  ...(minPrice !== undefined ? { min_price: minPrice } : {}),
  ...(maxPrice !== undefined ? { max_price: maxPrice } : {}),
  ...(minCap !== undefined ? { min_cap_usd: minCap * capMultiplier } : {}),
  ...(maxCap !== undefined ? { max_cap_usd: maxCap * capMultiplier } : {}),
  ...
};
```
Note:
- Using conditional spread ensures that when a filter is absent or unparseable, the key is omitted entirely from the request object (`!('min_price' in body)`), conforming to `source-probe.cjs` line 18: `check('absent filters omitted', false, 'min_price' in a)`.
- When set to `0`, `0 !== undefined` is `true`, so `{ min_price: 0 }` is included.

### C. Updates to Interfaces in `frontend/lib/resolveStockScanRequest.ts`
1. Import `type { CapUnit } from '@/lib/universeStore';`
2. Extend `ResolvedStockScanContext`:
```ts
export interface ResolvedStockScanContext {
  ...
  minPriceRaw?: string;
  maxPriceRaw?: string;
  minCapRaw?: string;
  maxCapRaw?: string;
  capUnit?: CapUnit;
}
```
3. Extend `StockScanRequestBody`:
```ts
export interface StockScanRequestBody {
  ...
  min_price?: number;
  max_price?: number;
  min_cap_usd?: number;
  max_cap_usd?: number;
}
```

### D. Wiring Call Sites
1. `frontend/lib/stockScan.ts`:
   In `runStockScan`:
   ```ts
   const uStore = useUniverseStore.getState();
   const requestBody = buildStockScanRequestBody({
     ...
     minPriceRaw: uStore.minPriceRaw,
     maxPriceRaw: uStore.maxPriceRaw,
     minCapRaw: uStore.minCapRaw,
     maxCapRaw: uStore.maxCapRaw,
     capUnit: uStore.capUnit,
   });
   ```
2. `frontend/lib/scanScheduleResolve.ts`:
   In `resolveProfileToScanRequest` (stocks mode):
   ```ts
   return buildStockScanRequestBody({
     ...
     minPriceRaw: profile.universe.minPriceRaw,
     maxPriceRaw: profile.universe.maxPriceRaw,
     minCapRaw: profile.universe.minCapRaw,
     maxCapRaw: profile.universe.maxCapRaw,
     capUnit: profile.universe.capUnit,
   });
   ```
3. `frontend/lib/currentScanReportInputs.ts`:
   ```ts
   minPriceRaw: universe.minPriceRaw,
   maxPriceRaw: universe.maxPriceRaw,
   minCapRaw: universe.minCapRaw,
   maxCapRaw: universe.maxCapRaw,
   capUnit: universe.capUnit,
   ```
4. `frontend/lib/analysisStore.ts`:
   ```ts
   const u = useUniverseStore.getState();
   ...
   minPriceRaw: u.minPriceRaw,
   maxPriceRaw: u.maxPriceRaw,
   minCapRaw: u.minCapRaw,
   maxCapRaw: u.maxCapRaw,
   capUnit: u.capUnit,
   ```

## 4. Test Strategy
1. **Unit Tests (`frontend/lib/__tests__/resolveStockScanRequest.filters.test.ts`)**:
   - `buildStockScanRequestBody` omits all 4 filter keys when inputs are empty strings or undefined.
   - `min_price: 0` is preserved when `minPriceRaw: '0'`.
   - `max_price: 150.5` is preserved when `maxPriceRaw: '150.5'`.
   - `min_cap_usd: 25000000` is computed when `minCapRaw: '25'` and `capUnit: 'M'`.
   - `max_cap_usd: 50000000` is computed when `maxCapRaw: '50'` and `capUnit: 'M'`.
   - `min_cap_usd: 2000000000` is computed when `minCapRaw: '2'` and `capUnit: 'B'`.
   - `min_cap_usd: 0` is computed when `minCapRaw: '0'` with either 'M' or 'B'.
   - Non-numeric strings (`'abc'`, `'NaN'`, `'Infinity'`) are omitted.
   - Default capUnit when undefined defaults to `'B'` (1e9 multiplier).
2. **Integration / Consumer Tests**:
   - Verify `resolveProfileToScanRequest` with stocks profile passes price/cap filters accurately.
   - Verify `runStockScanWithContinuation` reads from `useUniverseStore` and posts price/cap filters.
3. **Full Suite & Typecheck**:
   - `npm run typecheck`
   - `npm test`
   - `python scripts/state.py`

## 5. Adversarial Audit Gate
The numeric/persistence gate criteria:
- Does this put a wrong number in front of the user or on a broker order? No, correctly propagates configured price/cap thresholds in USD.
- Does this corrupt persisted data? No, read-only extraction and pure request building.
- Does this preserve explicit 0? Yes, `parseFilterNumber` explicitly allows `0`.
- Does this omit keys when absent? Yes, conditional spread prevents emitting `undefined` values that fail `'key' in obj` checks.
