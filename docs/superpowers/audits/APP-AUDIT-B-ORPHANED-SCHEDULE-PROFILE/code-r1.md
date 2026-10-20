# Independent Adversarial Code Audit: APP-AUDIT-B-ORPHANED-SCHEDULE-PROFILE (#403)

**Diff Reviewed:** `f7ef94c46d0da01c17052fa54ebe8ffb0bf34450..426d4a2c`  
**Plan:** `docs/superpowers/plans/2026-10-20-app-audit-b-orphaned-schedule-profile-plan.md`  
**Reviewer:** Independent adversarial subagent (`ab99bf76-8509-4fe3-bc8c-dc9194a8ebc8`)  
**Files Inspected:**
- `frontend/app/(frame)/settings/page.tsx`
- `frontend/app/(frame)/settings/__tests__/OrphanedScheduleProfile.test.tsx`
- `docs/superpowers/plans/2026-10-20-app-audit-b-orphaned-schedule-profile-plan.md`
- `docs/superpowers/PROJECT_STATE.json`

---

## 1. Scope & Mechanism Cross-Check

The diff addresses board issue #403 (remediation from #350):
When a scheduled scan entry references a `profile_id` that was deleted from local storage (or missing from the available mode-filtered profiles), the controlled `<select value={entry.profile_id}>` previously had no matching child `<option>`. Chromium and React DOM default visually to the first rendered `<option>`, misleading the operator into believing the schedule is mapped to an unrelated active profile.

The diff introduces:
1. `isProfileMissing = Boolean(entry.profile_id) && !profiles.some((p) => p.id === entry.profile_id)`
2. Warning display: `<Text size={11} tone="caution" className="schedule-missing-profile-warning">Profile missing or deleted — select an available profile to reassign.</Text>` in `styles.rowLabel`.
3. Disabled fallback `<option value={entry.profile_id} disabled>{entry.profile_name || entry.profile_id} (missing)</option>` at the top of the `<select>`.
4. Dedicated unit test suite `OrphanedScheduleProfile.test.tsx` verifying display on mount without update dispatch, followed by explicit reassignment.

---

## 2. Gate Verification & Adversarial Scenario Analysis

Under the project gate:
> A finding blocks only if it can put a WRONG NUMBER in front of a user or on a broker order, or CORRUPT PERSISTED DATA. A comment counts only if a competent reader acting on it would write a wrong change (it misstates mechanism).

### Concrete Scenarios Checked:

1. **Mount & No-Mutation Invariant:**
   - *Check:* Does mounting `<select value={entry.profile_id}>` with a disabled `<option value={entry.profile_id}>` trigger a synthetic React `onChange` or mutate backend storage?
   - *Finding:* React controlled `<select>` elements only trigger `onChange` on user interaction (DOM `change` event). On mount, `api.updateScanScheduleEntry` is not called (`expect(mockApi.updateScanScheduleEntry).not.toHaveBeenCalled()` confirmed passing). Stored YAML backend state remains pristine.

2. **Unrelated Field Edits on Orphaned Entry:**
   - *Check:* If the operator edits the schedule `label`, `fire_time`, `cadence_minutes`, or toggles `enabled` while the profile is orphaned, does `handleUpdate` clobber `profile_id`, `profile_name`, or `resolved_request`?
   - *Finding:* In `updateEntry(entry, patch)`, `next = { ...entry, ...patch }`. Unmodified fields retain their existing values (`next.profile_id`, `next.profile_name`, `next.resolved_request`). The backend receives the original values. No data corruption occurs.

3. **Runtime Execution & Scheduled Firing:**
   - *Check:* Does scheduled scan execution in `backend/app/services/scan_schedule_scheduler.py` rely on `profile_id` being present in frontend storage?
   - *Finding:* No. Scheduled scans execute `entry["resolved_request"]` directly via `ScanRequest.model_validate(entry["resolved_request"])` (options) and `StockScanRequest.model_validate(...)` (stocks). Orphaned entries continue executing their frozen resolved request safely until explicitly re-pointed or deleted.

4. **Mode Mismatches:**
   - *Check:* If an options entry references a profile whose mode was changed to stocks (or vice versa), what happens?
   - *Finding:* In `ScheduleSection`, `profiles` is passed as `profiles.filter((p) => p.mode === entry.mode)`. If the profile mode does not match, `profiles.some((p) => p.id === entry.profile_id)` evaluates to `false`, correctly setting `isProfileMissing = true`. The UI prevents assigning an incompatible mode profile.

5. **Empty Profiles Collection:**
   - *Check:* If all saved profiles are deleted (`profiles = []`), does the component crash or corrupt data?
   - *Finding:* `!profiles.some(...)` evaluates to `true`. `isProfileMissing` is `true`. The select cleanly renders only the disabled option, and the warning text renders without exception.

6. **Missing Name Fallback:**
   - *Check:* If `entry.profile_name` is empty or undefined, does the UI show `undefined (missing)`?
   - *Finding:* `entry.profile_name || entry.profile_id` properly falls back to `entry.profile_id`.

7. **Reassignment Path:**
   - *Check:* When reassigned to an available profile, does `resolveProfileToScanRequest` resolve the profile into a valid request body and update the backend? If resolution fails, is error state handled?
   - *Finding:* In `onChange`, `resolveProfileToScanRequest(p)` resolves the profile. If resolution throws, `setRowError` catches the error, no update is dispatched to the backend, and the row displays the rejection. If successful, `handleUpdate` updates `profile_id`, `profile_name`, `profile_synced_at`, and `resolved_request`.

8. **Presence Probes & System State:**
   - *Check:* `PROJECT_STATE.json` pins `isProfileMissing` in `frontend/app/(frame)/settings/page.tsx`.
   - *Finding:* Present at line 773. `python scripts/state.py` verified with 0 drift.

9. **Automated Verification:**
   - `npm run typecheck`: clean (exit code 0).
   - `npm run test -- OrphanedScheduleProfile`: 2/2 tests PASS.
   - `npm run test -- "settings/__tests__"`: 12 suites, 61 tests PASS.

---

## 3. Audit Gate Summary

GATE FINDINGS: 0.

Zero gate-level findings. The change reliably eliminates visual misrepresentation of orphaned schedule profiles without causing unsolicited data mutations, numeric leakage to broker orders, or persisted data corruption.
