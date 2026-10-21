# Independent Adversarial Audit Report: Plan `APP-AUDIT-B-PROFILE-WRITE-FAILURE` (#398)

- **Target Plan**: `docs/superpowers/plans/2026-10-21-app-audit-b-profile-write-failure-plan.md`
- **Issue**: #398 (`Failed Search Profile writes leave changed profiles active until reload`)
- **Reviewer**: Independent Adversarial Auditor (`888ac026-782a-4603-a8b1-3dec77ab7abb`)
- **Gate Standard**: Numeric / Persistence Gate (AUDIT-RULE-V2 / CLAUDE.md)

---

## 1. Audit Scope & Verification Matrix

The plan was analyzed adversarially against the real codebase and the reference artifacts:
1. `docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/followup/storage/findings.md` (Finding S1 & S3)
2. `docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/followup/storage/browser.cjs` (lines 50–75, 104–109)
3. `frontend/lib/searchProfilesStore.ts`
4. `frontend/components/organisms/SearchProfileBar/index.tsx`
5. `frontend/components/molecules/SaveProfileDialog/index.tsx`
6. `frontend/components/molecules/RenameProfileDialog/index.tsx`
7. `frontend/components/molecules/ConfirmDialog/index.tsx`
8. `docs/superpowers/PROJECT_STATE.json` (Phase `APP-AUDIT-B-PROFILE-WRITE-FAILURE`, verify probe `rollbackSearchProfilesOnWriteFailure`)

---

## 2. In-Depth Technical Verification

### 2.1 Complete CRUD Atomicity under Storage Failures
- **`saveProfile(name, snapshot)`**: Synchronously validates overrides (`assertStrategyScanOverrides`), constructs `nextProfiles`, and invokes `persistProfilesPayload(nextProfiles, get().legacyTargetPctDropped)` *before* `set(...)`. If `localStorage.setItem` throws `QuotaExceededError` or `SecurityError`, the action aborts immediately; `set()` is never called, `resyncScheduleEntriesForProfile(id)` is never triggered, memory remains 100% untouched, and disk bytes remain untouched.
- **`updateProfile(id, snapshot)`**: Constructs `nextProfiles` and invokes `persistProfilesPayload` prior to `set()`. On storage exception, `set()` is skipped. Memory retains prior profile properties (e.g., `direction: 'Bullish'`), matching disk readback.
- **`renameProfile(id, name)`**: Pre-commits to disk before store mutation. On storage failure, profile names in memory and in the dropdown remain unchanged.
- **`deleteProfile(id)`**: Pre-commits filtered profile list to disk. On storage failure, in-memory profile list retains the candidate.

### 2.2 Pre-Commit Persistence vs. In-Memory Divergence
- The pre-commit pattern (`persistProfilesPayload` before `set`) eliminates state divergence by construction: in-memory state is only transitioned if the physical disk write succeeds.
- Because `set()` is not invoked on failure, React subscribers and hooks never see transient unpersisted state, avoiding dirty UI flashes, unnecessary re-renders, and optimistic rollback races.
- Zustand v5's subsequent persist middleware invocation in `searchProfilesPersistStorage.setItem` writes the identical payload format (`{ state: { profiles, legacyTargetPctDropped }, version: 5 }`), and its internal try/catch ensures no secondary uncaught error occurs.

### 2.3 SSR Environment Behavior (`window === 'undefined'`)
- Line 64 of `persistProfilesPayload` guards with `if (typeof window === 'undefined') return;`.
- On server-side execution, `localStorage` is not accessed, preventing `ReferenceError` during SSR. Store actions update memory safely without disk I/O, matching Next.js App Router conventions and existing store implementations (`searchProfilesPersistStorage.getItem` and `setItem` already use the identical guard).

### 2.4 Error Handling & UI State in `SearchProfileBar`
- **`handleUpdate`**: Traps storage errors and sets `error` in `<div role="alert">`. Since `updateProfile` leaves memory unchanged, `isDirty` remains `true` and the "Update" button remains enabled. Applying or switching profiles reads the actual persisted baseline.
- **`SaveProfileDialog.onSave`**: Wrapped in `try / catch`. On error, `setSelectedId(id)` is skipped (preventing `selectedId` from referencing a non-existent or unpersisted profile), `error` is set, and `setShowSaveDialog(false)` closes the modal. This ensures the user is not trapped behind an overlay with a permanently disabled "Save" button (`submitting: true`), exposing the rejection alert on `SearchProfileBar`.
- **`RenameProfileDialog.onSave`**: Wrapped in `try / catch`. On error, `error` is set and `setShowRenameDialog(false)` closes the dialog, leaving original profile name intact.
- **`ConfirmDialog.onConfirm` (Delete)**: Wrapped in `try / catch`. On error, `setSelectedId(null)` is bypassed, leaving `selectedId` intact to match the un-deleted profile in store and on disk.

### 2.5 Schedule Re-sync & Future-Version Envelopes
- **Schedule Re-sync**: `void resyncScheduleEntriesForProfile(id)` is placed strictly after `persistProfilesPayload` and `set()`. On write failure, it is never called. Unpersisted parameter changes can never be pushed to backend `ScanScheduleEntry.resolved_request` or execute via automated cron.
- **Write Barrier**: `persistProfilesPayload` parses `localStorage.getItem(key)` and checks `currentEnvelope.version > CURRENT_SEARCH_PROFILES_SCHEMA_VERSION`. If a future schema version (e.g. 9999) is present, it throws `Write barrier: refusing write to newer schema version...` before `localStorage.setItem` is called. Future schemas, unknown properties, and sentinels are preserved byte-for-byte (`beforeRaw === afterRaw`), preventing downgrades and satisfying Finding S3.

### 2.6 Verification Probe & Project State
- `PROJECT_STATE.json` defines a presence probe for `rollbackSearchProfilesOnWriteFailure` in `frontend/lib/searchProfilesStore.ts`.
- The plan exports `rollbackSearchProfilesOnWriteFailure = true`, directly satisfying `scripts/state.py` verification.

---

## 3. Findings

No defects meeting the numeric or persistence gate were identified.

GATE FINDINGS: 0
