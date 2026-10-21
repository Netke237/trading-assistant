# Implementation Plan: Stocks Custom Universe Resolution and Stale Scan Context Invalidation (#343)

## 1. Problem Statement & Baseline Evidence
In Stocks mode, scans resolve the scan universe from `scanStore.context.universe` (or fall back to `['SP500']`), ignoring the user's Step 2 `useUniverseStore` selection (`pick`, `customRaw`, and `useWatchlistStore.added`):
- When a user selects `Custom` on Step 2 with symbols (e.g. `MKC, KEY, EMN`), `frontend/lib/stockScan.ts:339-340` ignores `universeStore.pick` and `universeStore.customRaw`, sending `universe: context?.universe ? [context.universe] : ['SP500']`.
- If `context?.universe` has a stale value (e.g. `'SP500'`), it scans the full 500-symbol S&P 500 universe instead of the 3 custom tickers.
- Even if `context?.universe` were `'Custom'`, sending `['Custom']` to the backend causes `expand_universe(['Custom'])` to treat `'Custom'` as a single non-existent ticker, resulting in zero results or scan errors.
- `frontend/app/(frame)/screener/step-4-stocks/page.tsx:259` displays `Scanning full {context?.universe ?? 'SP500'} universe for stock setups`, misleading the user about the scan scope.
- `frontend/app/(frame)/screener/step-4-stocks/HistoryPrefetchRow.tsx:34` also resolves `context?.universe ? [context.universe] : ['SP500']`.
- `frontend/lib/currentScanReportInputs.ts:29` hardcodes `universe: [context?.universe ?? 'SP500']` for stocks, unlike the options category which parses symbols from `universeStore`.
- `frontend/app/(frame)/screener/step-3-direction/page.tsx:697` in `syncToStore` preserves `universe: context?.universe ?? 'SP500'` rather than reading `useUniverseStore.getState().pick`.
- `frontend/components/organisms/RunScanButton/index.tsx` checks `customEmpty` in the UI but does not guard stocks mode against an empty universe prior to execution.

## 2. Gate Criteria & Constraints
- **Gate:** Report/address ONLY findings that can put a WRONG NUMBER in front of a user or on a broker order, or CORRUPT PERSISTED DATA.
  - Wrong tickers scanned = wrong candidates/scores/orders.
  - Sending `['Custom']` or `[]` to the backend causes scan failure or wrong scan scope.
  - Persisted stores (`scanStore`) must not undergo breaking migrations; migration rules must be strictly preserved.
  - Note: `universeStore` is an unpersisted session store (`create<UniverseState>` without `persist`), whereas `scanStore` is persisted in `bamendjou-scan-store` (`version: 19`). Unpersisted store state must NEVER passively overwrite persisted state on mount (Fix for F-2 and F2-1).
- **Self-Merge Conditions:** Follow all 5 self-merge conditions from `docs/agents/board.md`.

## 3. Architecture & Design

### A. Canonical Universe Resolution Module (`frontend/lib/universeResolution.ts`)
Create a single pure module to eliminate duplicated parsing, formatting, and resolution logic across the codebase:
- `parseSymbols(raw: string): string[]`: canonical ticker parser using regex `/^[A-Z][A-Z0-9.\-]{0,5}$/`.
- `SECTOR_LABELS: Record<string, string>`: human-readable labels for `SECTOR:XLK` -> `Technology`, `SP500` -> `S&P 500`, etc.
- `isValidUniverse(val: string): boolean`: returns true if `val` is a recognized `Universe` key (`SP500`, `NDX100`, `DOW30`, `SPY`, `Watchlist`, `Custom`, or `SECTOR:XL*`).
- `universeDisplayName(pick: string): string`: returns friendly name or fallback to raw string.
- `resolveUniverseSymbols(pick: Universe | string, customRaw: string, watchlistSymbols: string[] = []): string[]`:
  - `pick === 'Custom'`: `parseSymbols(customRaw)`
  - `pick === 'Watchlist'`: `Array.from(new Set(watchlistSymbols.map(s => s.trim().toUpperCase()).filter(s => /^[A-Z][A-Z0-9.\-]{0,5}$/.test(s))))`
  - Otherwise: `[pick]`
- `isUniverseEmpty(pick: Universe | string, customRaw: string, watchlistCount: number): boolean`:
  - Returns `true` if `pick === 'Custom'` and `parseSymbols(customRaw).length === 0`.
  - Returns `true` if `pick === 'Watchlist'` and `watchlistCount === 0`.
  - Returns `false` otherwise.
- `universeEmptyReason(pick: Universe | string): string`:
  - `pick === 'Custom'`: `'Custom universe is empty — enter symbols in Step 2 (Universe)'`
  - `pick === 'Watchlist'`: `'Watchlist is empty — star symbols before scanning'`
  - Otherwise: `'Universe is empty'`
