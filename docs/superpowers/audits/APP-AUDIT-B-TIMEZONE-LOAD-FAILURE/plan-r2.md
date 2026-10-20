# Adversarial Audit Report: APP-AUDIT-B-TIMEZONE-LOAD-FAILURE Plan (Round 2)

**Target:** `docs/superpowers/plans/2026-10-20-app-audit-b-timezone-load-failure-plan.md`  
**Reviewer:** Independent adversarial subagent (`780e6d6c-3034-435f-ba0d-5a9ef1e75819`)  
**Scope:** Review of Round 1 fixes and their interactions:
1. Fix for `F-PLAN-TZ-1`: Not clearing `loadError` on invocation of `fetchTimezone`, keeping `loadError` visible and Save disabled (via `isSaveDisabled = saving || loading || (Boolean(loadError) && !isEdited)`) throughout retry flight until confirmed server data arrives.
2. Fix for `F-PLAN-TZ-2`: In `handleRetry`, explicitly resetting `isDirty.current = false` and `setIsEdited(false)` before triggering `fetchTimezone` so that user-initiated retry accepts the server timezone, while preserving race protection against subsequent typing during the flight.

Cross-checked against:
- `frontend/app/(frame)/settings/page.tsx` (lines 470–545)
- `frontend/app/(frame)/settings/__tests__/OperatorTimezoneSection.race.test.tsx`
- `docs/superpowers/audits/APP-AUDIT-B-TIMEZONE-LOAD-FAILURE/plan-r1.md`
- `docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/followup/settings-states/findings.md` (item 6)
- `docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/followup/settings-states/browser.mjs` (lines 123–126)
- `docs/superpowers/PROJECT_STATE.json`

---

## 1. Audit of Fix for F-PLAN-TZ-1

- **Mechanism:** On retry invocation, `loadError` is not cleared; it remains set to `'Failed to load timezone from server'` until `api.getSchedulingTimezone()` resolves successfully. In addition, `isSaveDisabled = saving || loading || (Boolean(loadError) && !isEdited)` locks the Save button throughout the retry flight.
- **Verification:**
  - While retry GET is in flight, `loadError` is truthy and `loading` is true. `isSaveDisabled` evaluates to `true`.
  - The Save button cannot be clicked during the network round trip. The unconfirmed draft cannot overwrite the server timezone.
  - If retry fails, `catch` preserves `loadError = 'Failed to load timezone from server'`, leaving Save disabled.
  - Only when retry GET resolves with confirmed server data does `setLoadError('')` clear the error and enable Save with the server-hydrated timezone.
- **Verdict:** F-PLAN-TZ-1 is cleanly fixed with zero gate-level defects.

---

## 2. Audit of Fix for F-PLAN-TZ-2

- **Mechanism:** In `handleRetry`, `isDirty.current = false` and `setIsEdited(false)` are set before dispatching `fetchTimezone(false)`.
- **Verification:**
  - If the user previously typed in the input and subsequently clicks "Retry" to discover the true server timezone, resetting `isDirty.current = false` ensures the incoming GET response is not skipped by `if (!cancelledRef.current && !isDirty.current)`. The input updates to the confirmed server timezone (`r.timezone`).
  - If the user begins typing *after* clicking Retry while the request is still in flight, `onChange` immediately runs `isDirty.current = true; setIsEdited(true);`, restoring the #372 race protection so late arrival of the GET response will not clobber the newly typed draft.
- **Verdict:** F-PLAN-TZ-2 is cleanly fixed with zero gate-level defects.

---

## 3. Interaction & Edge Case Analysis

The following interaction flows were traced against the gate criteria:
1. **Initial GET Failure → Retry → Success:**
   - Input starts with `Europe/Berlin`, `loadError` set, Save disabled.
   - User clicks Retry. `isDirty.current = false`, `isEdited = false`, `loading = true`. Save disabled.
   - GET succeeds with `Asia/Tokyo`. `tz` updates to `Asia/Tokyo`, `loadError` clears, Save enabled. No unconfirmed overwrite possible.
2. **Initial GET Failure → Edit → Retry → Subsequent Failure:**
   - User typed `America/New_York`. Clicks Retry.
   - `handleRetry` sets `isDirty.current = false`, `isEdited = false`.
   - Retry GET rejects (HTTP 503). `catch` sets `loadError = 'Failed to load timezone from server'`.
   - `isSaveDisabled` evaluates to `true` (since `loadError` is present and `!isEdited` is true).
   - Operator cannot save the unconfirmed value without an explicit new edit. Persisted data is protected.
3. **Initial GET Failure → Retry → Typing during Flight → Success:**
   - Operator clicks Retry. While GET is in flight, operator types `Europe/London`.
   - `onChange` sets `isDirty.current = true; setIsEdited(true);`.
   - Retry GET arrives with `Asia/Tokyo`. Because `isDirty.current` is true, `setTz('Asia/Tokyo')` is skipped, preserving `Europe/London`.
   - `loadError` is cleared, enabling Save. Operator can deliberately save their intended `Europe/London`.
4. **Broker Order & Numerical Impact:**
   - Operator timezone is strictly scoped to quiet off-hours maintenance schedules (EDGAR, nightly OHLCV ingestion, tuning). Real NYSE market trading and broker execution always use `America/New_York` regardless of operator timezone. No wrong number can reach a broker order or calculation.
5. **Project State & Test Probe Alignment:**
   - `data-testid="timezone-load-error"` satisfies `PROJECT_STATE.json`'s verify probe pattern `timezone-load-error` on `frontend/app/(frame)/settings/page.tsx`.
   - Text `'Failed to load timezone from server'` satisfies `browser.mjs` Playwright regex `/failed|unavailable|could not|unknown/i`.

---

GATE FINDINGS: 0
