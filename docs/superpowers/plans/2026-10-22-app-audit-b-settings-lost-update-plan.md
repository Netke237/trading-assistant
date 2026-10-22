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
- **Criterion 2 (Deep property merge & same-field conflict resolution):** For nested configuration objects (`confidenceGate`, `markov`, `spreads`, `broker`, `scheduleConfig`, `fundamentalsGate`, `targetProfitPct`, `ibkrPaper`, `tradierPaper`, `tradierLive`, `alpacaPaper`, `tastytradePaper`), merging operates at the leaf-property level so edits to independent leaf properties (e.g. Tab A edits `atrMult.swing` while Tab B edits `cautionBelow`) merge cleanly. When both tabs modify the exact same leaf property, the active tab's edit applies without resetting other properties or corrupting persisted data.
- **Criterion 3 (Threshold ordering invariant):** After merging threshold objects (`confidenceGate`, `fundamentalsGate`), the invariant `rejectBelow <= cautionBelow` is strictly re-clamped via `clampGateThresholds`, ensuring invalid inverted gates can never reach storage or scoring engines.
- **Criterion 4 (Live synchronous cross-tab synchronization):** When `localStorage` is updated in one tab, a `storage` event on `SETTINGS_STORAGE_KEY` parses, migrates, and synchronizes the in-memory store in other open tabs synchronously, eliminating race conditions between user blur events and async hydration.
- **Criterion 5 (Storage key and schema compatibility):** The storage key remains `bamendjou-settings` and version remains `24`. Existing migration branches and serialized JSON structure (`{ state: ..., version: 24 }`) are strictly preserved. Initial read of pre-v24 disks migrates before establishing the committed baseline.
- **Criterion 6 (Local write failure reporting):** All writes delegate to the wrapped `reportingLocalStorage` instance, ensuring exceptions (`QuotaExceededError`, `SecurityError`) are caught and tracked in `useSettingsSaveStatus` without suppression.

## Architectural Design

### 1. Baseline Tracking with Default Fallback and Migration
In `frontend/lib/settingsStore.ts`:
- Maintain an in-memory baseline `lastCommittedSettings: Record<string, unknown> | null`.
- Provide `getDefaultPersistedSettings()` returning a fresh copy of the store's default persisted state.
- On initialization or read from storage:
  - Read `localStorage.getItem(SETTINGS_STORAGE_KEY)`.
  - If null or empty: `lastCommittedSettings = getDefaultPersistedSettings()`.
  - If present: parse JSON; if `parsed.version < 24`, pass through `migrateSettings(parsed.state, parsed.version)` so `lastCommittedSettings` is always in canonical v24 shape (preventing false diffs against legacy storage).
- Whenever merge logic evaluates a baseline, fallback safely: `const baseline = lastCommittedSettings ?? getDefaultPersistedSettings();`.

### 2. Deep Three-Way Merge on Write
During `setItem(key, valueString)`:
- Parse `incoming = JSON.parse(valueString)`.
- Read `currentDiskRaw = localStorage.getItem(key)`.
- If `currentDiskRaw` is null or corrupted:
  - Write `valueString` through `reportingStorage.setItem(key, valueString)`.
  - Update `lastCommittedSettings = incoming.state`.
  - Return.
