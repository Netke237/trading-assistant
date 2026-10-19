# Code Audit (Round 1) — APP-AUDIT-B-PERCENTILE-TEXT (#388)

- **Date**: 2026-10-19
- **Reviewer**: Fresh independent subagent `ad659a48-7955-4c75-ba54-dda7cf9f4364` (applying `bmad-review-adversarial-general`)
- **Reviewed Target**: `board/app-audit-b-percentile-text-3b7308fa` against `origin/main`
- **Reviewed Commit**: `30856ac6ef7527984a09b389b227d7e7dd51bb9c`
- **Diff SHA256**: `c3849ddf4d1b273ac484bf9c75d7ea9bd587c06d21b761ba5c7ee9e774acae67`
- **Gate Floor**: Numeric / persistence gate (blocks ONLY if it can put a WRONG NUMBER in front of a user or on a broker order, or CORRUPT PERSISTED DATA).
- **Gate Findings**: 0 (Clean)

## Audit Verification Summary

### 1. Pure Helper Implementation (`frontend/lib/formatOrdinal.ts`)
- **Mathematical & Grammatical Correctness**:
  - Base numbers: `0` -> `"0th"`, `1` -> `"1st"`, `2` -> `"2nd"`, `3` -> `"3rd"`, `4`..`10` -> `"4th"`..`"10th"`.
  - Teens exception: `Math.abs(Math.round(n)) % 100` correctly checks `11 <= mod100 <= 13`, returning `'th'` for `11th`, `12th`, `13th`, and compound teens `111th`, `112th`, `113th` (preventing erroneous `*st`, `*nd`, `*rd`).
  - Composite numbers: Correctly matches `abs % 10` for `21st`, `22nd`, `23rd`, `101st`, `121st`, etc.
  - Floats & Defect B3-4 Resolution: `Math.round(n)` correctly rounds decimal percentiles prior to suffix computation: `2.7` -> `3` -> `"3rd"`, `0.2` -> `"0th"`, `0.8` -> `"1st"`, `1.5` -> `"2nd"`, `20.9` -> `"21st"`. This resolves defect B3-4 (`vix_pct_252d: 2.7` rendering `"3th percentile"`).
  - Negative values: `Math.abs` computes suffix by magnitude while `${rounded}` preserves sign (e.g., `-1` -> `"-1st"`, `-11` -> `"-11th"`).
  - Non-finite & Nil safety: `Number.isFinite(n)` guards against `NaN`, `Infinity`, and `-Infinity`, returning `''`. `Number.isFinite(null)` and `Number.isFinite(undefined)` also evaluate to `false` in ECMAScript, ensuring safe failure without throwing.

### 2. Screener Step 1 Call Sites (`frontend/app/(frame)/screener/step-1-regime/page.tsx`)
- All 4 call sites were audited:
  - **Line 329** (`intraHmm` branch): `<Text size={11} tone="dim">VIX at {formatOrdinal(vix30)} percentile (30-day window)</Text>`
  - **Line 351** (`intraOmm` fallback branch): `<Text size={11} tone="dim">VIX at {formatOrdinal(vix30)} percentile (30-day window)</Text>`
  - **Line 385** (Swing horizon, `omm` branch): `<Text size={11} tone="dim">VIX at {formatOrdinal(vix252)} percentile (252-day window)</Text>`
  - **Line 415** (Position horizon, `omm` branch): `<Text size={11} tone="dim">VIX at {formatOrdinal(vix252)} percentile (252-day window)</Text>`
- Spacing: Single space before and after `{formatOrdinal(...)}` preserves proper token separation (`"VIX at 3rd percentile (252-day window)"`).
- Null guards: Preceding `{vix30 != null && ...}` and `{vix252 != null && ...}` checks prevent rendering when data is absent.
- No remaining hardcoded `}th` instances remain anywhere in `frontend/`.

### 3. Numeric & Persistence Gate Verification
- **Wrong number on UI / broker orders**: Zero risk. The numeric value rendered is identical to `Math.round(vix)` as previously computed; only the grammatical suffix is corrected. The formatted string is purely presentational inside `<Text>` in Step 1 Regime by Horizon cards and is never included in broker order payloads or sizing calculations.
- **Data corruption**: Zero risk. Neither `formatOrdinal` nor Step 1's horizon cards write to localStorage, IndexedDB, or backend persistence.

### 4. Test Suite Coverage
- `frontend/lib/__tests__/formatOrdinal.test.ts`: 13 test cases thoroughly asserting ordinals across 0..10, teens (11..13), 20..24, 100+, negatives, decimals (2.7 -> 3rd), and non-finite inputs.
- `frontend/app/(frame)/screener/step-1-regime/__tests__/vixPercentileDisplay.test.tsx`: 14 test cases verifying end-to-end rendering for 0th, 3rd (reproducing B3-4), `it.each` table of ordinals (1st, 2nd, 11th..13th, 21st..23rd), 30d window in intraday HMM and OMM, and null omissions.
