# APP-AUDIT-B-TIMEZONE-RACE — protect operator timezone edit against late load response (#372)

Independent remediation phase from #350, user-authorized. Existing evidence and its review counters remain immutable. No broker routing, scheduling execution, orders, or unrelated settings are part of this fix.

## Goal

Prevent a late asynchronous GET response for `/settings/scheduling` from overwriting an in-progress operator edit or newly submitted save in `OperatorTimezoneSection` on the Settings page (`frontend/app/(frame)/settings/page.tsx`), and protect in-flight saves against concurrency desynchronization.

## Mechanism

`OperatorTimezoneSection` (`frontend/app/(frame)/settings/page.tsx:466-510`) mounts and calls `api.getSchedulingTimezone()`.
Its `.then((r) => setTz(r.timezone))` unconditionally calls `setTz` when the promise resolves.
If the operator types into the timezone input before the network response resolves, the resolving promise clobbers the operator's draft with the stale server response (e.g. `'Europe/Berlin'` overwriting `'America/New_York'`). Furthermore, if the operator edits or submits a save before the initial GET resolves, the late initial GET can clobber the newly saved value. If an operator clicks Save multiple times or edits while a save is in flight, out-of-order responses can desynchronize the UI from the backend.

### Repair

1. Track whether the draft has been edited or saved by the operator using a ref `isDirty = useRef(false)`.
2. In the input's `onChange`, set `isDirty.current = true` and update `tz`.
3. In `useEffect`, guard the initial GET resolution with `!isDirty.current` and an unmount cancellation flag (`let cancelled = false; ... return () => { cancelled = true; }`).
4. In `handleSave`:
   - Guard against concurrent re-entrant submissions with a `saving` state (`const [saving, setSaving] = useState(false); if (saving) return;`).
   - Mark `isDirty.current = true;` immediately so any late initial GET cannot overwrite the saved setting even if the operator clicked Save without modifying the field first.
   - Capture `const submittedTz = tz;`.
   - Await `api.putSchedulingTimezone(submittedTz)`.
   - On success, sync `tz` only if the draft was not further modified while the save was in flight:
     `setTz((current) => (current === submittedTz ? res.timezone : current));`
   - Display `'Saved'`.
   - On failure, display `'Save failed — check the timezone name'`.
   - Clear `saving` in `finally`.
5. In JSX:
   - Disable the Save button while saving (`disabled={saving}`).
6. If the initial GET fails, swallow cleanly via `.catch(() => {})` without altering the operator's draft.

## Task 1 — Failing regression tests for timezone race conditions

Create `frontend/app/(frame)/settings/__tests__/OperatorTimezoneSection.race.test.tsx`.
Following the pattern of `ScheduleEntryRow.zeroRisk.test.tsx`:
Mock `api.getSchedulingTimezone` and `api.putSchedulingTimezone` along with the sibling endpoints called during Settings page `Scan` section mount (`getScheduledScanRunRetention`, `getScanSchedule`, `getScanScheduleEntryRuns`, `getRiskSettings`, `saveRiskSettings`).

Test cases:
1. **Late initial GET after operator edit**:
   - Delay resolution of `api.getSchedulingTimezone`.
   - Render `SettingsPage`, navigate to `Scan` section.
   - Operator types `'America/New_York'`.
   - Resolve the initial GET with `{ timezone: 'Europe/Berlin' }`.
   - Assert the input value remains `'America/New_York'` (confirm RED on unfixed code where it reverts to `'Europe/Berlin'`).
2. **Slow initial GET without edit**:
   - Delay resolution of `api.getSchedulingTimezone`.
   - Render and navigate to `Scan`.
   - Resolve with `{ timezone: 'America/Chicago' }`.
   - Assert input hydrates to `'America/Chicago'`.
3. **Slow failed GET with operator edit**:
   - Delay rejection of `api.getSchedulingTimezone`.
   - Operator types `'Asia/Tokyo'`.
   - Reject the initial GET.
   - Assert input remains `'Asia/Tokyo'`.
