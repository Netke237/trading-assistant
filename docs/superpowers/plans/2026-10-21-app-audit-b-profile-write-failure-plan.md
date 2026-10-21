# Implementation Plan: Atomic Search Profile Writes & Write Failure Rollback (Finding S1 / Issue #398)

## 1. Executive Summary & Problem Analysis

### 1.1 Context & Background
Issue #398 (`APP-AUDIT-B-PROFILE-WRITE-FAILURE`, size: M, complexity: 4) addresses storage finding **S1** identified during the Lane B / Lane I Settings & Profiles audit (`docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/followup/storage/findings.md`).

### 1.2 The Defect
When `localStorage.setItem` fails on key `bamendjou:search-profiles` (for example, due to browser quota exhaustion `DOMException('QuotaExceededError')`, permission denial `DOMException('SecurityError')`, or a newer schema write barrier):
1. In `frontend/lib/searchProfilesStore.ts`, the mutation actions `saveProfile`, `updateProfile`, `renameProfile`, and `deleteProfile` call `set((s) => ({ profiles: ... }))`.
2. Zustand v5 `persist` immediately commits the modified profile list to in-memory store state `state.profiles`.
3. Zustand then invokes `storage.setItem(name, value)` via `searchProfilesPersistStorage.setItem`.
4. `searchProfilesPersistStorage.setItem` has a `try { localStorage.setItem(...) } catch { /* quota exceeded */ }` block that swallows storage exceptions.
5. Even if `storage.setItem` throws, Zustand's persist middleware does not roll back `set(...)`.
6. **Result**:
   - Exact bytes on disk remain unchanged (`beforeRaw === afterRaw`).
   - In-memory `useSearchProfilesStore.getState().profiles` is mutated to the new/updated state.
   - `SearchProfileBar` dropdown renders the new/renamed profile or drops the deleted profile.
   - Applying an updated profile reads modified values (e.g. `direction: 'Bearish'`) from memory while disk readback still has `direction: 'Bullish'`.
   - On page reload (`window.location.reload()`), disk readback restores the old profile, silently discarding the changes the user was led to believe were saved.

---

## 2. Architecture & Design Principles

### 2.1 Atomic Persistence Contract (Finding S1)
The store must guarantee **Atomicity** across all CRUD operations (`saveProfile`, `updateProfile`, `renameProfile`, `deleteProfile`):
- **Success Case**: Disk bytes are updated with the new profile state AND in-memory store state reflects the changes.
- **Failure Case**:
  - If disk persistence fails (e.g. `QuotaExceededError`, `SecurityError`, or future-version write barrier refusal):
    1. In-memory `state.profiles` MUST NOT be mutated (remains 100% identical to prior committed state).
    2. Prior raw bytes in `localStorage` MUST remain untouched.
    3. The mutation action MUST throw a typed error describing the persistence failure.
    4. React UI controls (`SearchProfileBar`, `SaveProfileDialog`) MUST catch the error and display an explicit error alert (`role="alert"`), rather than pretending the profile was saved.
    5. The applied scan context and scan request builders MUST NOT receive phantom unpersisted parameters.

### 2.2 Mechanism for Atomicity
Rather than mutating Zustand in-memory state before persistence succeeds:
1. `persistProfilesPayload(nextProfiles, legacyTargetPctDropped)` verifies write preconditions:
   - Reads `localStorage.getItem('bamendjou:search-profiles')`.
   - If disk contains a newer schema version (`version > CURRENT_SEARCH_PROFILES_SCHEMA_VERSION`), throws an explicit write barrier error.
   - Serializes `{ state: { profiles: nextProfiles, legacyTargetPctDropped }, version: 5 }` and executes `localStorage.setItem('bamendjou:search-profiles', json)`.
2. If `localStorage.setItem` throws or rejects:
   - The exception is thrown BEFORE `set()` is ever called on Zustand store.
   - In-memory `state.profiles` is NEVER mutated.
   - `resyncScheduleEntriesForProfile(id)` is NEVER triggered.
