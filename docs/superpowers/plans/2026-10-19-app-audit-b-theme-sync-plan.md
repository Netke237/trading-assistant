# APP-AUDIT-B-THEME-SYNC — Theme changes synchronize across tabs in ThemeProvider (#399)

Part of #350 · programme #348. Separate remediation phase; audit defect remediation below the numeric gate.

## Goal

Ensure theme changes made in one browser tab synchronize to other same-origin tabs via the native window `storage` event, fulfilling the explicit UI promise at `frontend/app/(frame)/settings/page.tsx:224`:
`hint="Persisted in localStorage; synced across tabs"`.

## Mechanism

### Problem Analysis
1. In `frontend/lib/theme.ts`:
   - `useThemeStore` is defined with Zustand `persist` using key `THEME_STORAGE_KEY = 'bamendjou:theme'`.
   - It sets `skipHydration: true` and uses `createJSONStorage(() => localStorage)`.
   - `StoreHydration` (`frontend/components/StoreHydration/index.tsx`) calls `useThemeStore.persist.rehydrate()` on initial mount, ensuring page reloads and process restarts restore the saved theme.
2. In `frontend/components/ThemeProvider/index.tsx`:
   - `ThemeProvider` observes `const theme = useThemeStore((s) => s.theme)`.
   - An effect synchronizes `document.documentElement.dataset.theme = theme`.
3. The Breakdown Across Tabs:
   - When Tab A toggles or sets the theme, Tab A's store updates and Zustand `persist` writes to `localStorage.setItem('bamendjou:theme', ...)`.
   - The browser dispatches a native `StorageEvent` to all other same-origin tabs (Tab B, Tab C, etc.).
   - Neither `useThemeStore` nor `ThemeProvider` registers a `'storage'` event listener on `window`.
   - Consequently, Tab B never updates its in-memory store, `ThemeProvider` in Tab B does not run its effect, and `document.documentElement.dataset.theme` remains stale (e.g. `"light"` when Tab A switched to `"dark"`).

### Proposed Repair

#### 1. In `frontend/lib/theme.ts`:
Define and export helper functions for parsing and syncing theme state:
- `parseTheme(raw: string | null | undefined): Theme | null`:
  - Parses JSON safely (wrapped in try/catch).
  - Validates `parsed?.state?.theme === 'light' || parsed?.state?.theme === 'dark'`.
  - Returns the validated `Theme`, or `null` if invalid, malformed, or missing.
- `syncThemeFromStorage(raw?: string | null): void`:
  - If `typeof window === 'undefined'`, returns immediately (SSR safety).
  - Resolves raw storage string: uses provided `raw` if not undefined, else reads `localStorage.getItem(THEME_STORAGE_KEY)`.
  - Determines target theme: `parseTheme(value) ?? 'dark'`.
  - If current `useThemeStore.getState().theme !== target`, updates store via `useThemeStore.setState({ theme: target })`.
  - Setting state updates the store in memory, which triggers `ThemeProvider`'s existing effect to update `document.documentElement.dataset.theme`.

#### 2. In `frontend/components/ThemeProvider/index.tsx`:
Add an effect in `ThemeProvider` to listen for cross-tab storage events:
```tsx
useEffect(() => {
  const handleStorage = (event: StorageEvent) => {
    // StorageEvent.key is null when localStorage.clear() is invoked
    if (event.key === THEME_STORAGE_KEY || event.key === null) {
      syncThemeFromStorage(event.newValue);
    }
  };
  window.addEventListener('storage', handleStorage);
  return () => window.removeEventListener('storage', handleStorage);
}, []);
```
Because `ThemeProvider` is mounted in `RootLayout` (`frontend/app/layout.tsx`), it persists across all routes in the application, ensuring every tab stays synchronized regardless of which page is open.

#### 3. Cross-Tab Loop Prevention & Idempotency:
- When Tab B receives the `storage` event from Tab A, Tab B's `syncThemeFromStorage` checks `if (currentTheme !== target)`.
- If identical, it does nothing.
- If changed, Tab B's `useThemeStore.setState({ theme: target })` will write `target` to `localStorage`.
- By web standards, a tab never receives a `storage` event for its own `localStorage` mutations.
- If Tab A receives any event, Tab A already has `theme === target`, so `currentTheme !== target` evaluates to `false` and exits immediately with zero state mutation or re-renders.

