# Plan Audit (Round 1) — APP-AUDIT-B-TUNING-HINT (#377)

- **Date**: 2026-10-19
- **Reviewer**: Fresh independent subagent (Plan Audit Round 1)
- **Reviewed Target**: `docs/superpowers/plans/2026-10-19-app-audit-b-tuning-hint-plan.md`
- **Related Codebase**: `frontend/app/(frame)/settings/page.tsx`, `frontend/lib/api.ts`
- **Gate Floor**: Numeric / persistence gate (wrong numbers in front of user/order, corrupted persisted data)
- **Gate Findings**: **0 (Clean at the Gate)**
- **Architectural Findings / Pre-Implementation Notes**: **1 (Next.js 15 App Router page export restriction)**

---

## Gate Assessment

Under the repository numeric and persistence gate definition:
> "THE GATE IS THE ONLY THING THAT COUNTS. A finding blocks only if it can put a WRONG NUMBER in front of a user or on a broker order, or CORRUPT PERSISTED DATA. Everything else -- wording, comments, test hygiene, dead code, stale records, latent defects with no reachable path -- is not a finding for this purpose..."

- **Numeric integrity**: The cadence hint displays human-readable weekday strings ("Mon, Wed, Sat", "Sat", "every day"). It does not generate, alter, or feed into any numeric strike, price, stop-loss, quantity, or broker order parameters.
- **Persistence integrity**: `saveSchedule` and `loadSchedule` data flows are completely unaffected. `formatScheduleCadence` does not mutate the `daysOfWeek` state array in place (it copies into `Set` and sorts a new array). API payloads to `/api/strategy-tuning/schedule` remain `{ enabled, time, days_of_week }`.
- **Verdict**: **0 GATE FINDINGS (CLEAN)**.

---

## Detailed Plan Verification

### 1. `formatScheduleCadence` Correctness
- **Day Indexing**: `0=Mon ... 6=Sun` matches `DAY_LABELS` and backend `datetime.weekday()` / `CronTrigger`.
- **Default Saturday (`[5]`)**: Evaluates to `"Runs at the configured time on Sat"`.
- **Custom Days (e.g. `[0, 2, 5]`)**: Evaluates to `"Runs at the configured time on Mon, Wed, Sat"`.
- **All 7 Days (`[0, 1, 2, 3, 4, 5, 6]`)**: Correctly collapses to `"Runs at the configured time every day"`.
- **Empty Array (`[]`)**: Correctly evaluates to `"No active days selected"`.
- **Out of Range / Invalids**: `.filter((d) => Number.isInteger(d) && d >= 0 && d < DAY_LABELS.length)` correctly filters out `-1`, `7`, floats (`1.5`), `NaN`, etc.
- **Duplicates**: Deduplicated by `Set` and sorted ascending (`[5, 2, 5]` -> `[2, 5]`).
- **Defensive Guard**: Recommended implementation should use `Array.isArray(daysOfWeek) ? daysOfWeek : []` before `new Set(...)` to guard against possible `undefined`/`null` inputs in unit testing.

### 2. Next.js 15 App Router Page Export Constraint (Important Architectural Requirement)
- **Problem**: Next.js 15 enforces strict page entry export validation via `.next/types/app/(frame)/settings/page.ts`.
- **Verification**: Adding `export function formatScheduleCadence` directly to `frontend/app/(frame)/settings/page.tsx` was tested in the codebase with `npm run typecheck`. It failed with:
  ```
  .next/types/app/(frame)/settings/page.ts(12,13): error TS2344: Type 'OmitWithTag<typeof import("..."), "default" | ...>' does not satisfy the constraint '{ [x: string]: never; }'.
    Property 'formatScheduleCadence' is incompatible with index signature.
  ```
- **Remediation**: `formatScheduleCadence` (and `DAY_LABELS`) must not be exported from `frontend/app/(frame)/settings/page.tsx`. Instead, define and export them in a dedicated helper module:
  `frontend/app/(frame)/settings/scheduleCadence.ts`
  Then import `formatScheduleCadence` into `page.tsx` and the test suite (`__tests__/TuningScheduleHint.test.tsx`). This satisfies Next.js 15 App Router rules and ensures `npm run typecheck` (`tsc --noEmit`) passes cleanly.

### 3. UI Cadence Consistency
- `ScheduleSection` in `frontend/app/(frame)/settings/page.tsx` is used for:
  1. `StrategyTuningForm` (`showDaysOfWeek=true`) -> hint updates dynamically.
  2. `EdgarScheduleSection` (`showDaysOfWeek=false`) -> hint remains `"Runs at the configured time every day"`.
  3. `Sp500ScheduleSection` (`showDaysOfWeek=false`) -> hint remains `"Runs at the configured time every day"`.
- Scheduled Scans (`ScanScheduleSection`) uses an independent list UI with separate per-profile inputs and no conflicting cadence hints.
- No other contradictory cadence strings exist in the settings interface.

### 4. Payload Mutation / Corruption Check
- `days_of_week` is passed to `formatScheduleCadence` as read-only.
- `handleSave` passes `daysOfWeek` untouched to `saveSchedule`.
- `loadSchedule` receives `days_of_week` and sets component state without transformation.
- Zero risk of payload mutation, loss, or data corruption.
