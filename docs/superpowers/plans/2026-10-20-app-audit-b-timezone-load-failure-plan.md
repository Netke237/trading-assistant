# Implementation Plan: APP-AUDIT-B-TIMEZONE-LOAD-FAILURE (#404)

**Phase ID:** `APP-AUDIT-B-TIMEZONE-LOAD-FAILURE`  
**Issue:** #404 (remediation from #350, findings.md item 6)  
**Branch:** `board/app-audit-b-timezone-load-failure-29331b34`  
**Touches:** `frontend/app/(frame)/settings/page.tsx`

---

## 1. Problem Statement

In `frontend/app/(frame)/settings/page.tsx`, `OperatorTimezoneSection` manages readback and configuration of the operator timezone via `api.getSchedulingTimezone()` and `api.putSchedulingTimezone()`.

On initial mount:
- `tz` state is initialized to `'Europe/Berlin'` as a fallback default.
- `useEffect` invokes `api.getSchedulingTimezone()`.
- If the initial GET request fails (e.g. HTTP 503, 500, or network offline), the rejection is completely swallowed in `.catch(() => {})`.
- The UI leaves the input displaying `Europe/Berlin` with no error, loading, or unavailable marker.
- The operator cannot distinguish whether `Europe/Berlin` is the confirmed stored timezone on the server or an unconfirmed local draft, risking inadvertent saves that overwrite a different stored timezone (e.g. `Asia/Tokyo`).
- Furthermore, the Playwright validation probe in `docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/followup/settings-states/browser.mjs` checks:
  ```javascript
  check('timezone-initial-get-failure', 'ui', 'initial failure visibly distinguishes default draft from unknown stored timezone', ..., /failed|unavailable|could not|unknown/i.test(await tzrow.innerText()));
  ```
  which failed because `tzrow.innerText` displayed only `Timezone ... Default: Europe/Berlin Save`.

---

## 2. Proposed Changes

### 2.1 State & Logic in `OperatorTimezoneSection` (`page.tsx`)

1. **Explicit Load Error & Loading States:**
   - Add `const [loadError, setLoadError] = useState('');`
   - Add `const [loading, setLoading] = useState(false);`
   - Add `const [isEdited, setIsEdited] = useState(false);`
   - Maintain `const isDirty = useRef(false);` for race condition safety (#372).

2. **Isolated Fetch Function (`fetchTimezone`):**
   - Encapsulate the GET call in a reusable function called on initial mount and via user retry:
     ```ts
     async function fetchTimezone(isMount = false) {
       setLoading(true);
       // Note (F-PLAN-TZ-1 fix): Do NOT clear loadError on invocation.
       // Keep loadError visible and Save protected until confirmed data arrives.
       try {
         const r = await api.getSchedulingTimezone();
         if (!cancelledRef.current && !isDirty.current) {
           setTz(r.timezone);
         }
         if (!cancelledRef.current) {
           setLoadError('');
         }
       } catch {
         if (!cancelledRef.current) {
           setLoadError('Failed to load timezone from server');
         }
       } finally {
         if (!cancelledRef.current) {
           setLoading(false);
         }
       }
     }
     ```

3. **Protection Against Inadvertent Overwrite & Safe Retry:**
   - When `loadError` is present and the operator has not touched the input (`!isEdited`), the `Save` button is disabled. Furthermore, while `saving` or `loading` is in flight, `Save` is disabled:
     ```ts
     const isSaveDisabled = saving || loading || (Boolean(loadError) && !isEdited);
     ```
     `<button disabled={isSaveDisabled}>Save</button>`
   - Once the operator types in the input (`onChange`), `isDirty.current = true; setIsEdited(true);`, enabling `Save` for an explicit, informed edit.
   - When `loadError` is present, render a "Retry" button:
     `<button type="button" className={styles.btn} onClick={handleRetry} disabled={loading}>Retry</button>`
   - **User Retry Handler (`handleRetry`) (F-PLAN-TZ-2 fix):**
     When the operator explicitly clicks "Retry", they are intentionally requesting to view the server's configured timezone. Reset dirty and edited flags so the incoming response is accepted:
     ```ts
     function handleRetry() {
       isDirty.current = false;
       setIsEdited(false);
       void fetchTimezone(false);
     }
     ```
     If the operator begins typing *after* clicking Retry while the request is in flight, `onChange` immediately sets `isDirty.current = true; setIsEdited(true);`, preserving the #372 protection against concurrent clobbering.
   - Render the error message:
     `{loadError && <Text size={11} tone="reject" data-testid="timezone-load-error">{loadError}</Text>}`

4. **Preserve All #372 Race Condition Protections:**
   - Late GET resolving after operator typing still checks `!isDirty.current` and does not clobber edits.
   - `handleSave` sets `isDirty.current = true` at start.
   - `putSchedulingTimezone` resolution checks `current === submittedTz`.
   - Saving lock (`saving`) remains active during PUT.
   - Successful save clears `loadError`.

---

## 3. The Project Gate (Numeric / Data Integrity)

- **Wrong number on broker order:** No broker order uses the operator scheduling timezone (real NYSE market orders use America/New_York regardless).
- **Persisted data corruption:** Distinguishing a failed readback prevents the operator from unwittingly saving `Europe/Berlin` over an existing stored server timezone (`Asia/Tokyo`) during transient network / server 503 issues.
- **Race conditions:** Preserves all 8 verified race invariants from commit `e80e8341` (#372), while closing in-flight retry overwrite (`F-PLAN-TZ-1`) and retry discard (`F-PLAN-TZ-2`).

---

## 4. Acceptance Criteria & Test Plan

1. **Unit Test Suite (`OperatorTimezoneSection.loadFailure.test.tsx`):**
   - **Case 1 (Initial GET failure):** Initial GET rejects with 503. Row visibly displays `"Failed to load timezone from server"`. Save button is disabled while unedited.
   - **Case 2 (Informed edit after failure):** Operator edits input. Save button becomes enabled. Clicking Save calls `putSchedulingTimezone` with the edited value.
   - **Case 3 (Retry after failure):** Operator clicks Retry. During retry flight, Save remains disabled. When subsequent GET succeeds with `"Asia/Tokyo"`, input updates to `"Asia/Tokyo"`, error message disappears, Save button is enabled.
   - **Case 4 (Retry after prior typing):** Operator typed in field, then clicked Retry. Retry succeeds with `"Asia/Tokyo"`. Input updates to `"Asia/Tokyo"` (resolving F-PLAN-TZ-2).
   - **Case 5 (Typing during retry flight):** Operator clicks Retry, then types while GET is in flight. Server response does not clobber active draft.
   - **Case 6 (Save clearing error):** After editing following GET failure, successful PUT clears `loadError` and displays `"Saved"`.
2. **Regression Invariant:**
   - All 8 existing tests in `OperatorTimezoneSection.race.test.tsx` continue to pass without regression.
   - `npm run typecheck` clean.
   - `python scripts/state.py` clean (0 drift).
