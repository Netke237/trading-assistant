# Adversarial Audit Report: APP-AUDIT-B-TIMEZONE-LOAD-FAILURE Plan (Round 1)

**Target:** `docs/superpowers/plans/2026-10-20-app-audit-b-timezone-load-failure-plan.md`  
**Reviewer:** Independent adversarial subagent (`58a496d3-9929-4283-8453-94e3a0be0dd7`)  
**Cross-checked against:**
- `frontend/app/(frame)/settings/page.tsx` (lines 470–545)
- `frontend/app/(frame)/settings/__tests__/OperatorTimezoneSection.race.test.tsx`
- `docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/followup/settings-states/findings.md` (item 6)
- `docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/followup/settings-states/browser.mjs` (lines 123–126)
- `docs/superpowers/PROJECT_STATE.json`

---

### Finding 1: Clearing `loadError` on invocation prematurely unlocks Save during Retry, allowing unconfirmed default to overwrite server timezone

- **ID:** `F-PLAN-TZ-1`
- **Location:** `docs/superpowers/plans/2026-10-20-app-audit-b-timezone-load-failure-plan.md:40-42`, `52-53`
- **Concrete failing scenario:**
  1. Backend has `Asia/Tokyo` persisted in `settings.yaml`.
  2. User navigates to Settings → Scan. Initial `api.getSchedulingTimezone()` fails (e.g., HTTP 503 or transient network failure).
  3. Per Section 2.1 Point 2 & 3, the UI displays `Europe/Berlin`, shows error `"Failed to load timezone from server"`, and disables the Save button via `disabled={saving || (Boolean(loadError) && !isEdited)}` because `Boolean(loadError)` is true and `!isEdited` is true.
  4. Operator clicks the "Retry" button.
  5. Per Section 2.1 Point 2: On invocation of `fetchTimezone`, the plan executes:
     ```ts
     setLoading(true);
     setLoadError('');
     ```
  6. While the retry GET request is in flight over the network (e.g., 500ms–2s), `loadError` is now `''` (falsy).
  7. The Save button condition `disabled={saving || (Boolean(loadError) && !isEdited)}` evaluates to `false` because `Boolean(loadError)` is `false`. The Save button becomes active/enabled, and the error message disappears.
  8. The operator clicks the active "Save" button while the retry request is still in flight.
  9. `handleSave` executes, sending `Europe/Berlin` to `api.putSchedulingTimezone('Europe/Berlin')` and setting `isDirty.current = true`.
  10. Backend receives the PUT and overwrites `settings.yaml` scheduling timezone (`Asia/Tokyo`) with `Europe/Berlin`.
  11. When the delayed Retry GET response returns with `{ timezone: 'Asia/Tokyo' }`, `isDirty.current` is already true, so the server response is discarded.
- **Why it meets the gate:**
  Directly **CORRUPTS PERSISTED DATA** (`settings.yaml` on the server). The explicit purpose of #404 (and findings.md item 6) is to ensure saving an unconfirmed default requires a deliberate, informed edit. Prematurely clearing `loadError` on invocation of retry drops this protection during the in-flight network round-trip.
- **Suggested fix:**
  Do not clear `loadError` on invocation of `fetchTimezone`. Keep `loadError` set until the fetch actually succeeds (clear `loadError` only in the success handler `r => { ... setLoadError(''); }`). This keeps the Save button disabled and the error/retry indication visible throughout the in-flight retry until confirmed data arrives.

---

### Finding 2: Reusing `!isDirty.current` on user-initiated Retry silently discards server response if operator edited input, presenting wrong data and causing save corruption

- **ID:** `F-PLAN-TZ-2`
- **Location:** `docs/superpowers/plans/2026-10-20-app-audit-b-timezone-load-failure-plan.md:43-45`, `54-56`
- **Concrete failing scenario:**
  1. Backend has `Asia/Tokyo` stored in `settings.yaml`.
  2. Initial GET fails (HTTP 503). UI shows input `Europe/Berlin`, error message `"Failed to load timezone from server"`, and Retry button.
  3. Operator clicks the input and types (e.g., changes to `Europe/London`, or types/backspaces a character). `onChange` executes:
     ```ts
     isDirty.current = true;
     setIsEdited(true);
     ```
  4. Operator is uncertain what timezone was originally configured on the server and clicks "Retry" to fetch the stored server value.
  5. Retry GET succeeds, returning `{ timezone: 'Asia/Tokyo' }`.
  6. Per Section 2.1 Point 2: The success handler runs:
     ```ts
     if (!cancelled && !isDirty.current) {
       setTz(r.timezone);
     }
     setLoadError('');
     ```
  7. Because `isDirty.current` was set to `true` by the prior typing, `!isDirty.current` evaluates to `false`. `setTz` IS SKIPPED. The input remains `Europe/London`.
  8. `setLoadError('')` runs, clearing the error message and removing the Retry button.
  9. The operator sees `Europe/London` with no error message and no retry button, falsely believing that `Europe/London` was what the server returned.
  10. Operator clicks Save. `api.putSchedulingTimezone('Europe/London')` is sent, overwriting `Asia/Tokyo` on the server.
- **Why it meets the gate:**
  Presents **WRONG DATA** in front of the user (falsely representing unconfirmed draft text as the server's confirmed response) and directly leads to **CORRUPTING PERSISTED DATA** on the server. In #372, `!isDirty.current` was added solely to prevent a slow *initial mount* GET from clobbering concurrent user edits. Reusing `!isDirty.current` for explicit, user-initiated Retry without resetting `isDirty.current` causes any Retry after editing to be a silent no-op that discards the server's response.
- **Suggested fix:**
  When the user initiates a Retry, explicitly reset dirty and edited state (`isDirty.current = false; setIsEdited(false);`) so the incoming server response can update `tz`. Any typing performed *after* clicking Retry while the fetch is in flight will set `isDirty.current = true` and continue to be protected against race clobbering.

---

### What was checked to reach this count:
1. `OperatorTimezoneSection` in `frontend/app/(frame)/settings/page.tsx` (lines 470–545): verified existing state, `handleSave` PUT behavior, `useRef(false)` lifecycle, and `defaultValue="Europe/Berlin"`.
2. `OperatorTimezoneSection.race.test.tsx` (all 8 tests): verified that initial mount requires Save not to be unconditionally disabled on initial mount (Test 5), and verified test selectors (`row.querySelector('button')`).
3. `browser.mjs` lines 123–126: verified Playwright assertions on initial failure text matching `/failed|unavailable|could not|unknown/i` and pending unmount/remount persistence checks.
4. `findings.md` item 6: confirmed the defect scope and requirement that saving an unconfirmed default must require a deliberate informed edit.
5. `PROJECT_STATE.json`: verified verify probe `timezone-load-error` matches `data-testid="timezone-load-error"`.

GATE FINDINGS: 2
