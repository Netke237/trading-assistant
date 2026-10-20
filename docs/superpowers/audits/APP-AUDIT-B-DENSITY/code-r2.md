# Adversarial Code Audit Report: APP-AUDIT-B-DENSITY (#370) — Round 2

- **Reviewer**: Fresh independent adversarial auditor `1ba62927-4c41-414f-b628-7a9a3ee8f57e`
- **Skill Applied**: `bmad-review-adversarial-general` (.agents/skills/bmad-review-adversarial-general/SKILL.md)
- **Reviewed Target**: Diff between `origin/main` (`2d1e54c4f4f3867da090028d0b84fbbfaeb64f31`) and `HEAD` (`3b633d04898f7ede81b3dee4520e4cfb7176e3e8`), checked against `docs/superpowers/plans/2026-10-19-app-audit-b-density-plan.md`
- **Gate Floor**: Numeric / persistence gate (a finding blocks only if it can put a WRONG NUMBER in front of a user or on a broker order, or CORRUPT PERSISTED DATA; comments block only if a competent reader acting on them would write a wrong change misstating mechanism).

---

## Scope & Files Inspected

1. `frontend/lib/theme.ts`:
   - Exported `Density = 'Comfortable' | 'Compact'`.
   - Added `density: Density` and `setDensity: (d: Density) => void` to `ThemeState`.
   - Store configured with version `1` and a `migrate` handler:
     - Unversioned / v0 payloads (`{ state: { theme: ... } }`) keep their persisted theme and default `density: 'Comfortable'`.
     - Valid stored density is preserved.
     - Null or corrupted objects safely fall back to `{ theme: 'dark', density: 'Comfortable' }`.
   - Retained storage key `THEME_STORAGE_KEY = 'bamendjou:theme'` strictly without rename.
   - Retained `parseTheme` and `syncThemeFromStorage` helpers from #399 without alteration to their contracts.
2. `frontend/app/(frame)/settings/page.tsx`:
   - Replaced component-local `useState<'Comfortable' | 'Compact'>('Comfortable')` in `ThemeForm` with `useThemeStore((s) => s.density)` and `useThemeStore((s) => s.setDensity)`.
   - Bound `<select value={density} onChange={(e) => setDensity(e.target.value as Density)}>` directly to the store.
   - Verified no interaction with broker, risk, strategy parameters, or scan settings.
3. `frontend/app/layout.tsx`:
   - In `noFlashScript`: read `density` from `localStorage.getItem('bamendjou:theme')` inside `try/catch`. When `d === 'Compact' || d === 'Comfortable'`, sets `document.documentElement.dataset.density = d.toLowerCase()`.
   - Root `<html ...>` sets default `data-density="comfortable"`.
4. `frontend/components/ThemeProvider/index.tsx`:
   - Subscribed to `useThemeStore((s) => s.density)`.
   - Added `useEffect` syncing `document.documentElement.dataset.density = density.toLowerCase()`.
   - Retained `storage` event listener on `window` syncing cross-tab storage changes via `syncThemeFromStorage`.
5. `frontend/components/molecules/TableRow/index.tsx`:
   - Subscribed to `useThemeStore((s) => s.density)`.
   - Published `data-density={density.toLowerCase()}` attribute on the row element.
   - Grid columns (`style={{ gridTemplateColumns: columns }}`), status attribute, selection, and keyboard/click handlers remain intact and undisturbed.
6. `frontend/components/molecules/TableRow/TableRow.module.css`:
   - Updated `.row` min-height to `var(--table-row-min-height, 44px)`.
   - Added `.row[data-density="compact"], :global([data-density="compact"]) .row { min-height: 32px; }`.
7. `frontend/styles/tokens.css`:
   - Defined `--table-row-min-height: 44px;` on `:root` and `[data-density="comfortable"]`.
   - Defined `--table-row-min-height: 32px;` on `[data-density="compact"]`.
8. `frontend/app/(frame)/settings/__tests__/ThemeForm.density.test.tsx`:
   - Integration test proving density selection survives Settings section remount (Appearance → Regime → Appearance) and persists to `localStorage`.
9. `frontend/components/ThemeProvider/__tests__/ThemeProvider.density.test.tsx`:
   - Verified `dataset.density` initializes to `comfortable` and dynamically updates to `compact` upon store mutation.
10. `frontend/components/molecules/TableRow/__tests__/TableRow.density.test.tsx`:
    - Verified `TableRow` renders `data-density="comfortable"` by default, `data-density="compact"` when store density is `Compact`, and reacts dynamically to store updates.
11. `frontend/lib/__tests__/theme.test.ts`:
    - Verified store initial state, `setDensity`, persistence under `bamendjou:theme`, `toggle` interaction, and v0 legacy migration behavior.
    - Verified unit tests for `parseTheme` and `syncThemeFromStorage` pass.
12. `docs/superpowers/plans/2026-10-19-app-audit-b-density-plan.md` & `docs/superpowers/PROJECT_STATE.json`:
    - Verified plan requirements against implementation.
    - Verified `verify` probe (`density: Density` in `frontend/lib/theme.ts`) matches state checker.

---

## Merge Conflict Resolution Scrutiny

Special scrutiny was applied to the merge conflict resolution between `origin/main` (which brought in `APP-AUDIT-B-THEME-SYNC` #399) and the density branch (`APP-AUDIT-B-DENSITY` #370):

1. **`frontend/components/ThemeProvider/index.tsx`**:
   - Merge conflict: `origin/main` added the `storage` event listener calling `syncThemeFromStorage`, while the density branch added the `density` store subscription and `dataset.density` synchronization effect.
   - Resolution: Both effects were retained cleanly. The density effect and storage listener effect are decoupled and run in separate `useEffect` hooks with correct dependency arrays (`[density]` and `[]`).
2. **`frontend/lib/__tests__/theme.test.ts`**:
   - Merge conflict: `origin/main` added tests for `parseTheme` and `syncThemeFromStorage` under `describe('theme.ts unit tests (#399)', ...)`. The density branch added tests for density persistence and migration under `describe('theme store (useThemeStore) — persistence and density (#370)', ...)`.
   - Resolution: Both test suites were preserved in full. The `beforeEach` in the #399 suite was updated to reset `density: 'Comfortable'` as well as `theme: 'dark'`, ensuring test isolation and preventing cross-suite state leakage.

---

## Gate Assessment

- **Wrong numbers in front of user or on broker orders**:
  None. The changes operate strictly on CSS row min-height (`44px` vs `32px`) and visual density preference (`'Comfortable' | 'Compact'`). Zero touch or modification of pricing, sizing, Greeks, strike prices, calculations, scan scores, or order submission payloads.
- **Corrupted persisted data**:
  None. The storage key remains `'bamendjou:theme'`. Persist version was bumped from v0 to v1 with a backward-compatible migration handler that preserves existing theme selections (`'light' | 'dark'`), sets density default to `'Comfortable'`, and validates any stored density value against corruption.
- **Mechanism misstatements in comments**:
  None. Code comments accurately describe the DOM synchronization mechanism and inline script behavior.

---

## Verification Executed

1. `npm run typecheck` (`tsc --noEmit`): Clean (0 errors).
2. Jest unit and integration tests:
   - `npm test -- --testPathPattern="theme|TableRow|ThemeForm"`: 5 test suites passed, 31 tests passed.
   - `npm test -- --testPathPattern=settings`: 11 test suites passed, 83 tests passed.
3. `python scripts/state.py`: "No drift: every declared status matches the code."

GATE FINDINGS: 0
