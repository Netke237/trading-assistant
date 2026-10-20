# Adversarial Code Audit Report: APP-AUDIT-B-TIMEZONE-LOAD-FAILURE (#404)

**Review Target:** Diff between `origin/main` (`1d9b5b8e7d6df35c742f5899c3630cc9c087af9a`) and `HEAD` (`dbd5a475`), cross-checked against implementation plan `docs/superpowers/plans/2026-10-20-app-audit-b-timezone-load-failure-plan.md`.
**Reviewer:** Independent adversarial subagent (`68cfc30b-1020-48b1-ade1-d862c0c7d159`)

**Files Inspected:**
- `frontend/app/(frame)/settings/page.tsx` (lines 475–585, `OperatorTimezoneSection`)
- `frontend/app/(frame)/settings/__tests__/OperatorTimezoneSection.loadFailure.test.tsx`
- `frontend/app/(frame)/settings/__tests__/OperatorTimezoneSection.race.test.tsx`
- `docs/superpowers/plans/2026-10-20-app-audit-b-timezone-load-failure-plan.md`
- `docs/superpowers/PROJECT_STATE.json`

---

### The Gate Assessment

A finding blocks only if it can put a **WRONG NUMBER in front of a user or on a broker order**, or **CORRUPT PERSISTED DATA**. A comment counts only if a competent reader acting on it would write a wrong change (it misstates mechanism).

---

### Scenarios Analyzed & Traced

1. **Initial GET Failure & Default Protection (`settings/page.tsx:483-502, 537`):**
   - When `api.getSchedulingTimezone()` fails (e.g. HTTP 500/503 or offline), `.catch()` sets `loadError = 'Failed to load timezone from server'`.
   - `isEdited` remains `false`.
   - `isSaveDisabled = saving || (Boolean(loadError) && !isEdited)` evaluates to `true`.
   - The Save button is disabled in the DOM, and `handleSave()` guards with `if (saving || (Boolean(loadError) && !isEdited)) return;`.
   - The unconfirmed fallback default (`Europe/Berlin`) cannot be saved over a different server timezone (`Asia/Tokyo`). Persisted data cannot be corrupted on initial readback failure.

2. **Informed Edit After Load Failure (`settings/page.tsx:550-555`):**
   - When the operator edits the input, `onChange` sets `isDirty.current = true; setIsEdited(true);`.
   - `isSaveDisabled` evaluates to `false`, enabling Save for a deliberate edit.
   - On clicking Save, `submittedTz` is sent via `api.putSchedulingTimezone(submittedTz)`.
   - On resolution, `setSaveResult('Saved')` and `setLoadError('')` clear the error marker and retry button.

3. **In-Flight Retry Locking (`settings/page.tsx:504-516`):**
   - When Retry is clicked, `handleRetry` sets `isDirty.current = false` and `setIsEdited(false)`.
   - Critically (per plan finding `F-PLAN-TZ-1`), `loadError` is **not** cleared on invocation. It remains `'Failed to load timezone from server'`.
   - Because `loadError` remains truthy and `!isEdited` is `true`, `isSaveDisabled` evaluates to `true` throughout the retry flight.
   - The Save button remains disabled during the network round trip, preventing unconfirmed drafts from overwriting server data.

4. **Retry After Operator Edit (`settings/page.tsx:505-510`):**
   - If an operator typed in the field and subsequently decides to click Retry to inspect what the server actually holds, `handleRetry` resets `isDirty.current = false`.
   - When the retry GET resolves, `if (!isDirty.current)` evaluates to `true`, successfully updating `tz` to `r.timezone` (`Asia/Tokyo`) and clearing the error (resolving plan finding `F-PLAN-TZ-2`).

5. **Typing Race During Retry Flight (`settings/page.tsx:508-510, 552`):**
   - If the operator starts typing *after* clicking Retry while the request is in flight, `onChange` immediately sets `isDirty.current = true`.
   - When the late retry GET response arrives, `if (!isDirty.current)` skips `setTz`, preserving the operator's active draft.

6. **Interaction With #372 Race Condition Invariants:**
   - All 8 race invariant tests in `OperatorTimezoneSection.race.test.tsx` were run and passed cleanly.
   - Late GET after typing, late GET after save, delayed GET with unchanged default (Test 5), and unmount safety remain intact.

7. **Broker Order and Numerical Impact:**
   - Operator timezone is strictly scoped to local maintenance jobs (EDGAR prefetch, nightly OHLCV ingestion, tuning). NYSE market trading and broker execution always use `America/New_York` regardless of this setting. No broker order calculation or number is touched.

8. **Automated Verification:**
   - Jest settings suite: 15 passed, 15 total (95 tests passed, including all 5 new loadFailure tests and all 8 race tests).
   - TypeScript: `tsc --noEmit` exited 0.
   - Project state: `python scripts/state.py` verified 0 drift and matched `timezone-load-error` probe.

---

GATE FINDINGS: 0