#### 4. Settings Page UI Alignment:
- In `frontend/app/(frame)/settings/page.tsx:224`:
  `<Row label="Theme" hint="Persisted in localStorage; synced across tabs" defaultValue="Dark">`
  The explicit hint is completely fulfilled by this implementation.

## Task 1 — Failing Regression Tests

Create test suites covering unit parsing, store synchronization, and cross-tab UI event propagation:

1. **Unit tests in `frontend/lib/__tests__/theme.test.ts`**:
   - `parseTheme`:
     - Parses valid `{ state: { theme: 'light' } }` -> `'light'`.
     - Parses valid `{ state: { theme: 'dark' } }` -> `'dark'`.
     - Returns `null` on invalid JSON (e.g. `"{invalid"`).
     - Returns `null` on null / undefined / empty string.
     - Returns `null` on unsupported theme values (e.g. `{ state: { theme: 'solarized' } }`).
     - Returns `null` when `state` or `theme` property is missing.
   - `syncThemeFromStorage`:
     - Updates store to `'light'` when receiving raw serialized light state.
     - Updates store to `'dark'` when receiving raw serialized dark state.
     - Resets to default `'dark'` when raw string is `null` (e.g. key removed or storage cleared).
     - Ignores corrupted JSON without throwing or altering current state.
     - No-op when target theme already matches current store theme.

2. **Integration / UI tests in `frontend/components/ThemeProvider/__tests__/ThemeProvider.test.tsx`**:
   - Initial rendering:
     - Sets `document.documentElement.dataset.theme` to current store theme.
   - Cross-tab `storage` event handling:
     - Dispatches `StorageEvent` for `THEME_STORAGE_KEY` with new value `"light"`:
       - Verifies `useThemeStore.getState().theme` updates to `"light"`.
       - Verifies `document.documentElement.dataset.theme` updates to `"light"`.
     - Dispatches `StorageEvent` for `THEME_STORAGE_KEY` with new value `"dark"`:
       - Verifies `useThemeStore.getState().theme` updates to `"dark"`.
       - Verifies `document.documentElement.dataset.theme` updates to `"dark"`.
     - Dispatches `StorageEvent` with `key: null` (`localStorage.clear()`):
       - Verifies store and DOM reset to default `"dark"`.
     - Dispatches `StorageEvent` for unrelated key (e.g. `"bamendjou:alerts"`):
       - Verifies theme remains unchanged.
   - Cleanup:
     - Unmounting `ThemeProvider` removes the `storage` event listener from `window`.

## Task 2 — Implementation

1. In `frontend/lib/theme.ts`:
   - Implement and export `parseTheme`.
   - Implement and export `syncThemeFromStorage`.
2. In `frontend/components/ThemeProvider/index.tsx`:
   - Add `useEffect` registering the `storage` event listener calling `syncThemeFromStorage(event.newValue)`.
   - Clean up listener in unmount return callback.
3. Verification:
   - `npm run typecheck` (`tsc --noEmit`).
   - `npm run test -- --testPathPattern=theme`.
   - `npm run test -- --testPathPattern=ThemeProvider`.
   - Run settings suite: `npm run test -- --testPathPattern=settings`.

## Task 3 — State and Audit

1. Add phase `APP-AUDIT-B-THEME-SYNC` to `docs/superpowers/PROJECT_STATE.json` and set `active_phase: "APP-AUDIT-B-THEME-SYNC"`.
2. Run independent adversarial plan audit via fresh subagent using `bmad-review-adversarial-general` and record report at `docs/superpowers/audits/APP-AUDIT-B-THEME-SYNC/plan-r1.md`.
3. Implement code changes and regression tests.
4. Run independent adversarial code audit via fresh subagent and record report at `docs/superpowers/audits/APP-AUDIT-B-THEME-SYNC/code-r1.md`.
5. Verify `python scripts/state.py` clean with presence probe `syncThemeFromStorage` in `frontend/lib/theme.ts`.
6. Open pull request closing #399 and execute self-merge conditions.