- `universeCaption(pick: Universe | string, customRaw: string, watchlistCount: number, customSymbolsList?: string[]): string`:
  - For `Custom`:
    - If empty: `'Custom universe is empty — add symbols in Step 2 (Universe)'`
    - If symbols present: `Scanning ${N} custom ${N === 1 ? 'symbol' : 'symbols'} (${sample}) for stock setups`
  - For `Watchlist`:
    - If empty: `'Watchlist is empty — star symbols before scanning'`
    - If symbols present: `Scanning ${N} watchlist ${N === 1 ? 'symbol' : 'symbols'} for stock setups`
  - For Sector (`SECTOR:XL*`):
    - `Scanning ${name} sector (S&P 500) for stock setups`
  - For Presets (`SP500`, `NDX100`, `DOW30`, `SPY`):
    - `Scanning full ${name} universe for stock setups`

### B. Stale Result Invalidation in `scanStore.ts` (Fix for F-1 and F2-2)
Add an explicit action to `scanStore.ts`:
```ts
clearScanResults: () => void;
```
Implementation clears all scan results and candidate artifacts without resetting user configuration:
```ts
clearScanResults: () => set({
  previousRun: null,
  previousStockScanResult: null,
  scanResult: null,
  stockScanResult: null,
  stockScanRequest: null,
  stockScanAt: null,
  optionsScanAt: null,
  rejectedLog: [],
  conflictedSymbols: [],
}),
```

### C. Universal Hydration Seeding for `universeStore.pick` (Fix for F2-1)
To ensure `universeStore.pick` is always initialized from persisted `context.universe` on page reload regardless of which step route the user lands on:
1. In `StoreHydration` (`frontend/components/StoreHydration/index.tsx`) and `ScreenerLayout` (`frontend/app/(frame)/screener/layout.tsx`):
   When `scanStore` rehydrates:
   ```ts
   const ctxUniverse = useScanStore.getState().context?.universe;
   if (ctxUniverse && isValidUniverse(ctxUniverse)) {
     useUniverseStore.getState().setPick(ctxUniverse as Universe);
   }
   ```
2. In `step-3-direction/page.tsx`:
   `syncToStore(newDir, newHz, newMin, newMax)` sets:
   ```ts
   universe: context?.universe ?? useUniverseStore.getState().pick ?? 'SP500',
   ```
   This ensures that Step 3 adjustments preserve the persisted/selected universe rather than overwriting it with unseeded store defaults.

### D. Request Building in `frontend/lib/stockScan.ts`
In `runStockScan()`:
1. Resolve symbols using `resolveUniverseSymbols`:
   ```ts
   const uStore = useUniverseStore.getState();
   const watch = useWatchlistStore.getState();
   // Priority: if context has a valid universe, use that pick; fallback to uStore.pick
   const activePick = context?.universe ?? uStore.pick;
   const universeSymbols = resolveUniverseSymbols(activePick, uStore.customRaw, watch.added);
   ```
2. Guard against empty universe:
   If `universeSymbols.length === 0`:
   Fail fast without issuing a backend request:
   ```ts
   const reason = universeEmptyReason(activePick);
   store.setStockScanError(reason);
   store.setScanState('FAILED');
   return { kind: 'failure', reason, token };
   ```
3. Pass `universe: universeSymbols` into `buildStockScanRequestBody`.

### E. Step 4 Strategy Page (`frontend/app/(frame)/screener/step-4-stocks/page.tsx`)
1. Read active pick (`context?.universe ?? uStore.pick`), `uStore.customRaw`, and `useWatchlistStore.added.length`.
2. Compute `caption = universeCaption(activePick, customRaw, watchlistCount, symbols)`.
3. Compute `isEmpty = isUniverseEmpty(activePick, customRaw, watchlistCount)`.
4. Render `caption` in the step header (`<Text size={12} tone={isEmpty ? "caution" : "secondary"}>{caption}</Text>`).
5. In `aside className={styles.side}`:
   Disable `runBtn` when `isEmpty`:
   ```tsx
   disabled={!activeStrategy || scanning || isEmpty || ...}
   title={isEmpty ? universeEmptyReason(activePick) : ...}
   ```
6. In `onRun`:
   If `isEmpty`, do not dispatch; display toast or set scan error with `universeEmptyReason(activePick)`.

### F. Step 2 Universe Page (`frontend/app/(frame)/screener/step-2-universe/page.tsx`)
1. **Explicit Card Selection**:
   In `handleSelectPick(key: Universe)`:
   - Call `setPick(key)`.
   - If `scanStore.context` exists and `context.universe !== key`:
     Update `scanStore.setContext({ ...context, universe: key })`.
     This activates `scanStore.ts:491` (`prev.universe !== c.universe`), which automatically clears stale `scanResult` and `stockScanResult` so old candidates never linger.
