# APP-AUDIT-B-DENSITY — Appearance row density persistence across remount/reload (#370)

Part of #350 · programme #348.
Task ID: `APP-AUDIT-B-DENSITY` · Size S · Complexity 2/5 · Lanes: B (save boundary) & J (presentation).

## Problem & Root Cause

In `frontend/app/(frame)/settings/page.tsx`, the Appearance section intro states:
> "Visual preferences. Theme and density persist per browser."

However, `ThemeForm()` stores `density` solely in component-local `useState<'Comfortable' | 'Compact'>('Comfortable')`. No store or `localStorage` persistence exists for density. When the user navigates between Settings sub-sections (e.g. Appearance → Regime → Appearance) or reloads the browser, `ThemeForm` unmounts and remounts, resetting the density back to "Comfortable". Furthermore, tables across the application do not receive or reflect any row density preference.

## Scope of Changes

1. **Store persistence (`frontend/lib/theme.ts`)**:
   - Export `Density = 'Comfortable' | 'Compact'`.
   - Add `density: Density` and `setDensity: (d: Density) => void` to `ThemeState`.
   - Retain existing storage key `THEME_STORAGE_KEY = 'bamendjou:theme'` (strictly no storage key renames).
   - Configure `version: 1` with a `migrate` handler:
     - Legacy unversioned / v0 payloads (`{ state: { theme: ... } }`) keep their persisted `theme` and initialize `density: 'Comfortable'`.
     - Valid stored density is preserved.
   - Initial defaults: `theme: 'dark'`, `density: 'Comfortable'`.

2. **DOM sync (`frontend/components/ThemeProvider/index.tsx`)**:
   - Read `density` from `useThemeStore((s) => s.density)`.
   - Synchronize `document.documentElement.dataset.density = density.toLowerCase()` in a `useEffect` alongside `data-theme`.

3. **No-flash script & layout (`frontend/app/layout.tsx`)**:
   - In `noFlashScript`: read `density` from `localStorage.getItem('bamendjou:theme')` and set `document.documentElement.dataset.density = d.toLowerCase()` if `d === 'Compact' || d === 'Comfortable'`.
   - On `<html ...>` in `RootLayout`: add default `data-density="comfortable"`.

4. **Design tokens (`frontend/styles/tokens.css`)**:
   - Define `--table-row-min-height: 44px;` on `:root` and `[data-density="comfortable"]`.
   - Define `--table-row-min-height: 32px;` on `[data-density="compact"]`.

5. **Table row consumer (`frontend/components/molecules/TableRow/`)**:
   - In `TableRow/index.tsx`: subscribe to `useThemeStore((s) => s.density)` and pass `data-density={density.toLowerCase()}` to the row element.
   - In `TableRow/TableRow.module.css`: use `min-height: var(--table-row-min-height, 44px);` and add `:global([data-density="compact"]) .row, .row[data-density="compact"] { min-height: 32px; }`.

6. **Settings UI (`frontend/app/(frame)/settings/page.tsx`)**:
   - In `ThemeForm()`: bind the Row density `<select>` directly to `density` and `setDensity` from `useThemeStore`.

## Implementation & Test Strategy (TDD)

1. **Regression test (Red -> Green)**:
   - Create `frontend/app/(frame)/settings/__tests__/ThemeForm.density.test.tsx`:
     - Mount `SettingsPage`.
     - Change density select to "Compact".
     - Switch section to "regime" (unmounting `ThemeForm`).
     - Switch section back to "theme" (remounting `ThemeForm`).
     - Assert that the selected option remains "Compact".
     - Assert `localStorage.getItem('bamendjou:theme')` holds `density: 'Compact'`.

2. **Store & migration tests**:
   - Create `frontend/lib/__tests__/theme.test.ts`:
     - Test initial state: `theme: 'dark'`, `density: 'Comfortable'`.
     - Test `setDensity('Compact')` updates state and persists.
     - Test migration from v0 (`{ theme: 'light' }`) upgrades cleanly to v1 with `theme: 'light'` and `density: 'Comfortable'`.
     - Test migration preserves valid stored density if present.

3. **Component & DOM tests**:
   - Create `frontend/components/molecules/TableRow/__tests__/TableRow.density.test.tsx`:
     - Verify `TableRow` renders `data-density="comfortable"` by default.
     - Verify `TableRow` renders `data-density="compact"` when store density is `Compact`.
   - Create `frontend/components/ThemeProvider/__tests__/ThemeProvider.density.test.tsx`:
     - Verify `document.documentElement.dataset.density` mirrors `useThemeStore`.

4. **Repository verification**:
   - `npm run typecheck` clean (0 errors).
   - Full frontend test suite (`npm run test`) clean.
   - `python scripts/state.py` clean (0 drift).

## Review & Audit Gates

1. Independent plan audit: spawn a fresh subagent running `bmad-review-adversarial-general` against this plan under the numeric/persistence gate. Record 0 gate findings in `docs/superpowers/audits/APP-AUDIT-B-DENSITY/plan-r1.md`.
2. Update plan stage in `PROJECT_STATE.json`.
3. Implement code changes and tests.
4. Independent code audit: spawn a fresh subagent running `bmad-review-adversarial-general` against the diff under the numeric/persistence gate. Record 0 gate findings in `docs/superpowers/audits/APP-AUDIT-B-DENSITY/code-r1.md`.
5. Update code stage in `PROJECT_STATE.json` and verify `python scripts/state.py`.