3. If `localStorage.setItem` succeeds:
   - Disk is now safely updated.
   - `set({ profiles: nextProfiles })` is called to update in-memory state and notify React subscribers.
   - When Zustand's persist middleware runs `storage.setItem`, it writes the exact same payload (or no-ops if verified), ensuring sync consistency.

---

## 3. Detailed File Changes

### 3.1 `frontend/lib/searchProfilesStore.ts`
- **Pre-write Persistence Helper**:
  Implement and export `rollbackSearchProfilesOnWriteFailure` (and `persistProfilesPayload`):
  ```ts
  export function persistProfilesPayload(
    profiles: SearchProfile[],
    legacyTargetPctDropped: boolean,
  ): void {
    if (typeof window === 'undefined') return;
    const key = 'bamendjou:search-profiles';
    const currentRaw = localStorage.getItem(key);
    if (currentRaw) {
      try {
        const currentEnvelope = JSON.parse(currentRaw);
        if (
          typeof currentEnvelope?.version === 'number' &&
          currentEnvelope.version > CURRENT_SEARCH_PROFILES_SCHEMA_VERSION
        ) {
          throw new Error(
            `Write barrier: refusing write to newer schema version ${currentEnvelope.version} (current: ${CURRENT_SEARCH_PROFILES_SCHEMA_VERSION})`,
          );
        }
      } catch (e) {
        if (e instanceof Error && e.message.startsWith('Write barrier:')) {
          throw e;
        }
      }
    }
    const envelope = {
      state: { profiles, legacyTargetPctDropped },
      version: CURRENT_SEARCH_PROFILES_SCHEMA_VERSION,
    };
    localStorage.setItem(key, JSON.stringify(envelope));
  }
  ```
- **Update Actions**:
  - `saveProfile(name, snapshot)`:
    Constructs the new profile. Calls `persistProfilesPayload(nextProfiles, get().legacyTargetPctDropped)` first. Only after write succeeds, calls `set({ profiles: nextProfiles })` and dispatches schedule resync.
  - `updateProfile(id, snapshot)`:
    Constructs updated profile list. Calls `persistProfilesPayload(nextProfiles, get().legacyTargetPctDropped)` first. Only after write succeeds, calls `set({ profiles: nextProfiles })` and dispatches schedule resync.
  - `renameProfile(id, name)`:
    Constructs renamed profile list. Calls `persistProfilesPayload(nextProfiles, get().legacyTargetPctDropped)` first. Only after write succeeds, calls `set({ profiles: nextProfiles })`.
  - `deleteProfile(id)`:
    Constructs filtered profile list. Calls `persistProfilesPayload(nextProfiles, get().legacyTargetPctDropped)` first. Only after write succeeds, calls `set({ profiles: nextProfiles })`.
- **Export Presence Symbol**:
  Export `rollbackSearchProfilesOnWriteFailure = true` to satisfy the `PROJECT_STATE.json` presence probe.

### 3.2 `frontend/components/organisms/SearchProfileBar/index.tsx`
- Ensure all profile mutation handlers capture thrown storage errors and set the user-visible `error` state:
  - `handleUpdate`:
    ```tsx
    function handleUpdate() {
      if (!selected) return;
      try {
        updateProfile(selected.id, captureCurrentSnapshot(activeMode));
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    }
    ```
  - `SaveProfileDialog.onSave`:
    ```tsx
    onSave={(name) => {
      try {
        const id = useSearchProfilesStore.getState().saveProfile(name, captureCurrentSnapshot(activeMode));
        setSelectedId(id);
        setError(null);
        setShowSaveDialog(false);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setShowSaveDialog(false);
      }
    }}
    ```
  - `RenameProfileDialog.onSave`:
    ```tsx
    onSave={(name) => {
      try {
        renameProfile(selected.id, name);
        setError(null);
        setShowRenameDialog(false);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setShowRenameDialog(false);
      }
    }}
    ```
  - `ConfirmDialog.onConfirm` (Delete):
    ```tsx
    onConfirm={() => {
      try {
        deleteProfile(selected.id);
        setSelectedId(null);
        setError(null);
        setShowDeleteConfirm(false);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setShowDeleteConfirm(false);
      }
    }}
    ```

---

## 4. Test Strategy

