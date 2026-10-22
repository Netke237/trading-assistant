# Plan: APP-AUDIT-B-ORPHANED-SCHEDULE-PROFILE (#403)

**Phase ID:** `APP-AUDIT-B-ORPHANED-SCHEDULE-PROFILE`
**Issue:** #403 (remediation from #350)
**Scope:** Explicit display of orphaned/deleted profile reference in Settings Scheduled Scans instead of visually defaulting to an unrelated available profile.

---

## 1. Context & Problem Statement

In `frontend/app/(frame)/settings/page.tsx`, `ScheduleEntryRow` renders a `<select>` with options corresponding to `profiles` (filtered by the entry's mode):
```tsx
<select
  className={styles.input}
  value={entry.profile_id}
  onChange={...}
>
  {profiles.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
</select>
```

When a schedule's referenced `profile_id` has been deleted or is missing from `profiles` (e.g. `entry.profile_id === 'deleted-profile'`):
- The `<select>` element receives `value="deleted-profile"`.
- Because none of the `<option>` elements have `value="deleted-profile"`, the browser DOM automatically displays the *first* available `<option>` (e.g. "Audit options B").
- The underlying schedule entry and backend request still point to `deleted-profile`, but to the operator, the schedule falsely appears to be running "Audit options B".
- Furthermore, no warning or indication is given that the referenced profile is missing.

Expected:
- Explicitly display the unavailable/missing profile option with its stored identity (e.g. `${entry.profile_name || entry.profile_id} (missing)` or `${entry.profile_name || entry.profile_id} (unavailable)`).
- Keep this option selected in the controlled `<select>` until the operator deliberately reassigns it to an existing profile.
- Display a clear warning indicator (`Profile missing or deleted`) in the schedule row so the operator knows re-assignment is needed.
- No automatic mutation occurs: the stored schedule id and resolved request remain untouched until an explicit user selection is made.

---

## 2. Proposed Changes

### 2.1 Missing Profile Option in `ScheduleEntryRow` (`frontend/app/(frame)/settings/page.tsx`)
In `ScheduleEntryRow`:
```tsx
const isProfileMissing = Boolean(entry.profile_id) && !profiles.some((p) => p.id === entry.profile_id);
```
Inside the `<select>` element:
```tsx
<select
  className={styles.input}
  value={entry.profile_id}
  onChange={async (e) => {
    const p = profiles.find((pr) => pr.id === e.target.value);
    if (!p) return;
    try {
      const resolved = resolveProfileToScanRequest(p);
      await handleUpdate({
        profile_id: p.id,
        profile_name: p.name,
        profile_synced_at: new Date().toISOString(),
        resolved_request: resolved,
      });
    } catch (err) {
      setRowError(err instanceof Error ? err.message : 'Could not resolve selected profile into a scan request.');
    }
  }}
>
  {isProfileMissing && (
    <option value={entry.profile_id} disabled>
      {entry.profile_name || entry.profile_id} (missing)
    </option>
  )}
  {profiles.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
</select>
```

### 2.2 Warning Indicator in `rowLabel`
In `ScheduleEntryRow`:
```tsx
{isProfileMissing && (
  <Text size={11} tone="caution" className="schedule-missing-profile-warning">
    Profile missing or deleted — select an available profile to reassign.
  </Text>
)}
```

---

## 3. Numeric & Persistence Safety Gate Analysis
- **Wrong number on broker order?** No. This governs the display of saved profile identifiers in Settings. No broker orders or prices are generated.
- **Corrupted persisted data?** No. The missing option is rendered dynamically when `!profiles.some(...)`. It does not write to backend storage or mutate existing YAML state unless the operator deliberately chooses a different profile.

---

## 4. Verification Plan

### 4.1 Unit & Component Tests (`frontend/app/(frame)/settings/__tests__/OrphanedScheduleProfile.test.tsx`)
Create comprehensive tests covering:
1. `schedule-missing-profile-display`: When `entry.profile_id` is `'deleted-profile'` and `profiles` only contains `audit-options-b`:
   - Verify the select visibly displays the missing profile identity (`deleted-profile (missing)` or `${profile_name} (missing)`).
   - Verify the warning text "Profile missing or deleted" is displayed.
   - Verify `api.updateScanScheduleEntry` is NOT called upon mount.
2. Deliberate re-assignment:
   - When the user selects `audit-options-b` from the dropdown, `api.updateScanScheduleEntry` is called with `profile_id: 'audit-options-b'`.
   - The warning and missing option clear.

### 4.2 Automated Checks
- `npm run typecheck`
- `npm run test -- frontend/app/(frame)/settings/__tests__/OrphanedScheduleProfile.test.tsx`
- Run all settings tests: `npm run test -- frontend/app/(frame)/settings/__tests__/`
- `python scripts/state.py` (0 drift)