2. **Unified Custom Symbols Mutation (Fix for F-1 & F2-2)**:
   Define a unified mutation helper:
   ```ts
   const updateCustomRaw = useCallback((newRaw: string) => {
     setCustomRaw(newRaw);
     if (pick === 'Custom' && (useScanStore.getState().stockScanResult || useScanStore.getState().scanResult)) {
       useScanStore.getState().clearScanResults();
     }
   }, [setCustomRaw, pick]);
   ```
   Route ALL three custom symbol mutation points through `updateCustomRaw`:
   - Textarea input (`onChange={(e) => updateCustomRaw(e.target.value)}`)
   - CSV upload completion (`updateCustomRaw(unique.join(' '))`)
   - Chip removal click (`updateCustomRaw(symbols.filter((x) => x !== s).join(' '))`)
3. **History Pre-warm**:
   In `handleLoadHistory`:
   Use `resolveUniverseSymbols(pick, customRaw, useWatchlistStore.getState().added)` so pre-warming history for Watchlist and Custom works accurately.

### G. RunScanButton (`frontend/components/organisms/RunScanButton/index.tsx`)
1. Read active pick (`context?.universe ?? pick`).
2. Compute `watchlistCount = useWatchlistStore((s) => s.added.length)`.
3. Compute `isEmpty = isUniverseEmpty(activePick, customRaw, watchlistCount)`.
4. Disable button when `isEmpty && screenerMode !== 'prebreakout'`.
5. In `onClick`, check `isEmpty` for all non-prebreakout modes before initiating scan, dispatching a failure toast with `universeEmptyReason(activePick)` if triggered.

### H. HistoryPrefetchRow (`frontend/app/(frame)/screener/step-4-stocks/HistoryPrefetchRow.tsx`)
1. Replace `context?.universe ? [context.universe] : ['SP500']` with `resolveUniverseSymbols(context?.universe ?? uStore.pick, uStore.customRaw, useWatchlistStore.getState().added)`.
2. If resolved list is empty, disallow prefetch start.

### I. Current Scan Report Inputs (`frontend/lib/currentScanReportInputs.ts`)
1. Replace hardcoded `[context?.universe ?? 'SP500']` in stocks category with `resolveUniverseSymbols(context?.universe ?? universe.pick, universe.customRaw, watch.added)`.

## 4. Test Strategy
1. **Unit Tests for Canonical Universe Resolution:**
   `frontend/lib/__tests__/universeResolution.test.ts`:
   - `parseSymbols`: whitespace, commas, mixed punctuation, lowercase to uppercase, valid symbol regex, deduping, invalid symbol filtering.
   - `resolveUniverseSymbols`:
     - `'Custom'` with `'MKC, KEY, EMN'` -> `['MKC', 'KEY', 'EMN']`.
     - `'Custom'` with empty string -> `[]`.
     - `'Watchlist'` with `['AAPL', 'MSFT']` -> `['AAPL', 'MSFT']`.
     - `'Watchlist'` with empty list -> `[]`.
     - `'SP500'` -> `['SP500']`.
     - `'NDX100'` -> `['NDX100']`.
     - `'SECTOR:XLK'` -> `['SECTOR:XLK']`.
   - `isValidUniverse`: verify recognition of all preset/sector/custom/watchlist keys.
   - `universeDisplayName`: verify sector names and index names.
   - `universeCaption`: verify strings for presets, sectors, custom (sampled tickers), watchlist, and empty states.
2. **Integration & Regression Tests:**
   `frontend/app/(frame)/screener/step-4-stocks/__tests__/customUniverseScan.test.tsx`:
   - Switching from a prior SP500 context to Custom (with 3 symbols: `MKC, KEY, EMN`) sends `universe: ['MKC', 'KEY', 'EMN']` to `api.postStockScan`.
   - Step 4 header renders `Scanning 3 custom symbols (MKC, KEY, EMN) for stock setups`.
   - Modifying custom symbols in Step 2 via textarea, CSV upload, or chip removal while `pick === 'Custom'` invalidates previous scan results (Fix for F-1 & F2-2).
   - Reload / remount on Step 3 or Step 4 seeds `universeStore.pick` from persisted `context.universe` and does not wipe scan results or corrupt `context.universe` (Fix for F-2 & F2-1).
   - Switching from Custom to NDX100 sends `universe: ['NDX100']` and header renders `Scanning full Nasdaq 100 universe for stock setups`.
   - Switching to Watchlist with 2 starred symbols sends those 2 symbols.
   - Empty Custom universe disables the run button and displays caution caption `Custom universe is empty — add symbols in Step 2 (Universe)`.
   - Verify `api.postStockScan` is never called when custom universe is empty.
3. **Existing Test Suite Verification:**
   - Run `npm --prefix frontend test` to ensure all existing tests continue to pass.
   - Run `npm --prefix frontend run typecheck` to verify strict TypeScript adherence.
