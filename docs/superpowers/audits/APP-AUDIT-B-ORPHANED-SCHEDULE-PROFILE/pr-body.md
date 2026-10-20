## Summary
Closes #403.
Fixes item 4 from `docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/followup/settings-states/findings.md`:
When a scheduled scan entry references a profile that was subsequently deleted from local storage, the select dropdown previously rendered the first available profile name visually while leaving `entry.profile_id` pointing to the deleted profile ID.

This change:
1. Detects orphaned profiles via `const isProfileMissing = Boolean(entry.profile_id) && !profiles.some((p) => p.id === entry.profile_id);`.
2. Explicitly renders a disabled fallback `<option value={entry.profile_id} disabled>{entry.profile_name || entry.profile_id} (missing)</option>` in the profile `<select>`.
3. Displays an explicit warning label `<Text size={11} tone="caution">Profile not found</Text>` below the select so the user is informed that the profile was removed and can pick a valid profile or delete the schedule entry.
4. Adds comprehensive unit tests in `frontend/app/(frame)/settings/__tests__/OrphanedScheduleProfile.test.tsx`.

## Verification
- `npm run test -- --testPathPattern=OrphanedScheduleProfile` (2/2 passing)
- `npm run test -- --testPathPattern="settings"` (12 test suites, 61 tests passing)
- `npm run typecheck` clean
- `python scripts/state.py` clean (0 drift)

## Preconditions for Self-Merge
- [x] Board issue: #403
- [x] Audit clean: true (Plan R1 clean, Code R1 clean)
- [x] Pre-merge CI: all checks green
- [x] Target is default branch (`main`)
- [x] Single commit / merge commit preserving audit trace
