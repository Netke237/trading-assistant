## Summary
Implements visible, actionable error and validation feedback for scheduled scan operations (invalid cadence, failed update, failed delete, and unresolvable profile selection) in Settings → Scan (#402, #431).

## Scope & Changes
- `frontend/app/(frame)/settings/page.tsx`:
  - `ScheduledScansSection`: `updateEntry` and `deleteEntry` return `{ ok: boolean; error?: string }` formatting error details instead of silently swallowing exceptions.
  - `ScheduleEntryRow`:
    - Validates cadence bounds (5–1440 min) and surfaces immediate error without submitting invalid numbers.
    - Captures `updateEntry` failures (e.g. 500 on label blur) and displays row-level error while retaining user draft.
    - Captures `deleteEntry` failures and displays row-level error.
    - Catches profile resolution errors (e.g. legacy profiles missing required fields) in profile dropdown, displays error message, and retains existing committed profile without PUT.
    - Renders `{rowError && <Text size={11} tone="reject">{rowError}</Text>}` with `data-testid="schedule-entry-error-<id>"`.
- `frontend/app/(frame)/settings/__tests__/ScheduleFeedback.test.tsx`:
  - 4 focused unit/component tests asserting all four feedback behaviors.
- `docs/superpowers/audits/APP-AUDIT-B-SCHEDULE-FEEDBACK/`:
  - `plan-r1.md`: Clean plan audit by independent subagent `386e77b8-f002-41fc-a753-1caa7dee65f1` (0 gate findings).
  - `code-r1.md`: Clean code audit by independent subagent `4a2a43d1-ba96-44d0-9ac8-baa4978a0b60` (0 gate findings).

## Audits & Verification
- Plan Audit: Round 1 clean (0 gate findings).
- Code Audit: Round 1 clean (0 gate findings).
- Frontend tests: 13/13 settings suites passed (88/88 tests).
- Typecheck: clean (`tsc --noEmit`).
- State: `python scripts/state.py` verified (0 drift).
