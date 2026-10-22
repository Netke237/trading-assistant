# Plan: APP-AUDIT-B-SCHEDULE-FEEDBACK (#402)

**Phase ID:** `APP-AUDIT-B-SCHEDULE-FEEDBACK`
**Issue:** #402 (remediation from #350)
**Scope:** Visible, actionable error and validation feedback for scheduled scan operations (invalid cadence, failed update, failed delete, and unresolvable profile selection) in Settings → Scan.

---

## 1. Context & Problem Statement

In `frontend/app/(frame)/settings/page.tsx`, scheduled scans are configured in `ScheduledScansSection` and individual rows are rendered by `ScheduleEntryRow`.

Four failure modes currently occur silently without user-facing explanation:
1. **Invalid cadence input:**
   - Entering an invalid loop cadence (e.g., 0 or < 5) either silently snaps back to the prior value or fails on backend schema validation without an error message explaining why the cadence was rejected.
2. **Schedule update HTTP failure (e.g. 500 on label blur):**
   - In `updateEntry`, exceptions from `api.updateScanScheduleEntry` are caught and swallowed (`// Leave the list stale rather than silently reverting the UI's optimistic value.`).
   - The user sees their typed draft (e.g., "Failed draft") but receives no feedback that the save failed, leading to false confidence until remount/reload reverts it.
3. **Schedule delete HTTP failure (e.g. 500 on delete):**
   - In `deleteEntry`, exceptions from `api.deleteScanScheduleEntry` are swallowed with `/* best-effort */`.
   - The row remains and no explanation is provided.
4. **Unresolvable profile selection:**
   - In `ScheduleEntryRow`, selecting a profile that cannot resolve (e.g., an incomplete/legacy profile throwing in `resolveProfileToScanRequest`) silently catches and discards the exception (`/* leave entry pointed at old profile if this one can't resolve yet */`).
   - No explanation is presented explaining why the selected profile cannot resolve.

Expected:
- Explain every failed operation or unresolvable profile.
- Surface error messages at the row level without corrupting persisted state.
- Keep the prior committed record intact while clearly indicating any unsaved draft.
- Provide clear recovery/retry upon user correction.

---

## 2. Proposed Changes

### 2.1 Error Handling in `ScheduledScansSection` (`frontend/app/(frame)/settings/page.tsx`)
- Update `updateEntry` to return `Promise<{ ok: boolean; error?: string }>`:
  - If `api.updateScanScheduleEntry` succeeds, call `void refresh()` and return `{ ok: true }`.
  - If it fails, capture `err.message` (or standard fallback `'Could not update schedule entry — check backend is reachable.'`) and return `{ ok: false, error }`.
- Update `deleteEntry` to return `Promise<{ ok: boolean; error?: string }>`:
  - If `api.deleteScanScheduleEntry` succeeds, call `void refresh()` and return `{ ok: true }`.
  - If it fails, return `{ ok: false, error: 'Could not delete schedule entry — check backend is reachable.' }`.

### 2.2 Row-Level Error & Validation State in `ScheduleEntryRow`
- Introduce `rowError` state (`const [rowError, setRowError] = useState<string>('');`).
- For profile selection:
  ```ts
  onChange={async (e) => {
    const p = profiles.find((pr) => pr.id === e.target.value);
    if (!p) return;
    try {
      const resolved = resolveProfileToScanRequest(p);
      const res = await onUpdate({
        profile_id: p.id,
        profile_name: p.name,
        profile_synced_at: new Date().toISOString(),
        resolved_request: resolved,
      });
      if (!res.ok) {
        setRowError(res.error || 'Could not update schedule profile.');
      } else {
        setRowError('');
      }
    } catch (err) {
      setRowError(err instanceof Error ? err.message : 'Could not resolve selected profile into a scan request.');
    }
  }}
  ```
- For label edit:
  - On blur, if `label !== entry.label`:
    - Call `await onUpdate({ label })`.
    - If `!res.ok`, set `rowError` to indicate the save failed and the draft is unsaved.
    - If user edits `label` again, clear the previous error.
- For cadence edit:
  - Validate client-side bounds (`val < 5 || val > 1440`): display `'Cadence must be between 5 and 1440 minutes.'` immediately and do not submit invalid numbers.
  - If submission fails, display the returned error.
- For delete:
  - When delete fails, set `rowError` to `'Could not delete schedule entry — check backend is reachable.'`.
- Rendering:
  - Render `{rowError && <Text size={11} tone="reject">{rowError}</Text>}` clearly below or beside the row controls so the user sees the error immediately.

---

## 3. Numeric & Persistence Safety Gate Analysis
- **Wrong number on broker order?** No. Scheduled scan settings configure local schedule intervals and profile pointers. No broker orders or prices are generated here.
- **Corrupted persisted data?** No. On failure, prior committed records are preserved, and no partial or corrupt state is written to the API or localStorage.

---

## 4. Verification Plan

### 4.1 Unit & Component Tests (`frontend/app/(frame)/settings/__tests__/ScheduleFeedback.test.tsx`)
Create comprehensive tests covering:
1. `schedule-invalid-cadence-feedback`: Entering cadence 0 or < 5 displays validation error and does not mutate backend.
2. `schedule-update-failure-feedback`: Rejected label update (mock 500) displays error message and preserves unpersisted draft status.
3. `schedule-delete-failure-feedback`: Rejected delete (mock 500) displays error message and retains entry in view.
4. `schedule-legacy-profile-refusal`: Selecting an unresolvable profile displays error message and preserves prior committed entry without PUT.
5. Successful retry/recovery: Updating input after failure clears the error.

### 4.2 Automated Checks
- `npm run typecheck`
- `npm run test -- frontend/app/(frame)/settings/__tests__/ScheduleFeedback.test.tsx`
- Run all settings tests: `npm run test -- frontend/app/(frame)/settings/__tests__/`
- `python scripts/state.py` (0 drift)
