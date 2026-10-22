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
- **Criterion 2 (Recursive leaf property merge & conflict resolution):** For nested configuration objects (`confidenceGate`, `markov`, `spreads`, `broker`, `scheduleConfig`, `fundamentalsGate`, `targetProfitPct`, `ibkrPaper`, `tradierPaper`, `tradierLive`, `alpacaPaper`, `tastytradePaper`), merging operates recursively down to scalar leaf properties. Edits to independent leaf properties (such as Tab A editing `confidenceGate.atrMult.swing.target` while Tab B edits `confidenceGate.atrMult.intraday.target` or `confidenceGate.cautionBelow`) merge cleanly. When both tabs modify the exact same scalar leaf property, the active tab's edit applies without resetting other properties or corrupting persisted data.
- **Criterion 3 (Threshold ordering invariant):** After merging threshold objects (`confidenceGate`, `fundamentalsGate`), the invariant `rejectBelow <= cautionBelow` is strictly re-clamped via `clampGateThresholds`, ensuring invalid inverted gates can never reach storage or scoring engines.
- **Criterion 4 (Live synchronous cross-tab synchronization without write echo):** When `localStorage` is updated in one tab, a `storage` event on `SETTINGS_STORAGE_KEY` parses, migrates, updates `lastCommittedSettings`, and synchronizes the in-memory store in other open tabs synchronously under an `isSyncing` guard. This eliminates the race window between user blur events and async hydration, and guarantees that applying a storage update in Tab B never triggers a write-back to `localStorage` (preventing cross-tab infinite write loops).
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

### 2. Recursive Leaf-Property Three-Way Merge
Implement `mergeLeafProperties(incoming: unknown, disk: unknown, baseline: unknown): unknown`:
```ts
function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

export function mergeLeafProperties(
  incoming: unknown,
  disk: unknown,
  baseline: unknown,
): unknown {
  if (isPlainObject(incoming) && isPlainObject(disk)) {
    const baseObj = isPlainObject(baseline) ? baseline : {};
    const allKeys = new Set([
      ...Object.keys(incoming),
      ...Object.keys(disk),
      ...Object.keys(baseObj),
    ]);
    const result: Record<string, unknown> = {};
    for (const key of allKeys) {
      result[key] = mergeLeafProperties(incoming[key], disk[key], baseObj[key]);
    }
    return result;
  }
  const tabChanged = !isSettingsEqual(incoming, baseline);
  const diskChanged = !isSettingsEqual(disk, baseline);
  if (tabChanged && !diskChanged) return incoming;
  if (diskChanged && !tabChanged) return disk;
  if (tabChanged && diskChanged) return incoming; // active tab user action wins conflict
  return disk !== undefined ? disk : incoming;
}
```
During `setItem(key, valueString)`:
- Parse `incoming = JSON.parse(valueString)`.
- Read `currentDiskRaw = localStorage.getItem(key)`.
- If `currentDiskRaw` is null or corrupted:
  - Write `valueString` through `reportingStorage.setItem(key, valueString)`.
  - Update `lastCommittedSettings = incoming.state`.
  - Return.
- Parse `currentDisk = JSON.parse(currentDiskRaw)`.
- If `currentDisk.version < 24`: `currentDisk.state = migrateSettings(currentDisk.state, currentDisk.version)`.
- Merge state across all keys via `mergeLeafProperties(incoming.state, currentDisk.state, baseline)`.
- Post-merge threshold clamping:
  - For `confidenceGate`: apply `clampGateThresholds('cautionBelow', mergedGate.cautionBelow, mergedGate.rejectBelow)`.
  - For `fundamentalsGate`: clamp `rejectBelow <= cautionBelow`.
- Construct `mergedState`.
- Serialize `{ state: mergedState, version: incoming.version }` and write through wrapped `reportingStorage.setItem(key, serialized)`.
- Update `lastCommittedSettings = mergedState`.
- If `mergedState` incorporates updates from disk that differed from `incoming.state`, update in-memory store using a re-entrancy guarded `setState(mergedState, false)`.

### 3. Synchronization & Re-Entrancy Guards
To prevent infinite write loops and recursion between store mutations, storage writes, and cross-tab storage events:
```ts
let isMerging = false;
let isSyncing = false;

// inside createSettingsStorage().setItem:
if (isMerging || isSyncing) return;
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
    - If valid and typeof state === 'object':
      - If `version < 24`: `migrated = migrateSettings(state, version)`. Else `migrated = state`.
      - Synchronously update committed baseline first: `lastCommittedSettings = migrated`.
      - Synchronously update in-memory store under sync guard:
        ```ts
        isSyncing = true;
        try {
          useSettingsStore.setState(migrated, false);
        } finally {
          isSyncing = false;
        }
        ```
- Attach `window.addEventListener('storage', (e) => { if (e.key === SETTINGS_STORAGE_KEY) syncSettingsFromStorage(e.newValue); })` when `typeof window !== 'undefined'`.

## Sub-Tasks & Breakdown

### Task 1: Core Recursive 3-Way Merge & Synchronous Cross-Tab Sync (`frontend/lib/settingsStore.ts`)
- Define `SETTINGS_PERSISTED_KEYS`.
- Implement `isSettingsEqual(a: unknown, b: unknown): boolean` for deep value comparison.
- Implement `getDefaultPersistedSettings()`.
- Implement `mergeLeafProperties` for recursive leaf-level 3-way merging.
- Implement post-merge `clampGateThresholds` ordering protection.
- Implement `createSettingsStorage()` wrapping `reportingLocalStorage` with `isMerging` and `isSyncing` guards.
- Implement `syncSettingsFromStorage(raw?: string | null): void` with synchronous state & baseline update under `isSyncing` guard.
- Register window `storage` listener.

### Task 2: Unit & Regression Tests (`frontend/lib/__tests__/settingsLostUpdate.test.ts`)
- Stale-tab different-field update (finding S5): Tab A sets `markov.lookback: 55`, Tab B sets `confidenceGate.cautionBelow: 64` -> storage preserves both `55` and `64`.
- Deep nested property merge within same section (finding F-08): Tab A sets `confidenceGate.atrMult.swing.target: 3.5`, Tab B sets `confidenceGate.atrMult.intraday.target: 1.8` -> storage preserves both `3.5` and `1.8`.
- Same-field leaf conflict: Tab A sets `markov.lookback: 55`, Tab B sets `markov.lookback: 45` -> Tab B's active edit applies without corrupting other settings.
- Threshold invariant re-clamping: Tab A sets `cautionBelow: 40`, Tab B sets `rejectBelow: 45` -> merged result re-clamps `rejectBelow` to `40`.
- Fresh session handling: empty localStorage initializes baseline without crashing on null dereference.
- Legacy schema migration on read: pre-v24 disk state migrates before establishing baseline, preventing spurious conflict detection.
- Cross-tab `StorageEvent` without write loop (finding F-09): dispatching `StorageEvent` updates `useSettingsStore` in-memory state and UI synchronously without calling `reportingStorage.setItem` or triggering a write echo.
- Error reporting: verify storage quota exceptions are reported to `useSettingsSaveStatus` via `reportingLocalStorage`.

### Task 3: Full Verification & Audit
- Run `npm test -- settings` and full frontend test suite.
- Run `npm run typecheck` (`tsc --noEmit`).
- Verify zero regression in existing `settingsStore.test.ts` and `settingsSaveStatus.test.ts`.
- Run `python scripts/state.py` to ensure zero drift.
