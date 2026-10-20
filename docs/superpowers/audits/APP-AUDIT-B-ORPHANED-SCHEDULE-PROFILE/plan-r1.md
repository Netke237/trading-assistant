# Independent Adversarial Plan Audit: APP-AUDIT-B-ORPHANED-SCHEDULE-PROFILE (#403)

**Audited Plan:** `docs/superpowers/plans/2026-10-20-app-audit-b-orphaned-schedule-profile-plan.md`  
**Cross-checked Files:**
- `frontend/app/(frame)/settings/page.tsx` (lines 750–870)
- `docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/followup/settings-states/findings.md` (item 4)
- `docs/superpowers/PROJECT_STATE.json`
- `frontend/lib/searchProfilesStore.ts`
- `frontend/lib/scanScheduleResolve.ts`
- `backend/app/schemas/scan_schedule.py`
- `backend/app/services/scan_schedule_scheduler.py`

---

## Audit Evaluation Against the Numeric & Persistence Gate

### 1. Controlled `<select>` and Missing Option Behavior
- **Mechanism verified:** In `frontend/app/(frame)/settings/page.tsx` line 808, `<select className={styles.input} value={entry.profile_id}>` currently receives the stored schedule entry's `profile_id`. When that `profile_id` has been deleted from `profiles`, none of the child `<option>` elements match, causing Chromium/React DOM to fall back visually to the first rendered `<option>`.
- **Proposed fix:** Inserting `<option value={entry.profile_id} disabled>{entry.profile_name || entry.profile_id} (missing)</option>` when `isProfileMissing` is true ensures that the `<select value={entry.profile_id}>` has an exact value match. The browser displays the stored identity marked as `(missing)` rather than defaulting to an unrelated profile.
- **Safety check:** The option is marked `disabled`. React controlled components preserve the selected value on mount without triggering synthetic change events. No mutation or network calls (`api.updateScanScheduleEntry`) are dispatched on mount.

### 2. Mutation & Reassignment Paths
- **Unmutated state:** If the operator takes no action or edits other fields in the row (e.g., modifying `label`, `pattern`, or toggling `enabled`), `handleUpdate` patches only those fields; `entry.profile_id` and `entry.resolved_request` remain unchanged and intact in backend storage.
- **Reassignment:** When the operator deliberately selects an active profile from the dropdown, `onChange` invokes `resolveProfileToScanRequest(p)` and updates `profile_id`, `profile_name`, `profile_synced_at`, and `resolved_request`. If resolution fails (e.g. legacy profile), `setRowError` catches the error, no update is sent to the backend, and the row remains in its previous state with an error explanation.
- **Run now execution:** Scheduled scan execution (`_run_scheduled_entry` in `scan_schedule_scheduler.py`) runs `entry["resolved_request"]` directly and does not look up `profile_id` at runtime. Orphaned entries continue to run their last resolved request safely until explicitly reassigned.

### 3. Indicator Placement and Verification Probe
- **UI integration:** In `ScheduleEntryRow`, `styles.rowLabel` is a flex container (`flex-direction: column; gap: 2px`). Rendering `<Text size={11} tone="caution" className="schedule-missing-profile-warning">` fits cleanly beneath `defaultTag` and existing caution badges (`stale`, `scheduleRiskIgnored`).
- **`PROJECT_STATE.json` probe:** The verify probe pins `isProfileMissing` in `frontend/app/(frame)/settings/page.tsx`. Section 2.1 defines `const isProfileMissing = Boolean(entry.profile_id) && !profiles.some((p) => p.id === entry.profile_id);`, fully satisfying the presence probe.
- **Test coverage:** Section 4 defines component unit tests in `frontend/app/(frame)/settings/__tests__/OrphanedScheduleProfile.test.tsx` verifying display on mount without write, followed by deliberate reassignment, matching conventions in `ScheduleFeedback.test.tsx`.

---

GATE FINDINGS: 0.

Zero gate-level findings. The plan correctly addresses item 4 of the audit findings without introducing any mechanism misstatements, data corruption, or numeric leakage to broker orders or user-facing calculations.