- Parse `currentDisk = JSON.parse(currentDiskRaw)`.
- If `currentDisk.version < 24`: `currentDisk.state = migrateSettings(currentDisk.state, currentDisk.version)`.
- For each top-level key $K$ in `SETTINGS_PERSISTED_KEYS`:
  - If `incoming.state[K]` and `currentDisk.state[K]` are plain objects (e.g. `confidenceGate`, `markov`, `spreads`, `scheduleConfig`, `fundamentalsGate`, `broker`):
    - Perform a leaf-property 3-way merge:
      - For each property $P$ of the object:
        - `tabChanged = !isSettingsEqual(incoming.state[K]?.[P], baseline[K]?.[P])`
        - `diskChanged = !isSettingsEqual(currentDisk.state[K]?.[P], baseline[K]?.[P])`
        - If `tabChanged` and `!diskChanged`: take `incoming.state[K][P]`.
        - If `diskChanged` and `!tabChanged`: take `currentDisk.state[K][P]` (preserves other tab's edit).
        - If neither changed: take `currentDisk.state[K][P]`.
        - If both changed (conflict): take `incoming.state[K][P]` (active tab's user action).
    - If $K === 'confidenceGate'`: re-clamp `merged.confidenceGate` via `clampGateThresholds('cautionBelow', mergedGate.cautionBelow, mergedGate.rejectBelow)` to guarantee `rejectBelow <= cautionBelow`.
    - If $K === 'fundamentalsGate'`: clamp `rejectBelow <= cautionBelow`.
  - Else (primitives or top-level scalars like `shortlistMaxCandidates`, `premiumStopPct`):
    - `tabChanged = !isSettingsEqual(incoming.state[K], baseline[K])`
    - `diskChanged = !isSettingsEqual(currentDisk.state[K], baseline[K])`
    - If `tabChanged` and `!diskChanged`: take `incoming.state[K]`.
    - If `diskChanged` and `!tabChanged`: take `currentDisk.state[K]`.
    - If neither changed: take `currentDisk.state[K]`.
    - If both changed: take `incoming.state[K]`.
- Construct `mergedState`.
- Serialize `{ state: mergedState, version: incoming.version }` and write through wrapped `reportingStorage.setItem(key, serialized)`.
- Update `lastCommittedSettings = mergedState`.
- If `mergedState` incorporates updates from disk that differed from `incoming.state`, update in-memory store using a re-entrancy guarded `setState(mergedState, false)`.

### 3. Re-Entrancy Guard
To prevent recursive calls when `useSettingsStore.setState(mergedState, false)` is called inside `setItem`:
```ts
let isMerging = false;
// inside setItem:
if (isMerging) return;
try {
  isMerging = true;
  // compute mergedState, write through reportingStorage, update lastCommittedSettings
  if (hasDiffFromIncoming) {
    useSettingsStore.setState(mergedState, false);
  }
} finally {
  isMerging = false;
}
```

### 4. Live Synchronous Cross-Tab Synchronization (`syncSettingsFromStorage`)
Export `syncSettingsFromStorage(raw?: string | null): void`:
- When a `storage` event fires with `key === SETTINGS_STORAGE_KEY`:
  - If `raw === null` or storage cleared: do nothing or preserve in-memory state.
  - If raw JSON exists:
    - Parse `{ state, version }`.
    - If valid:
      - If `version < 24`: `migrated = migrateSettings(state, version)`. Else `migrated = state`.
      - Synchronously update in-memory store: `useSettingsStore.setState(migrated, false)`.
      - Synchronously update `lastCommittedSettings = migrated`.
- Attach `window.addEventListener('storage', (e) => { if (e.key === SETTINGS_STORAGE_KEY) syncSettingsFromStorage(e.newValue); })` when `typeof window !== 'undefined'`.

## Sub-Tasks & Breakdown

### Task 1: Core 3-Way Deep Merge & Synchronization Implementation (`frontend/lib/settingsStore.ts`)
- Define `SETTINGS_PERSISTED_KEYS`.
- Implement `isSettingsEqual(a: unknown, b: unknown): boolean` for deep value comparison.
- Implement `getDefaultPersistedSettings()`.
- Implement leaf-property 3-way merge with `clampGateThresholds` ordering protection.
- Implement `createSettingsStorage()` wrapping `reportingLocalStorage` with re-entrancy protection and 3-way merge.
- Implement `syncSettingsFromStorage(raw?: string | null): void` with synchronous state & baseline update.
- Register window `storage` listener.

### Task 2: Unit & Regression Tests (`frontend/lib/__tests__/settingsLostUpdate.test.ts`)
- Stale-tab different-field update (finding S5): Tab A sets `markov.lookback: 55`, Tab B sets `confidenceGate.cautionBelow: 64` -> storage preserves both `55` and `64`.
- Deep property merge within same section: Tab A sets `confidenceGate.atrMult.swing.target: 3.5`, Tab B sets `confidenceGate.cautionBelow: 64` -> storage preserves both `3.5` and `64`.
- Same-field leaf conflict: Tab A sets `markov.lookback: 55`, Tab B sets `markov.lookback: 45` -> Tab B's active edit applies without corrupting other settings.
- Threshold invariant re-clamping: Tab A sets `cautionBelow: 40`, Tab B sets `rejectBelow: 45` -> merged result re-clamps `rejectBelow` to `40`.
- Fresh session handling: empty localStorage initializes baseline without crashing on null dereference.
- Legacy schema migration on read: pre-v24 disk state migrates before establishing baseline, preventing spurious conflict detection.
- Cross-tab `StorageEvent`: dispatching `StorageEvent` updates `useSettingsStore` in-memory state and UI synchronously.
- Error reporting: verify storage quota exceptions are reported to `useSettingsSaveStatus` via `reportingLocalStorage`.

### Task 3: Full Verification & Audit
- Run `npm test -- settings` and full frontend test suite.
- Run `npm run typecheck` (`tsc --noEmit`).
- Verify zero regression in existing `settingsStore.test.ts` and `settingsSaveStatus.test.ts`.
- Run `python scripts/state.py` to ensure zero drift.
