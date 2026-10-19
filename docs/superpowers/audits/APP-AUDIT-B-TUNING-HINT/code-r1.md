# Code Audit (Round 1) — APP-AUDIT-B-TUNING-HINT (#377)

- **Date**: 2026-10-19
- **Reviewer**: Fresh independent subagent (applying `bmad-review-adversarial-general`)
- **Reviewed Target**: Commit `800c58ce2ce186f47dcc0c59d35f12d16b7d2b12` on `board/app-audit-b-tuning-hint-b1ebd61a` against `bbaf8f8165049685ce45474ce09ad54ae04ebf15`
- **Reviewed Files**:
  - `frontend/app/(frame)/settings/page.tsx`
  - `frontend/app/(frame)/settings/scheduleCadence.ts`
  - `frontend/app/(frame)/settings/__tests__/TuningScheduleHint.test.tsx`
  - `docs/superpowers/plans/2026-10-19-app-audit-b-tuning-hint-plan.md`
  - `docs/superpowers/audits/APP-AUDIT-B-TUNING-HINT/plan-r1.md`
- **Diff SHA256**: `8bd70b2464ddad45698d0afeb9d0dd3c6f0cdf51adaf81468447b901805101e8`
- **Gate Floor**: Numeric / persistence gate (blocks ONLY if it can put a WRONG NUMBER in front of a user or on a broker order, or CORRUPT PERSISTED DATA).
- **Gate Findings**: 0 (Clean at the Gate)

---

## Gate Assessment

Under the repository numeric and persistence gate definition:
> "THE GATE IS THE ONLY THING THAT COUNTS, AND THE REVIEWER IS TOLD SO. A finding blocks only if it can put a WRONG NUMBER in front of a user or on a broker order, or CORRUPT PERSISTED DATA. Everything else -- wording, comments, test hygiene, dead code, stale records, latent defects with no reachable path -- is not a finding for this purpose..."

### 1. Numeric Errors & Broker Order Integrity
- **Finding**: None.
- **Analysis**: The changes introduce `formatScheduleCadence` in `frontend/app/(frame)/settings/scheduleCadence.ts`, which returns presentational strings for schedule cadence ("Mon, Wed, Sat", "Sat", "every day", "No active days selected"). It performs no numerical calculations related to prices, strikes, stop losses, position sizes, risk caps, or broker orders. It has no connection to broker execution.

### 2. Schedule Payload & Persistence Integrity
- **Finding**: None.
- **Analysis**: `formatScheduleCadence` is a pure function. It treats `daysOfWeek` as read-only and does not mutate the state array in place (it extracts unique days into a new `Set`, filters, and sorts a fresh array). In `frontend/app/(frame)/settings/page.tsx:ScheduleSection`, the `handleSave` handler transmits `{ enabled, time, days_of_week: daysOfWeek }` directly to `saveSchedule` (`saveTuningSchedule` calling `POST /api/strategy-tuning/schedule`). Persisted data structure, types, and serialization remain completely intact.

### 3. Day Index Alignment (0=Mon ... 6=Sun)
- **Finding**: None.
- **Analysis**:
  - `DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const;` (`scheduleCadence.ts:1`)
  - Index 0 = 'Mon', 1 = 'Tue', 2 = 'Wed', 3 = 'Thu', 4 = 'Fri', 5 = 'Sat', 6 = 'Sun'.
  - Backend `tuning_schedule_store.py:15`: `days_of_week: [5]` (Saturday-only). Python `datetime.weekday()` defines Monday as 0 and Sunday as 6, matching Saturday as 5.
  - In `DaysOfWeekPicker` (`page.tsx:859`), `DAY_LABELS.map((label, day) => ...)` indexes `day` 0 through 6 directly.
  - Alignment across frontend UI, helper formatting, API payload, and backend cron trigger is 100% consistent.