### 4.1 Unit Tests (`frontend/lib/__tests__/searchProfilesWriteFailure.test.ts`)
1. **Save Profile Failure**:
   - Mock `localStorage.setItem` throwing `QuotaExceededError` / `SecurityError`.
   - Call `saveProfile('New Profile', snapshot)`.
   - Expect error to be thrown.
   - Assert `useSearchProfilesStore.getState().profiles` is unchanged (0 profiles).
   - Assert `localStorage.getItem` returns the original bytes.
2. **Update Profile Failure**:
   - Seed store with baseline profile (`direction: 'Bullish'`).
   - Mock `localStorage.setItem` throwing `QuotaExceededError` / `SecurityError`.
   - Call `updateProfile('baseline-id', { ...snapshot, direction: 'Bearish' })`.
   - Expect error to be thrown.
   - Assert `useSearchProfilesStore.getState().profiles[0].direction` remains `'Bullish'`.
   - Assert `localStorage` bytes still contain `'Bullish'`.
3. **Rename Profile Failure**:
   - Seed store with baseline profile (`name: 'Original'`).
   - Mock `localStorage.setItem` throwing `QuotaExceededError`.
   - Call `renameProfile('baseline-id', 'Renamed')`.
   - Expect error to be thrown.
   - Assert in-memory profile name remains `'Original'`.
4. **Delete Profile Failure**:
   - Seed store with baseline profile.
   - Mock `localStorage.setItem` throwing `QuotaExceededError`.
   - Call `deleteProfile('baseline-id')`.
   - Expect error to be thrown.
   - Assert in-memory profiles array still has length 1.
5. **Future-Version Write Barrier Refusal**:
   - Seed `localStorage` with `version: 9999`.
   - Call `saveProfile`, `updateProfile`, `renameProfile`, `deleteProfile`.
   - Assert all throw write barrier error.
   - Assert memory remains unmutated and disk bytes are 100% exact.
6. **Success Path**:
   - Verify all 4 CRUD operations succeed under normal storage conditions and properly update both disk and memory.

### 4.2 Component Tests (`frontend/components/organisms/SearchProfileBar/__tests__/SearchProfileBar.writeFailure.test.tsx`)
1. **Failed Save as New**:
   - User opens Save dialog, enters name, clicks Save.
   - `localStorage.setItem` throws `QuotaExceededError`.
   - Expect error message rendered in `role="alert"`.
   - Expect dropdown options to remain unchanged.
2. **Failed Update**:
   - User edits direction and clicks Update.
   - `localStorage.setItem` throws `SecurityError`.
   - Expect error message in `role="alert"`.
   - In-memory profile remains unchanged.
3. **Failed Rename & Delete**:
   - Test rename and delete failure handling in UI.

---

## 5. Execution Steps

1. **Plan Stage**:
   - Create plan file `docs/superpowers/plans/2026-10-21-app-audit-b-profile-write-failure-plan.md`.
   - Register plan in `docs/superpowers/PROJECT_STATE.json`.
   - Commit plan and push to `board/app-audit-b-profile-write-failure-513f936a`.
   - Dispatch independent Plan Auditor subagent applying `bmad-review-adversarial-general` with numeric/persistence gate.
   - Fix any plan findings until Plan Audit is clean.
2. **Implementation Stage**:
   - Implement `persistProfilesPayload` and atomic CRUD actions in `frontend/lib/searchProfilesStore.ts`.
   - Update `frontend/components/organisms/SearchProfileBar/index.tsx` error handling.
   - Add unit test suite `frontend/lib/__tests__/searchProfilesWriteFailure.test.ts`.
   - Add integration test suite `frontend/components/organisms/SearchProfileBar/__tests__/SearchProfileBar.writeFailure.test.tsx`.
   - Run typecheck and all search profile test suites.
   - Update `PROJECT_STATE.json` status to `built`.
3. **Code Audit Stage**:
   - Dispatch independent Code Auditor subagent.
   - Fix any code findings until Code Audit is clean.
4. **Self-Merge & Closure**:
   - Open PR for #398.
   - Await green CI.
   - Self-merge PR per `board.md` step 7.
   - Release claim and notify.
