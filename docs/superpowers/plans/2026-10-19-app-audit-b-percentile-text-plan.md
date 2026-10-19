# APP-AUDIT-B-PERCENTILE-TEXT — Regime VIX percentile labels render incorrect ordinal suffixes (#388)

Independent remediation phase from #350 (programme #348), addressing defect B3-4 from `docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/regime/findings.md`.

## Goal

Fix the presentation defect in Screener Step 1 (`frontend/app/(frame)/screener/step-1-regime/page.tsx`) where VIX percentile labels render hardcoded `th` suffixes (e.g., `3th percentile` from `vix_pct_252d: 2.7`), replacing it with standard English ordinal formatting (e.g., `3rd percentile`, `1st percentile`, `2nd percentile`, `11th percentile`, `21st percentile`).

## Root Cause

In `frontend/app/(frame)/screener/step-1-regime/page.tsx`:
- Line 331 (Intraday horizon, `intraHmm` branch):
  `<Text size={11} tone="dim">VIX at {Math.round(vix30)}th percentile (30-day window)</Text>`
- Line 353 (Intraday horizon, `intraOmm` branch):
  `<Text size={11} tone="dim">VIX at {Math.round(vix30)}th percentile (30-day window)</Text>`
- Line 387 (Swing horizon, `omm` branch):
  `<Text size={11} tone="dim">VIX at {Math.round(vix252)}th percentile (252-day window)</Text>`
- Line 417 (Position horizon, `omm` branch):
  `<Text size={11} tone="dim">VIX at {Math.round(vix252)}th percentile (252-day window)</Text>`

Each of these four sites interpolates `{Math.round(...)}th` directly into the string, producing invalid ordinals such as `1th`, `2th`, `3th`, `21th`, `22th`, `23th`.

## Design & Implementation

### 1. Pure Helper: `frontend/lib/formatOrdinal.ts`

Introduce two exported functions:
- `ordinalSuffix(n: number): string`
  Computes the correct English ordinal suffix for a rounded integer `n`:
  - If `!Number.isFinite(n)`, returns `''`.
  - For `Math.abs(Math.round(n)) % 100` between 11 and 13 inclusive, returns `'th'` (e.g. 11th, 12th, 13th, 111th, 112th, 113th).
  - Otherwise, for `Math.abs(Math.round(n)) % 10`:
    - `1` -> `'st'` (e.g. 1st, 21st, 31st, 101st)
    - `2` -> `'nd'` (e.g. 2nd, 22nd, 32nd, 102nd)
    - `3` -> `'rd'` (e.g. 3rd, 23rd, 33rd, 103rd)
    - All others (`0`, `4`..`9`) -> `'th'` (e.g. 0th, 4th..10th, 20th, 100th).
- `formatOrdinal(n: number): string`
  Rounds `n` via `Math.round(n)` and returns `${rounded}${ordinalSuffix(rounded)}`.
  Returns `''` if `!Number.isFinite(n)`.

### 2. Page Updates: `frontend/app/(frame)/screener/step-1-regime/page.tsx`

Import `formatOrdinal` from `@/lib/formatOrdinal`.
Update the four rendering sites:
- Line 331:
  `<Text size={11} tone="dim">VIX at {formatOrdinal(vix30)} percentile (30-day window)</Text>`
- Line 353:
  `<Text size={11} tone="dim">VIX at {formatOrdinal(vix30)} percentile (30-day window)</Text>`
- Line 387:
  `<Text size={11} tone="dim">VIX at {formatOrdinal(vix252)} percentile (252-day window)</Text>`
- Line 417:
  `<Text size={11} tone="dim">VIX at {formatOrdinal(vix252)} percentile (252-day window)</Text>`

### 3. Unit Tests: `frontend/lib/__tests__/formatOrdinal.test.ts`

Thorough unit tests covering:
- Base cases: 0 -> `0th`, 1 -> `1st`, 2 -> `2nd`, 3 -> `3rd`, 4 -> `4th`..9 -> `9th`, 10 -> `10th`.
- Teens exception (11-13): 11 -> `11th`, 12 -> `12th`, 13 -> `13th`, 14 -> `14th`.
- Twenties & beyond: 20 -> `20th`, 21 -> `21st`, 22 -> `22nd`, 23 -> `23rd`, 24 -> `24th`.
- Larger numbers & hundreds teens: 100 -> `100th`, 101 -> `101st`, 102 -> `102nd`, 103 -> `103rd`, 111 -> `111th`, 112 -> `112th`, 113 -> `113th`, 121 -> `121st`.
- Decimals: 2.7 -> `3rd`, 0.2 -> `0th`, 0.8 -> `1st`, 20.9 -> `21st`.
- Edge cases: `NaN`, `Infinity`, `-Infinity` -> `''`.

### 4. Component & Integration Tests

Update and expand `frontend/app/(frame)/screener/step-1-regime/__tests__/vixPercentileDisplay.test.tsx`:
- Preserve existing tests (e.g. `0.0` -> `0th percentile`).
- Add test for `vix_pct_252d: 2.7` -> verifies `VIX at 3rd percentile (252-day window)` rendered in Swing and Position columns (confirming resolution of finding B3-4).
- Add tests for 1st, 2nd, 21st, 11th, 12th, 13th for 252-day window.
- Add test for 30-day window intraday (both `intraHmm` and `intraOmm` branches) rendering correct ordinal suffixes.

## Verification Checklist

1. `npm test -- frontend/lib/__tests__/formatOrdinal.test.ts`
2. `npm test -- frontend/app/(frame)/screener/step-1-regime/__tests__/vixPercentileDisplay.test.tsx`
3. `npm run typecheck` (`tsc --noEmit`)
4. Full frontend test suite: `npm test`
5. `python scripts/state.py`
