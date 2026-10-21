# Audit Report: STOCKS-CUSTOM-UNIVERSE Plan Round 2

Conducted independent adversarial audit under the `bmad-review-adversarial-general` skill by subagent `5bc76eba-2e03-487e-ba73-746c71f0d688` against Issue #343 ("Stocks scan ignores current Custom universe and reuses stale scan context").

## Findings

### F2-1: Seeding `universeStore.pick` solely on Step 2 mount leaves `universeStore.pick` unseeded on reload of Steps 3/4/6/7
- **Location**: `docs/superpowers/plans/2026-10-21-stocks-custom-universe-plan.md:107-108, 124-125` (Section 3.E.1, Section 3.F.1)
- **Failing Scenario**:
  1. User selects `NDX100` on Step 2 and runs stock scan. `context.universe: 'NDX100'` and `stockScanResult` are persisted in localStorage.
  2. User reloads on `/screener/step-3-direction` or `/screener/step-4-stocks`. Next.js mounts active route; `Step2Page` never mounts.
  3. `universeStore` initializes with unpersisted default `pick: 'SP500'`.
  4. On Step 3: Any adjustment invokes `syncToStore`, which writes `universe: useUniverseStore.getState().pick` ('SP500'). `scanStore.ts:491` sees `'NDX100' !== 'SP500'`, wiping `stockScanResult` and corrupting `context.universe` to `'SP500'`.
  5. On Step 4: Header renders `SP500` caption. Clicking "Run Stock Scan" resolves `uStore.pick` ('SP500'), scanning 500 stocks instead of 100, generating wrong candidates, scores, and broker orders.
- **Resolution**:
  - Seed `universeStore.pick` from `context.universe` in `StoreHydration` (`frontend/components/StoreHydration/index.tsx`) and `ScreenerLayout` (`frontend/app/(frame)/screener/layout.tsx`) upon hydration, ensuring `universeStore.pick` matches `context.universe` on reload regardless of which step route the user lands on.
  - In Step 3's `syncToStore`, preserve `universe: context?.universe ?? useUniverseStore.getState().pick ?? 'SP500'`.

### F2-2: Limiting stale result invalidation to textarea `onChange` misses CSV upload and chip removal in Step 2
- **Location**: `docs/superpowers/plans/2026-10-21-stocks-custom-universe-plan.md:115-118` (Section 3.E.3)
- **Failing Scenario**:
  1. In Step 2 (`step-2-universe/page.tsx`), custom symbols are mutated in three places:
     - textarea `onChange` (line 527)
     - CSV upload `onChange` (line 550)
     - Ticker chip removal "×" `onClick` (line 581)
  2. If `clearScanResults()` is only attached to textarea `onChange`, removing a symbol via chip removal or CSV upload does not trigger invalidation.
  3. Obsolete candidates for removed symbols remain in `stockScanResult` and can be traded on Step 7 (WRONG BROKER ORDER).
- **Resolution**:
  - Create a unified `updateCustomRaw(val: string)` helper in `step-2-universe/page.tsx` that calls `setCustomRaw(val)` and invokes `useScanStore.getState().clearScanResults()` when `pick === 'Custom'` and scan results exist.
  - Route all three mutation paths (textarea, CSV upload, chip remove) through `updateCustomRaw`.