4. **Edit and save before initial GET resolves**:
   - Delay resolution of initial `api.getSchedulingTimezone`.
   - Operator types `'America/New_York'` and clicks `Save`.
   - Verify `api.putSchedulingTimezone` is called with `'America/New_York'`.
   - Mock PUT to resolve with `{ timezone: 'America/New_York' }`.
   - Resolve the initial delayed GET with `{ timezone: 'Europe/Berlin' }`.
   - Assert input remains `'America/New_York'` and `'Saved'` confirmation appears.
5. **Save without prior typing before delayed initial GET resolves**:
   - Delay resolution of initial `api.getSchedulingTimezone`.
   - Operator clicks `Save` directly (submitting default `Europe/Berlin`).
   - Mock PUT to resolve with `{ timezone: 'Europe/Berlin' }`.
   - Resolve the delayed initial GET with `{ timezone: 'America/New_York' }`.
   - Assert input remains `'Europe/Berlin'` and is not clobbered by the late GET.
6. **Editing while save is in flight**:
   - Delay resolution of `api.putSchedulingTimezone`.
   - Operator clicks `Save` with `'America/Chicago'`.
   - While PUT is in flight, operator changes input to `'America/Phoenix'`.
   - Resolve PUT with `{ timezone: 'America/Chicago' }`.
   - Assert input remains `'America/Phoenix'` and is not overwritten by the older PUT response.
7. **Concurrency guard on Save button**:
   - While `api.putSchedulingTimezone` is in flight, assert Save button is disabled and rapid clicks do not trigger duplicate PUT requests.
8. **Unmount during initial GET**:
   - Render and unmount before `api.getSchedulingTimezone` resolves.
   - Resolve promise; assert no unhandled rejection or state update on unmounted component.

## Task 2 — Implement the fix in OperatorTimezoneSection

Modify `OperatorTimezoneSection` in `frontend/app/(frame)/settings/page.tsx`:
- Add `const isDirty = useRef(false);` and `const [saving, setSaving] = useState(false);`.
- In `useEffect`, add `let cancelled = false;`:
  ```tsx
  api.getSchedulingTimezone()
    .then((r) => {
      if (!cancelled && !isDirty.current) {
        setTz(r.timezone);
      }
    })
    .catch(() => {});
  return () => {
    cancelled = true;
  };
  ```
- In the `<input>` element:
  ```tsx
  onChange={(e) => {
    isDirty.current = true;
    setTz(e.target.value);
  }}
  ```
- In `handleSave`:
  ```tsx
  async function handleSave() {
    if (saving) return;
    setSaving(true);
    isDirty.current = true;
    const submittedTz = tz;
    setSaveResult('');
    try {
      const res = await api.putSchedulingTimezone(submittedTz);
      setTz((current) => (current === submittedTz ? res.timezone : current));
      setSaveResult('Saved');
    } catch {
      setSaveResult('Save failed — check the timezone name');
    } finally {
      setSaving(false);
      setTimeout(() => setSaveResult(''), 2500);
    }
  }
  ```
- In the Save button:
  ```tsx
  <button
    type="button"
    className={`${styles.btn} ${styles.btnPrimary}`}
    onClick={handleSave}
    disabled={saving}
  >
    Save
  </button>
  ```
- Run the regression tests and verify all pass (GREEN).

## Task 3 — Full suite validation

1. Run focused Jest tests:
   `npm test -- frontend/app/(frame)/settings/__tests__/OperatorTimezoneSection.race.test.tsx`
2. Run full frontend suite:
   `npm test`
3. Run TypeScript check:
   `npm run typecheck`
4. Run backend pytest suite with Python 3.11.

## Review and closure

- Fresh independent plan reviewer before code implementation;
- Fresh independent code reviewer on `main..HEAD` diff;
- 3-round cap per stage, numeric/persistence gate;
- Update `docs/superpowers/PROJECT_STATE.json` and release claim upon completion.
