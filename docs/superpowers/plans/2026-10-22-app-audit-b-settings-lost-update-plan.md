# Plan: Stale-tab Settings edit overwrites unrelated saved values (#400)

## Problem & Context
During Lane B storage verification (finding S5 in `docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/followup/storage/findings.md`), a persisted lost-update defect was cataloged in `frontend/lib/settingsStore.ts`:
1. Two same-origin tabs (Tab A and Tab B) are open at the same initial state (e.g. `markov.lookback = 35`, `confidenceGate.cautionBelow = 50`).
2. In Tab A, the user changes `markov.lookback` to 55. This persists `{ markov: { lookback: 55 }, confidenceGate: { cautionBelow: 50 }, ... }` to `localStorage['bamendjou-settings']`.
3. Tab B does not listen to `storage` events, so its in-memory Zustand store remains stale (`markov.lookback = 35`).
4. In Tab B, the user edits `confidenceGate.cautionBelow` to 64 and blurs.
5. Tab B serializes its entire in-memory state snapshot and writes it to `localStorage['bamendjou-settings']`.
6. This whole-store write silently overwrites Tab A's newer `markov.lookback = 55` back to `35`, causing silent data loss of unrelated settings.

Issue #400 tracks the remediation for this defect (`APP-AUDIT-B-SETTINGS-LOST-UPDATE`), with native blocker #371 closed.

## Core Requirements & Acceptance Criteria
- **Criterion 1 (Different-field stale-tab edit):** When Tab A updates setting field $X$ (e.g. `markov.lookback = 55`) and Tab B updates setting field $Y$ (e.g. `confidenceGate.cautionBelow = 64`), persisting Tab B's edit must preserve Tab A's setting $X$ (55) alongside Tab B's setting $Y$ (64).
- **Criterion 2 (Same-field conflict resolution):** When Tab A updates setting field $X$ and Tab B also updates setting field $X$ from the stale baseline, the active user edit in Tab B applies without corrupting or resetting unrelated fields.
- **Criterion 3 (Live cross-tab synchronization):** When `localStorage` is updated in one tab, a `storage` event on `SETTINGS_STORAGE_KEY` synchronizes the in-memory store in other open tabs in real time.
- **Criterion 4 (Storage key and schema compatibility):** The storage key remains `bamendjou-settings` and version remains `24`. Existing migration branches and serialized JSON structure (`{ state: ..., version: 24 }`) are strictly preserved.
- **Criterion 5 (Local write failure reporting):** Storage exceptions (`QuotaExceededError`, `SecurityError`) continue to be reported via `reportingLocalStorage` and `settingsSaveStatus` without suppression.

## Architectural Design

### 1. Diff-Based Three-Way Merge on Write
In `frontend/lib/settingsStore.ts`, we track the last committed storage snapshot `lastCommittedSettings` in memory:
- On initial hydration/read, `lastCommittedSettings` is initialized to the parsed disk state.
- During `setItem(key, valueString)`:
  - Parse `incoming = JSON.parse(valueString)`.
  - Read `currentDiskRaw = localStorage.getItem(key)`.
  - If `currentDiskRaw` exists:
    - Parse `currentDisk = JSON.parse(currentDiskRaw)`.
    - If `currentDisk.version` differs from current version, run `migrateSettings(currentDisk.state, currentDisk.version)` so merging operates on canonical schemas.
    - For each top-level key $K$ in `SETTINGS_PERSISTED_KEYS`:
      - Determine if current tab changed $K$: `tabChanged = !isEqual(incoming.state[K], lastCommittedSettings[K])`.
      - Determine if disk (another tab) changed $K$: `diskChanged = !isEqual(currentDisk.state[K], lastCommittedSettings[K])`.
      - If `tabChanged` and `!diskChanged`: use `incoming.state[K]`.
      - If `diskChanged` and `!tabChanged`: use `currentDisk.state[K]` (preserves other tab's update).
      - If neither changed: use `currentDisk.state[K]`.
      - If both changed (conflict): use `incoming.state[K]` (the active user action).
    - Construct `mergedState`.
    - Serialize `{ state: mergedState, version: incoming.version }` and write to `localStorage`.
    - Update `lastCommittedSettings = mergedState`.
    - If `mergedState` incorporates updates from disk that differed from in-memory state, update in-memory `useSettingsStore` state via `setState(mergedState, false)` without re-triggering storage write.

### 2. Cross-Tab Storage Event Synchronization (`syncSettingsFromStorage`)
Export `syncSettingsFromStorage(raw?: string | null): void`:
- When a `storage` event fires with `key === SETTINGS_STORAGE_KEY`:
  - If `raw === null` or `localStorage.getItem(SETTINGS_STORAGE_KEY) === null`:
    - Storage was cleared externally; optionally reset or preserve in-memory.
  - If raw JSON exists:
    - Parse `{ state, version }`.
    - If valid, execute `useSettingsStore.persist.rehydrate()`.
    - Update `lastCommittedSettings = migratedState`.
- Initialize `window.addEventListener('storage', handleStorage)` in browser environments (`typeof window !== 'undefined'`).

### 3. Pure Deep-Equality Helper (`isSettingsEqual`)
Provide a fast, deterministic deep equality helper for settings state objects (supporting primitives, arrays, and nested plain objects like `markov`, `confidenceGate`, `spreads`, `broker`, `scheduleConfig`).

## Sub-Tasks & Breakdown

### Task 1: Core Merge and Synchronization Implementation (`frontend/lib/settingsStore.ts`)
- Define `SETTINGS_PERSISTED_KEYS`.
- Implement `isSettingsEqual(a: unknown, b: unknown): boolean`.
- Implement `mergeSettingsState(incoming: SettingsState, disk: SettingsState, baseline: SettingsState): SettingsState`.
- Implement custom `createSettingsStorage()` wrapping `reportingLocalStorage` with 3-way merge logic.
- Implement `syncSettingsFromStorage(raw?: string | null): void`.
- Register cross-tab `storage` event listener.

### Task 2: Unit & Regression Tests (`frontend/lib/__tests__/settingsLostUpdate.test.ts`)
- Add comprehensive test suite covering:
  - Stale tab different-field update: Tab A modifies `markov.lookback: 55`, Tab B modifies `confidenceGate.cautionBelow: 64` -> verify persisted state contains BOTH `55` and `64`.
  - Same-field conflict: Tab A modifies `markov.lookback: 55`, Tab B modifies `markov.lookback: 45` -> verify Tab B's active edit applies without resetting other fields.
  - Storage event dispatch: dispatching `StorageEvent` for `bamendjou-settings` updates `useSettingsStore` in-memory state and UI text values.
  - Schema version and keys: verify storage key `'bamendjou-settings'` and version `24` are strictly preserved.
  - Error reporting: verify `reportingLocalStorage` still reports write failures to `useSettingsSaveStatus`.

### Task 3: Full Verification & Audit
- Run `npm test -- settings` and full frontend test suite.
- Run `npm run typecheck` (`tsc --noEmit`).
- Verify zero regression in existing `settingsStore.test.ts` and `settingsSaveStatus.test.ts`.
- Run `python scripts/state.py` to ensure zero drift.