### 4. Edge Cases in `formatScheduleCadence`
- **Finding**: None.
- **Analysis**:
  - `showDaysOfWeek: false`: Returns `'Runs at the configured time every day'` unconditionally, preserving exact behavior for EDGAR and S&P 500 schedulers.
  - `daysOfWeek` null or undefined: `Array.isArray(daysOfWeek) ? daysOfWeek : []` ensures no crash; returns `'No active days selected'`.
  - Empty array `[]`: Returns `'No active days selected'`.
  - Single day `[5]`: Returns `'Runs at the configured time on Sat'`.
  - Custom days `[0, 2, 5]`: Returns `'Runs at the configured time on Mon, Wed, Sat'`.
  - All 7 days `[0, 1, 2, 3, 4, 5, 6]`: Collapses cleanly to `'Runs at the configured time every day'`.
  - Duplicates & unsorted `[5, 2, 0, 5, 2]`: `Set` deduplication and numeric `.sort((a, b) => a - b)` produce sorted unique indices `[0, 2, 5]` -> `'Runs at the configured time on Mon, Wed, Sat'`.
  - Out of range or non-integer elements (`[-1, 0, 7, 99]`, `[1.5, NaN]`): Filtered by `Number.isInteger(d) && d >= 0 && d < DAY_LABELS.length`.

### 5. Next.js 15 App Router Conventions
- **Finding**: None.
- **Analysis**: Next.js 15 App Router enforces that `page.tsx` must not export non-page helper identifiers. The implementation strictly adheres to this by placing `DAY_LABELS` and `formatScheduleCadence` in `frontend/app/(frame)/settings/scheduleCadence.ts` and importing them into `page.tsx`. `frontend/app/(frame)/settings/page.tsx` exports only `default function SettingsPage()`. `tsc --noEmit` passes cleanly with zero errors.

### 6. Existing Schedule Callers (EDGAR, S&P 500, Ingestion)
- **Finding**: None.
- **Analysis**:
  - `EdgarScheduleSection` (`page.tsx:2340`) calls `ScheduleSection` with `showDaysOfWeek` omitted (defaulting to `false`).
  - `Sp500ScheduleSection` (`page.tsx:2355`) calls `ScheduleSection` with `showDaysOfWeek` omitted (defaulting to `false`).
  - Both render `'Runs at the configured time every day'`.
  - `IngestionScheduleSection` uses a dedicated `<Row label="Enable nightly schedule" hint="Runs the ingestion job at the configured time every day" ...>` and is completely unaffected.

---

## Adversarial Re-check Verification

1. **Live UI reactivity**:
   - `ScheduleSection` maintains `daysOfWeek` in React state (`const [daysOfWeek, setDaysOfWeek] = useState<number[]>([5])`).
   - `DaysOfWeekPicker` passes updated arrays to `setDaysOfWeek`.
   - On checkbox toggle, React triggers re-render, and `Row` receives the freshly computed `formatScheduleCadence(showDaysOfWeek, daysOfWeek)`. This is explicitly asserted by integration test `dynamically updates hint when checkboxes in DaysOfWeekPicker are toggled`.
2. **Asynchronous hydration**:
   - On mount, `loadSchedule()` fetches `getTuningSchedule()`.
   - The resolved `days_of_week` array calls `setDaysOfWeek(dow)`, dynamically updating the displayed cadence from default Saturday `[5]` to any previously saved custom schedule (e.g., `[0, 2, 5]`).
   - Verified by integration test `hydrates saved Mon/Wed/Sat [0, 2, 5] schedule with accurate cadence hint`.

---

## Verification Evidence

- `npm --prefix frontend run typecheck`: clean (exit code 0).
- `npm --prefix frontend run test -- --testPathPattern=TuningScheduleHint`: 12/12 passed (exit code 0).
- `npm --prefix frontend run test -- --testPathPattern=settings`: 32/32 passed (exit code 0).

---

## Audit Verdict

**CLEAN AT THE NUMERIC / PERSISTENCE GATE (0 FINDINGS)**.
The diff solves issue #377 cleanly without introducing numeric inaccuracies, data corruption, or architectural violations.
