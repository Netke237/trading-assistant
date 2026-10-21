# Audit Report: STOCKS-CUSTOM-UNIVERSE Plan Round 1

Conducted independent adversarial audit under the `bmad-review-adversarial-general` skill by subagent `0a76948a-039f-47b5-8944-b6023fbed04a` against Issue #343 ("Stocks scan ignores current Custom universe and reuses stale scan context").

## Findings

### F-1: Custom symbols change within 'Custom' universe does not invalidate stale scan results
- **Location**: `docs/superpowers/plans/2026-10-21-stocks-custom-universe-plan.md:85-90` (Section 3.D.1)
- **Failing Scenario**:
  1. User selects `Custom` on Step 2 with symbols `MKC, KEY, EMN` and runs stock scan. `stockScanResult` holds candidates for `MKC, KEY, EMN`.
  2. User navigates back to Step 2 to edit custom symbols to `TSLA, NVDA`. Because the active pick is already `Custom`, editing `<textarea>` invokes `setCustomRaw(...)` rather than `handleSelectPick`.
  3. Even if `handleSelectPick('Custom')` were triggered, `context.universe` is already `'Custom'`, so `context.universe !== key` evaluates to `false` and `setContext` is not called.
  4. Even if `setContext` was called with `'Custom'`, `scanStore.ts:491` checks `prev.universe !== c.universe` ('Custom' !== 'Custom' is false), so `stockScanResult` is never cleared.
  5. Step 4 caption shows `TSLA, NVDA`, but `stockScanResult` still has results for `MKC, KEY, EMN`.
  6. Step 6 displays backtest metrics for `MKC, KEY, EMN` (WRONG NUMBERS), and Step 7 allows broker order submission for `MKC, KEY, EMN` (WRONG BROKER ORDER).
- **Resolution**:
  - Add `clearScanResults` action to `scanStore.ts` that clears `previousRun`, `previousStockScanResult`, `scanResult`, `stockScanResult`, `stockScanRequest`, `stockScanAt`, `optionsScanAt`, `rejectedLog`, and `conflictedSymbols`.
  - When `customRaw` changes while `pick === 'Custom'`, call `clearScanResults()` so modifying custom tickers immediately wipes obsolete results.

### F-2: Passive sync on Step 3 mount overwrites persisted context.universe with unpersisted universeStore default
- **Location**: `docs/superpowers/plans/2026-10-21-stocks-custom-universe-plan.md:97-99` (Section 3.E.2) & Section 2
- **Failing Scenario**:
  1. User runs scan on universe `NDX100`. `scanStore` persists `context.universe = 'NDX100'` and `stockScanResult` in `bamendjou-scan-store`.
  2. User refreshes or reloads page.
  3. `scanStore` rehydrates `context.universe = 'NDX100'` and `stockScanResult`.
  4. `universeStore` is unpersisted (`create<UniverseState>` without `persist`) and initializes on load with default `pick: 'SP500'`.
  5. If Step 3 on mount checks `context.universe !== useUniverseStore.getState().pick` ('NDX100' !== 'SP500') and passively calls `setContext({ ...context, universe: 'SP500' })`:
  6. `scanStore.ts:491` evaluates `prev.universe !== c.universe` ('NDX100' !== 'SP500') as true and wipes `stockScanResult: null`, `scanResult: null`, etc.
  7. Persisted scan results are destroyed merely by visiting Step 3 on page reload without user interaction.
- **Resolution**:
  - Remove passive synchronization on Step 3 mount.
  - On Step 2 mount, seed `universeStore.pick` from hydrated `context.universe` (if valid) so the unpersisted UI store reflects the persisted selection.
  - Update `context.universe` only on explicit user actions:
    - Step 2 card click: `handleSelectPick(key)` calls `setContext({ ...context, universe: key })`.
    - Step 3 control change: `syncToStore` reads `useUniverseStore.getState().pick`.
