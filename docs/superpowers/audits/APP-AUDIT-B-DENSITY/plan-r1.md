# APP-AUDIT-B-DENSITY — independent plan round 1 of 3

Reviewer: fresh independent subagent, applying `bmad-review-adversarial-general` and the repository numeric/persistence gate. GATE FINDINGS: **0**.

Exact reviewed artifact: `docs/superpowers/plans/2026-10-19-app-audit-b-density-plan.md`, lines 1–80, SHA256 `d2ca053620bfc6e1caff8df313d03c6e719f57a7ceefcbc2680516f9c72e5cd2`.

Source baseline: worktree HEAD `f08e4dfcfeded53690b522a90db3185c9bd2dd98`. Reviewed actual codebase files:
- `frontend/lib/theme.ts`: lines 1–42 (`THEME_STORAGE_KEY = 'bamendjou:theme'`, `useThemeStore` with Zustand `persist` middleware, `skipHydration: true`, unversioned / v0 baseline).
- `frontend/app/(frame)/settings/page.tsx`: lines 215–238 (`ThemeForm()` unpersisted local `useState<'Comfortable' | 'Compact'>('Comfortable')` resetting on remount).
- `frontend/app/layout.tsx`: lines 51–84 (inline `noFlashScript` reading `localStorage['bamendjou:theme']`, `<html data-theme="dark">` with `suppressHydrationWarning`).
- `frontend/components/ThemeProvider/index.tsx`: lines 1–24 (`document.documentElement.dataset.theme = theme` in `useEffect`).
- `frontend/components/StoreHydration/index.tsx`: line 39 (`useThemeStore.persist.rehydrate()` already executed on client mount).
- `frontend/components/molecules/TableRow/index.tsx` & `TableRow.module.css`: lines 1–74 and 1–67 (`min-height: 44px`).
- `frontend/styles/tokens.css` & `frontend/app/globals.css`: design tokens sheet.

Findings: none meeting the gate. No location/trigger/guard/consequence entries are required because no blocking defect was established.

---

## Detailed Scrutiny Against Numeric & Persistence Gate

### 1. Zustand persistence migration handling existing `bamendjou:theme` payloads
- Existing stored data in `localStorage['bamendjou:theme']` uses shape `{"state":{"theme":"dark"|"light"},"version":0}` (or unversioned default).
- The plan bumps store version to `version: 1` and provides a `migrate(persistedState, version)` handler.
- Strictly retains `THEME_STORAGE_KEY = 'bamendjou:theme'` (strictly no storage key renames per repo conventions).
- Migration branch for `version < 1` reads existing `theme`, preserves it if valid (`'dark'` or `'light'`), and initializes `density: 'Comfortable'`. If `persistedState` is empty or null, it falls back cleanly to defaults (`theme: 'dark'`, `density: 'Comfortable'`).
- Zero data loss or corruption for existing users.

### 2. Preservation of theme and density defaults
- The migration guarantees that any existing user's theme selection (`'light'` or `'dark'`) remains intact.
- The new `density` setting defaults to `'Comfortable'`.
- Any existing or partially set valid density (`'Comfortable'` | `'Compact'`) is preserved.

### 3. DOM synchronization (`data-density`) and `TableRow` solving the reset defect
- Root cause verified: in `SettingsPage`, `ThemeForm()` previously managed `density` in component-local `useState`, discarding state on sub-tab navigation or reload.
- Plan binds `ThemeForm` directly to `useThemeStore((s) => s.density)` and `setDensity`, eliminating unmount state loss.
- Page reload sync:
  - `RootLayout` sets default `<html data-density="comfortable">`.
  - Inline `noFlashScript` in `<head>` parses `localStorage['bamendjou:theme']` and sets `document.documentElement.dataset.density = d.toLowerCase()` before initial paint if stored density is `'Compact'`, preventing layout shift / flash of un-compact content.
  - `StoreHydration` rehydrates `useThemeStore` on mount.
  - `ThemeProvider`'s `useEffect` synchronizes `document.documentElement.dataset.density = density.toLowerCase()`.
  - `TableRow` adopts `min-height: var(--table-row-min-height, 44px)` with `--table-row-min-height: 32px` under `[data-density="compact"]` and element attribute `data-density="compact"`.
- Remount/reload reset defect is completely resolved.

### 4. Edge cases & data corruption analysis
- Corrupt / non-JSON `localStorage`: `noFlashScript` wraps parsing in `try { ... } catch (e) {}` and validates allowed values (`'Compact'` or `'Comfortable'`).
- Unsupported values: strict union type `Density = 'Comfortable' | 'Compact'` and dropdown options prevent invalid state writes.
- Numeric / broker order isolation: Theme and density state are purely visual presentation attributes; no calculation, sizing, threshold, or broker execution reads `useThemeStore`.

---

## Meaningful Zero-Finding Recheck (BMad Adversarial Stance)

- Re-checked case-sensitivity: Store uses PascalCase `'Comfortable' | 'Compact'`; DOM dataset uses lowercase `'comfortable' | 'compact'`. The plan consistently maps `density.toLowerCase()` in `ThemeProvider`, `noFlashScript`, `TableRow`, and CSS selectors (`[data-density="compact"]`).
- Re-checked hydration lifecycle: `useThemeStore` specifies `skipHydration: true`. `StoreHydration` explicitly calls `useThemeStore.persist.rehydrate()` at mount. Between SSR and hydration, `noFlashScript` bridges the DOM attribute while `suppressHydrationWarning` on `<html>` prevents Next.js hydration mismatches.
- Re-checked scope boundary: The plan confines edits to `theme.ts`, `settings/page.tsx`, `layout.tsx`, `ThemeProvider/index.tsx`, `TableRow`, `tokens.css`, and associated tests. No unrelated stores or broker routing logic are touched.
- Re-checked verification plan: TDD test suite specified covering `ThemeForm` remount persistence, `themeStore` migration from v0, and `TableRow`/`ThemeProvider` DOM attribute rendering.

Plan Round 1 is clean under the numeric/persistence gate.
