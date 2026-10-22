# APP-AUDIT-B-TUNING-HINT — Strategy tuning schedule cadence hint reflects selected weekdays (#377)

Part of #350 · programme #348. Separate remediation phase, user-authorized. Application code does not change scheduler execution policy or tuning calibration.

## Goal

Ensure the visible cadence hint under "Enable schedule" in `ScheduleSection` (`frontend/app/(frame)/settings/page.tsx`) accurately reflects the selected weekdays when `showDaysOfWeek` is enabled (used by Strategy Tuning), rather than falsely displaying `"Runs at the configured time every day"` when custom days such as Mon/Wed/Sat (`[0, 2, 5]`) or default Saturday (`[5]`) are active.

## Mechanism

### Problem Analysis
In `frontend/app/(frame)/settings/page.tsx:2205-2316`, `ScheduleSection` is a reusable component used for:
1. `EdgarScheduleSection` (`showDaysOfWeek=false`)
2. `Sp500ScheduleSection` (`showDaysOfWeek=false`)
3. `StrategyTuningForm` (`showDaysOfWeek=true`)

In `ScheduleSection`:
```tsx
<Row label="Enable schedule" hint="Runs at the configured time every day" defaultValue="Off">
  <Toggle defaultOn={enabled} onChange={(on) => setEnabled(on)} />
</Row>
```
The hint string is currently hardcoded to `"Runs at the configured time every day"`.
When Strategy Tuning is enabled with `showDaysOfWeek=true`, the user can select specific weekdays (default Saturday `[5]`, or custom such as `[0, 2, 5]` for Mon/Wed/Sat).
Although `days_of_week` correctly saves to and loads from the backend `/api/strategy-tuning/schedule`, the visible hint in the "Enable schedule" row stubbornly claims the job runs "every day", contradicting the selected weekdays.

### Repair
Introduce a pure helper function `formatScheduleCadence(showDaysOfWeek: boolean, daysOfWeek: number[]): string`:
```tsx
export function formatScheduleCadence(showDaysOfWeek: boolean, daysOfWeek: number[]): string {
  if (!showDaysOfWeek) {
    return 'Runs at the configured time every day';
  }
  const unique = Array.from(new Set(daysOfWeek))
    .filter((d) => Number.isInteger(d) && d >= 0 && d < DAY_LABELS.length)
    .sort((a, b) => a - b);
  if (unique.length === 0) {
    return 'No active days selected';
  }
  if (unique.length === DAY_LABELS.length) {
    return 'Runs at the configured time every day';
  }
  const dayNames = unique.map((d) => DAY_LABELS[d]).join(', ');
  return `Runs at the configured time on ${dayNames}`;
}
```

In `ScheduleSection`:
Replace the static hint:
```tsx
<Row label="Enable schedule" hint={formatScheduleCadence(showDaysOfWeek, daysOfWeek)} defaultValue="Off">
```

### Behavior Verification
1. **Default Saturday (`[5]`)**: Hint displays `"Runs at the configured time on Sat"`.
2. **Custom weekdays (e.g. `[0, 2, 5]` for Mon, Wed, Sat)**: Hint displays `"Runs at the configured time on Mon, Wed, Sat"`.
3. **All seven days (`[0, 1, 2, 3, 4, 5, 6]`)**: Hint displays `"Runs at the configured time every day"`.
4. **No days selected (`[]`)**: Hint displays `"No active days selected"`.
5. **Dynamic updates**: As the user toggles checkboxes in `DaysOfWeekPicker`, `daysOfWeek` state updates, immediately updating the hint without needing a save or reload.
6. **Remount hydration**: On page or section remount, the loaded `days_of_week` from `getTuningSchedule()` hydrates `daysOfWeek` state and renders the saved cadence hint.
7. **Non-daysOfWeek sections (`EdgarScheduleSection`, `Sp500ScheduleSection`)**: With `showDaysOfWeek=false` (default), the hint remains `"Runs at the configured time every day"`.
8. **No side effects**: Scheduler API contracts, trigger endpoints, and backend cron execution logic remain unchanged.

## Task 1 — Failing Regression Tests

Create `frontend/app/(frame)/settings/__tests__/TuningScheduleHint.test.tsx`:
1. **Unit tests for `formatScheduleCadence`**:
   - `showDaysOfWeek = false` returns `"Runs at the configured time every day"` regardless of `daysOfWeek`.
   - `showDaysOfWeek = true` with `[5]` returns `"Runs at the configured time on Sat"`.
   - `showDaysOfWeek = true` with `[0, 2, 5]` returns `"Runs at the configured time on Mon, Wed, Sat"`.
   - `showDaysOfWeek = true` with all 7 days returns `"Runs at the configured time every day"`.
   - `showDaysOfWeek = true` with `[]` returns `"No active days selected"`.
   - Handles unsorted or duplicate inputs gracefully (e.g. `[5, 2, 0, 2]` -> `"Runs at the configured time on Mon, Wed, Sat"`).
   - Filters out out-of-range day numbers (`[-1, 0, 7]` -> `"Runs at the configured time on Mon"`).
2. **Integration / UI tests mounting SettingsPage**:
   - Mock `@/lib/api` (`getTuningSchedule`, `saveTuningSchedule`, `getTuningJobCount`, `getTuningJob`, etc.).
   - Mount `SettingsPage`, navigate to `Strategy Tuning`.
   - Verify initial display shows `"Runs at the configured time on Sat"` when backend returns `days_of_week: [5]`.
   - Re-mount with mock backend returning `days_of_week: [0, 2, 5]` and verify hint displays `"Runs at the configured time on Mon, Wed, Sat"`.
   - Interactively toggle weekday checkboxes (check Mon, Wed) and verify the hint text updates live to `"Runs at the configured time on Mon, Wed, Sat"`.
   - Navigate to `Data` section (where EDGAR and S&P 500 schedules reside) and verify their "Enable schedule" rows display `"Runs at the configured time every day"`.

## Task 2 — Implementation in Settings Page

1. In `frontend/app/(frame)/settings/page.tsx`:
   - Export helper `formatScheduleCadence(showDaysOfWeek: boolean, daysOfWeek: number[]): string`.
   - Update `ScheduleSection`'s "Enable schedule" `<Row>` hint prop to use `formatScheduleCadence(showDaysOfWeek, daysOfWeek)`.
2. Run typecheck: `npm run typecheck` (`tsc --noEmit`).
3. Run Jest tests: `npm run test -- --testPathPattern=TuningScheduleHint`.
4. Run all settings tests to verify no regressions: `npm run test -- --testPathPattern=settings`.

## Task 3 — State and Audit

1. Run adversarial plan audit using a fresh subagent with `bmad-review-adversarial-general` and record in `docs/superpowers/audits/APP-AUDIT-B-TUNING-HINT/plan-r1.md`.
2. Execute code implementation and tests.
3. Run adversarial code audit using a fresh subagent and record in `docs/superpowers/audits/APP-AUDIT-B-TUNING-HINT/code-r1.md`.
4. Update `docs/superpowers/PROJECT_STATE.json` with the new phase record and probe, verifying `python scripts/state.py` reports clean.
