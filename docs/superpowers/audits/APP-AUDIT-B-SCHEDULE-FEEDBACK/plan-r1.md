# Independent Adversarial Audit Report: APP-AUDIT-B-SCHEDULE-FEEDBACK Plan (#402)

**Reviewed Artifact:** `docs/superpowers/plans/2026-10-20-app-audit-b-schedule-feedback-plan.md`
**Checked Against:**
- `frontend/app/(frame)/settings/page.tsx` (lines 620–860)
- `frontend/lib/api.ts` (lines 61–78, 100–122, 1006–1016)
- `docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/followup/settings-states/findings.md` (items 3 and 5)
- `docs/superpowers/PROJECT_STATE.json` (`APP-AUDIT-B-SCHEDULE-FEEDBACK` record and verify probe)
- `backend/app/schemas/scan_schedule.py` & `backend/app/routers/scan_schedule.py`
- Test assertions in `docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/followup/settings-states/browser.mjs`

---

## Audit Scope & Verification

I conducted an adversarial examination of the plan against the numeric and persistence safety gate:
*A finding blocks only if it can put a WRONG NUMBER in front of a user or on a broker order, or CORRUPT PERSISTED DATA. A comment counts only if a competent reader acting on it would write a wrong change (it misstates mechanism).*

### 1. Concrete Scenarios Evaluated

1. **Cadence Input & Validation (`val < 5 || val > 1440`):**
   - *Scenario:* User enters `0`, `< 5`, or `> 1440` (addressing findings item 3 and `schedule-invalid-cadence-feedback`).
   - *Verification:* The plan specifies client-side bounds checking refusing submission of out-of-bounds cadence values and surfacing an immediate rejection message (`'Cadence must be between 5 and 1440 minutes.'`). Even if submitted, backend Pydantic schema `ScanScheduleEntryCreate` enforces `ge=5, le=1440`, returning HTTP 422 which `updateEntry` now catches and formats via `apiError` detail. The prior committed valid cadence (e.g. 35) in YAML storage is never overwritten with an invalid number.
   - *Verdict:* Safe. No invalid number is persisted or emitted to broker systems.

2. **Unresolvable Profile Selection:**
   - *Scenario:* User selects a legacy/synthetic profile lacking required fields (`fundamentalsGate`/`spreads` in options mode or `strategy` in stocks mode, addressing findings item 5 and `schedule-legacy-profile-refusal`).
   - *Verification:* `resolveProfileToScanRequest` throws an explicit error (`"cannot resolve..."`). The plan catches this in `ScheduleEntryRow.onChange`, sets `rowError` from `err.message`, and prevents `onUpdate` from dispatching. The schedule entry in backend YAML and in the parent state remains pointed at the existing valid profile and existing resolved request (`schedule-legacy-profile-no-write` preserved).
   - *Verdict:* Safe. Persisted schedule data is not mutated or corrupted.

3. **Schedule Update HTTP Failure (e.g., 500 on label blur):**
   - *Scenario:* User edits `label` (e.g. "Failed draft") and blurs while backend returns HTTP 500 (`schedule-update-failure-feedback`).
   - *Verification:* `updateEntry` returns `{ ok: false, error }`, `ScheduleEntryRow` surfaces the failure message beside/below the row, and `entries` in `ScheduledScansSection` is not updated with unconfirmed data. The server ledger retains the previous committed record ("Renamed fixed"), which correctly restores upon remount.
   - *Verdict:* Safe. No false confidence or corrupted state.

4. **Schedule Delete HTTP Failure (e.g., 500 on delete):**
   - *Scenario:* User clicks "Delete" while backend returns HTTP 500 (`schedule-delete-failure-feedback`).
   - *Verification:* `deleteEntry` catches the error, returns `{ ok: false, error }`, and `ScheduleEntryRow` displays the failure. The row is retained in UI and in the backend store. Subsequent retry can succeed and cleanly unmount the row upon `void refresh()`.
   - *Verdict:* Safe. No data is lost or prematurely pruned.

5. **Broker & Financial Safety:**
   - Scheduled scan settings configure local trigger times, intervals, and scan request bodies. They do not generate orders, calculate position sizing, or route broker transactions.
   - *Verdict:* No broker numbers or financial metrics are touched.

6. **State & Mechanism Accuracy:**
   - All citations to `page.tsx` code lines, swallowed exception comments (`// Leave the list stale...`, `/* best-effort */`, `/* leave entry pointed at old profile... */`), and API contract signatures accurately state existing mechanism without misleading an implementer.
   - *Implementation Anchor Note (Informational, non-gating):* `PROJECT_STATE.json` specifies `"pattern": "schedule-entry-error"` for `APP-AUDIT-B-SCHEDULE-FEEDBACK`'s verify probe. The implementer should ensure the rendered error element includes `data-testid="schedule-entry-error"` or `className="schedule-entry-error"` to satisfy `scripts/state.py` presence verification.

---

GATE FINDINGS: 0
