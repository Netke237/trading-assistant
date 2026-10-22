# APP-AUDIT-B-DENSITY — independent code round 1 of 3

Reviewer: fresh independent subagent `b3d1e67a-2f58-4e5d-b3c3-6d85679f37e7`, applying `bmad-review-adversarial-general` and the repository numeric/persistence gate. GATE FINDINGS: **0**.

Exact reviewed artifact: commit `eafbd7d612ec78611aff4133c88178e8000faebf` (diff `f08e4dfcfeded53690b522a90db3185c9bd2dd98..eafbd7d612ec78611aff4133c88178e8000faebf`).

Files reviewed:
- `frontend/lib/theme.ts`: Added `Density` type (`'Comfortable' | 'Compact'`), `density: Density`, `setDensity: (d: Density) => void` on `ThemeState`. Implemented Zustand `version: 1` with a migration handler that safely validates and preserves existing legacy v0 payloads (`theme: 'light' | 'dark'`), defaults missing/corrupted density to `'Comfortable'`, and keeps storage key `THEME_STORAGE_KEY = 'bamendjou:theme'` untouched.
- `frontend/lib/__tests__/theme.test.ts`: 5 tests verifying default state, `setDensity` state and localStorage persistence, `setTheme`/`toggle` alongside density, and v0 legacy migration.
- `frontend/app/(frame)/settings/page.tsx`: Bound `ThemeForm` row density dropdown directly to `useThemeStore((s) => s.density)` and `setDensity`, eliminating unmount state loss on subnav switching.
- `frontend/app/(frame)/settings/__tests__/ThemeForm.density.test.tsx`: Integration test verifying density selection survives Settings section remount (Appearance -> Regime -> Appearance) and persists to localStorage.
- `frontend/app/layout.tsx`: Updated `noFlashScript` in `<head>` to parse `density` from `bamendjou:theme` with try/catch exception safety, and added default `data-density="comfortable"` to `<html ...>`.
- `frontend/components/ThemeProvider/index.tsx`: Added `useEffect` to synchronize `document.documentElement.dataset.density = density.toLowerCase()` in lockstep with store changes.
- `frontend/components/ThemeProvider/__tests__/ThemeProvider.density.test.tsx`: 2 tests verifying `data-density` synchronization on initial mount and on subsequent store updates.
- `frontend/components/molecules/TableRow/index.tsx`: Subscribed to `useThemeStore((s) => s.density)` and published `data-density={density.toLowerCase()}` attribute on row elements.
- `frontend/components/molecules/TableRow/TableRow.module.css`: Adopted `min-height: var(--table-row-min-height, 44px)` and added `.row[data-density="compact"], :global([data-density="compact"]) .row { min-height: 32px; }`.
- `frontend/components/molecules/TableRow/__tests__/TableRow.density.test.tsx`: 3 tests verifying `TableRow` renders with `data-density="comfortable"` by default, `data-density="compact"` when store density is `Compact`, and reacts dynamically to store updates.
- `frontend/styles/tokens.css`: Defined `--table-row-min-height: 44px` on `:root` and `[data-density="comfortable"]`, and `32px` on `[data-density="compact"]`.
- `docs/superpowers/plans/2026-10-19-app-audit-b-density-plan.md`
- `docs/superpowers/audits/APP-AUDIT-B-DENSITY/plan-r1.md`
- `docs/superpowers/PROJECT_STATE.json`

Findings: none meeting the gate. No location/trigger/guard/consequence entries required because no blocking defect was found.

---

## Detailed Scrutiny Against Numeric & Persistence Gate

### 1. Persistence & Migration Integrity (`frontend/lib/theme.ts`)
- Preserved existing storage key `'bamendjou:theme'` (strictly no key rename).
- Configured Zustand store version 1 with migration:
  ```ts
  migrate: (persistedState: unknown, version: number) => {
    const state = (persistedState && typeof persistedState === 'object')
      ? (persistedState as Record<string, unknown>)
      : {};
    return {
      theme: state.theme === 'light' ? 'light' : 'dark',
      density: state.density === 'Compact' ? 'Compact' : 'Comfortable',
    };
  }
  ```
- Validated:
  - If a user had `theme: 'light'` saved in v0, `state.theme === 'light'` evaluates to `'light'`.
  - If a user had `theme: 'dark'` saved in v0, `state.theme === 'dark'` evaluates to `'dark'`.
  - If legacy payload did not contain `density`, it defaults cleanly to `'Comfortable'`.
  - If corrupted or null, it falls back safely to `{ theme: 'dark', density: 'Comfortable' }`.
  - Actions `setTheme`, `setDensity`, and `toggle` only perform shallow updates on their respective fields without clobbering each other.

### 2. Remount & Reload Preservation (`frontend/app/(frame)/settings/page.tsx`)
- Root cause resolved: `ThemeForm` previously used local `useState<'Comfortable' | 'Compact'>('Comfortable')`, causing density to reset to "Comfortable" whenever the user navigated between Settings tabs or reloaded the browser.
- Switched to Zustand store `useThemeStore((s) => s.density)` and `setDensity`.
- Remounting `ThemeForm` now reads the persisted state. Tested and verified via `ThemeForm.density.test.tsx`.

### 3. No-Flash Script & Hydration Safety (`frontend/app/layout.tsx` & `ThemeProvider`)
- `noFlashScript` in `layout.tsx` safely extracts `parsed.state.density` inside `try { ... } catch (e) {}`. If privacy mode blocks `localStorage.getItem` or storage contains malformed JSON, it catches cleanly without throwing or crashing.
- Evaluates `d === 'Compact' || d === 'Comfortable'`, setting `document.documentElement.dataset.density = d.toLowerCase()`.
- Root `<html ...>` specifies `data-density="comfortable"` and `suppressHydrationWarning`.
- `StoreHydration` calls `useThemeStore.persist.rehydrate()`, and `ThemeProvider` ensures DOM dataset remains synchronized via `useEffect`.

### 4. Layout & Numeric / Broker Isolation (`TableRow` & `tokens.css`)
- `TableRow` column widths (`gridTemplateColumns: columns`) and grid column structure are untouched.
- `min-height` switches between 44px (comfortable) and 32px (compact), saving vertical screen space in dense tables while preserving text alignment and border styling.
- Zero touch or interaction with pricing, sizing, calculation, or broker order execution logic.

---

## Verification Results

1. **TypeScript check**:
   `npm run typecheck` (`tsc --noEmit`) exited 0 with 0 errors.

2. **Jest tests**:
   - `jest --testPathPattern=density|theme`: 4 test suites passed, 11 tests passed in 21.5s.
   - `jest frontend/lib/persistMigrations.test.ts`: 1 test suite passed, 13 tests passed in 12.1s.
   - `jest ThemeForm`: 1 test suite passed, 1 test passed in 9.4s.

3. **Project state check**:
   `py scripts/state.py` verified cleanly: "No drift: every declared status matches the code."

Code Round 1 audit is clean with **0 gate findings**.
