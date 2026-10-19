# Plan Audit (Round 1) — APP-AUDIT-B-THEME-SYNC (#399)

- **Date**: 2026-10-19
- **Reviewer**: Fresh independent gate auditor `a1296fd7-ce3f-47a2-8cf4-4628bfb68bfe` (Plan Audit Round 1)
- **Reviewed Target**: `docs/superpowers/plans/2026-10-19-app-audit-b-theme-sync-plan.md`
- **Gate Floor**: Numeric / persistence gate (wrong numbers in front of user/order, corrupted persisted data)
- **Gate Findings**: **0 (Clean at the Gate)**
- **Architectural Findings / Pre-Implementation Notes**: **1 (Implementation recommendation reconciling line 37 and line 85)**
- **Exact Verdict**: **CLEAN**

---

### Gate Assessment

Under the repository numeric and persistence gate definition:
> "THE GATE IS THE ONLY THING THAT COUNTS. A finding blocks only if it can put a WRONG NUMBER in front of a user or on a broker order, or CORRUPT PERSISTED DATA. Everything else -- wording, comments, test hygiene, dead code, stale records, latent defects with no reachable path -- is not a finding for this purpose..."

- **Numeric Integrity**: Theme switching operates on `'light' | 'dark'`. It does not calculate, touch, or format any financial numerical figures, strike prices, Greeks, order quantities, or stop levels.
- **Persistence Integrity**: Theme storage is isolated strictly to `'bamendjou:theme'` managed via Zustand's `persist` middleware. The plan only touches `frontend/lib/theme.ts` and `frontend/components/ThemeProvider/index.tsx`. It does not touch or mutate any other store or persisted database/browser state.
- **Gate Findings**: **0**

---

### Edge Case Evaluation

1. **Infinite Loop Prevention**:
   - Web Storage specification dictates that `StorageEvent` is only dispatched to other windows/tabs sharing the origin, never to the window initiating `localStorage.setItem`.
   - When Tab B receives the `storage` event and updates its store via `useThemeStore.setState({ theme: target })`, Tab A receives a subsequent event.
   - In Tab A, `useThemeStore.getState().theme === target` evaluates to `true`, so `currentTheme !== target` evaluates to `false`.
   - Tab A performs zero state mutations and does not write to `localStorage`. The chain cleanly and deterministically terminates in 1 hop.
2. **`StorageEvent.key === null` (`localStorage.clear()`)**:
   - Handled cleanly via `event.key === THEME_STORAGE_KEY || event.key === null`.
   - When `value === null` (cleared or deleted), resets to default `'dark'`, aligning with initial store state and design token baseline.
3. **Corrupted JSON & Invalid Theme Strings (Pre-Implementation Recommendation)**:
   - `parseTheme` uses `try / catch` and validates `parsed?.state?.theme === 'light' || parsed?.state?.theme === 'dark'`. Returns `null` on corrupt JSON or unknown theme strings.
   - In `syncThemeFromStorage`, distinguish between `value === null` (storage cleared/removed -> reset to `'dark'`) and `value !== null && parseTheme(value) === null` (corrupted JSON -> ignore and keep current state):
     ```ts
     export function syncThemeFromStorage(raw?: string | null): void {
       if (typeof window === 'undefined') return;
       const value = raw !== undefined ? raw : localStorage.getItem(THEME_STORAGE_KEY);
       if (value === null) {
         if (useThemeStore.getState().theme !== 'dark') {
           useThemeStore.setState({ theme: 'dark' });
         }
         return;
       }
       const parsed = parseTheme(value);
       if (parsed && useThemeStore.getState().theme !== parsed) {
         useThemeStore.setState({ theme: parsed });
       }
     }
     ```
4. **SSR Safety**:
   - `syncThemeFromStorage` has `if (typeof window === 'undefined') return;`.
   - `ThemeProvider` is marked `'use client'` and registers the listener inside `useEffect` (browser client-mount only).
5. **Preservation of `noFlashScript` in `frontend/app/layout.tsx`**:
   - `noFlashScript` reads `localStorage.getItem('bamendjou:theme')` and parses `parsed.state.theme`.
   - The plan preserves the key name and `{ state: { theme: ... } }` schema. `app/layout.tsx` is untouched and preserved.
6. **Preservation of `StoreHydration`**:
   - `StoreHydration` calls `useThemeStore.persist.rehydrate()` on initial mount. This remains untouched and functions identically on page reload and browser process restart.
7. **Architectural Constraints**:
   - `theme.ts` is in `lib/`, so Next.js 15 App Router page export constraints do not apply to exported helper functions. Typecheck and imports are fully compliant.

---

### Audit Verdict
**CLEAN (0 gate-blocking findings). Ready to proceed to implementation.**
