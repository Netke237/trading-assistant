# Implementation Plan: Malformed Profile Validation and Future-Version Write Barrier (#381)

## 1. Problem Statement & Baseline Evidence
Issue #381 addresses defect C3 and storage finding S3 from the Settings and Profiles audit (`docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/`):

1. **Defect C3 — Malformed current-version profile crashes Step 3 Search Profile controls**:
   - `localStorage` may contain a version-5 payload for `bamendjou:search-profiles` with malformed profile objects (e.g. `updatedAt: null`, missing string `id`, missing string `name`, invalid `mode`, missing/malformed `universe`, missing `direction`).
   - When Step 3 mounts (`/screener/step-3-direction`), `SearchProfileBar` calls:
     ```ts
     const modeProfiles = profiles
       .filter((p) => p.mode === activeMode)
       .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
     ```
   - If `b.updatedAt` or `a.updatedAt` is null or not a string, `localeCompare` throws a TypeError (`Cannot read properties of null (reading 'localeCompare')`), crashing the entire React tree. The Search Profile bar disappears and Step 3 displays a client runtime error.
   - In `controls/source-probe.cjs:22-23`:
     ```js
     localStorage.setItem('bamendjou:search-profiles', JSON.stringify({ version: 5, state: { profiles: [{ ...clone(base), updatedAt: null }] } }));
     await ps.persist.rehydrate();
     check('malformed current profile rejected', 0, ps.getState().profiles.length);
     ```
     Currently fails: `ps.getState().profiles.length` is 1 because the malformed profile is accepted into the store without shape validation.

2. **Finding S3 — Opening an unknown future profile store downgrades and discards data**:
   - In `followup/storage/browser.cjs:104-109`:
     ```js
     const future = { ...fixture, version: 9999, state: { ...fixture.state, futureAuditSentinel: 'must-survive-older-client' } };
     localStorage.setItem(k, JSON.stringify(future));
     ```
   - When Step 3 loads, `StoreHydration` calls `useSearchProfilesStore.persist.rehydrate()`.
   - Zustand's persist middleware detects `deserializedStorageValue.version !== options.version (5)`, runs `migrate`, marks `migrated = true`, and immediately calls `setItem()`.
   - `setItem()` writes `{ state: options.partialize(state), version: 5 }`, overwriting `version: 9999` with `version: 5` and discarding unknown state fields such as `futureAuditSentinel`.
   - In `followup/storage/browser.cjs:108`:
     ```js
     check('unknown future version preserves bytes until explicit compatible migration', JSON.stringify(future), after[KEY]);
     ```
     Currently fails because `after[KEY]` is rewritten to version 5 with sentinel stripped.

---

## 2. Gate Criteria & Constraints
- **The Gate:** A finding blocks only if it can put a WRONG NUMBER in front of a user or on a broker order, or CORRUPT PERSISTED DATA.
  - A malformed profile entering in-memory state can apply corrupt parameters to scans, producing wrong numbers, candidate rankings, or broker order parameters.
  - Crashing Step 3 prevents users from executing scans or configuring parameters.
  - Silently downgrading a newer future envelope to version 5 corrupts persisted data and destroys forward compatibility.
  - An older client must leave unknown newer data untouched on disk (`beforeRaw === afterRaw`) while safely reading compatible profiles for in-memory display.
- **Self-Merge Conditions:** Follow all 5 self-merge conditions from `docs/agents/board.md`.

---

## 3. Architecture & Detailed Design

### A. Dedicated Profile Validation Module (`frontend/lib/searchProfileValidation.ts`)
Create a pure validation module defining strict shape guards:
1. `isValidSearchProfile(p: unknown): p is SearchProfile`:
   - Checks `p !== null && typeof p === 'object' && !Array.isArray(p)`.
   - `id`: `typeof p.id === 'string' && p.id.trim().length > 0`.
   - `name`: `typeof p.name === 'string' && p.name.trim().length > 0`.
   - `mode`: `p.mode === 'options' || p.mode === 'stocks'`.
   - `createdAt`: `typeof p.createdAt === 'string' && p.createdAt.trim().length > 0 && !isNaN(Date.parse(p.createdAt))`.
   - `updatedAt`: `typeof p.updatedAt === 'string' && p.updatedAt.trim().length > 0 && !isNaN(Date.parse(p.updatedAt))`.
   - `direction`: `p.direction === 'Bullish' || p.direction === 'Bearish'`.
   - `universe`: non-null, non-array object requiring:
     - `typeof p.universe.pick === 'string' && p.universe.pick.trim().length > 0`
     - `typeof p.universe.customRaw === 'string'`
     - `p.universe.capUnit === 'M' || p.universe.capUnit === 'B'`
     - `typeof p.universe.minPriceRaw === 'string'`
     - `typeof p.universe.maxPriceRaw === 'string'`
     - `typeof p.universe.minCapRaw === 'string'`
     - `typeof p.universe.maxCapRaw === 'string'` (resolves F-5: ensures price/cap fields are string primitives, preventing `Number(null) === 0` sending 0 to backend)
   - `horizonPreset`: `typeof p.horizonPreset === 'string' && p.horizonPreset.trim().length > 0`.
   - `holdMin`: `typeof p.holdMin === 'number' && Number.isFinite(p.holdMin)`.
   - `holdMax`: `typeof p.holdMax === 'number' && Number.isFinite(p.holdMax)`.
   - `scanOverrides`: `typeof p.scanOverrides === 'object' && p.scanOverrides !== null && !Array.isArray(p.scanOverrides)`.
   - `scanSettings`:
     - non-null, non-array object
     - `confidenceGate`: non-null, non-array object with:
       - `typeof p.scanSettings.confidenceGate.enabled === 'boolean'`
       - `typeof p.scanSettings.confidenceGate.cautionBelow === 'number' && Number.isFinite(p.scanSettings.confidenceGate.cautionBelow)`
       - `typeof p.scanSettings.confidenceGate.rejectBelow === 'number' && Number.isFinite(p.scanSettings.confidenceGate.rejectBelow)`
       - `atrMult`: non-null, non-array object containing `intraday`, `swing`, and `position` sub-objects, each having finite numeric `target` and `stop` (resolves F-6: prevents `TypeError: Cannot read properties of undefined (reading 'intraday'/'swing'/'position')` in `atrMultForHorizon` / `resolveProfileToScanRequest`)
   - Strategy & StrategyParams co-presence (resolves F-7):
     - If `p.mode === 'stocks'`:
       - `strategy` and `strategyParams` must be both undefined OR both present:
         `((p.strategy === undefined && p.strategyParams === undefined) || (typeof p.strategy === 'string' && p.strategy.trim().length > 0 && typeof p.strategyParams === 'object' && p.strategyParams !== null && !Array.isArray(p.strategyParams)))`.
     - If `p.mode === 'options'`:
       - `p.strategy === undefined && p.strategyParams === undefined` (options profiles do not carry stocks strategy state).

2. `sanitizeSearchProfiles(profiles: unknown): SearchProfile[]`:
   - If `!Array.isArray(profiles)`, returns `[]`.
   - Filters entries using `isValidSearchProfile`.
   - Returns only structurally valid profiles.

3. `safeCompareTimestamps(a?: string | null, b?: string | null): number`:
   - Pure comparator for descending order: `(b || '').localeCompare(a || '')`.

### B. Store Rehydration, Migration & Future-Version Write Barrier (`frontend/lib/searchProfilesStore.ts`)
1. **Sanitization Hooks Across All Versions (resolves F-1)**:
   - In Zustand's persist middleware, `migrate(persistedState, version)` only runs when `storedVersion !== options.version`. It does NOT execute when the stored payload is already version 5!
   - Therefore, profile sanitization must be enforced in two complementary locations:
     a. **In `options.merge(persistedState, currentState)`**:
        ```ts
        merge: (persistedState, currentState) => {
          const typed = persistedState as Partial<SearchProfilesState> | undefined;
          return {
            ...currentState,
            ...typed,
            profiles: sanitizeSearchProfiles(typed?.profiles ?? currentState.profiles),
          };
        }
        ```
        `options.merge` runs unconditionally on every hydration across all schema versions (whether migrated, matching, or future), guaranteeing that malformed profiles never enter the Zustand store state in memory.
     b. **In `storage.getItem`**:
        Directly sanitizes profiles before returning the state object to Zustand.
     c. **In `migrate`**:
        Applies `st.profiles = sanitizeSearchProfiles(st.profiles)` at the end of legacy migration branches (<3, <4, <5).

2. **Custom Storage Adapter `PersistStorage<PersistedSearchProfiles>` (resolves F-2, F-3, F-4)**:
   - Define `PersistedSearchProfiles = Pick<SearchProfilesState, 'profiles' | 'legacyTargetPctDropped'>`.
   - Directly implement `PersistStorage<PersistedSearchProfiles>` and supply it directly to `persist(..., { storage: searchProfilesPersistStorage })` **WITHOUT** wrapping in `createJSONStorage`. (Resolves F-2: avoids `createJSONStorage` calling `JSON.parse("[object Object]")` and crashing).
   - `CURRENT_VERSION = 5`.
   - `getItem(name: string): StorageValue<PersistedSearchProfiles> | null`:
     - Reads raw string from `localStorage.getItem(name)`.
     - If null, empty, or unparseable JSON, returns null.
     - Parses JSON:
       - If `typeof parsed.version === 'number' && parsed.version > CURRENT_VERSION`:
         - Future envelope detected (e.g. `version: 9999` with `futureAuditSentinel`).
         - Extract and sanitize profiles compatible with current version:
           `const safeProfiles = sanitizeSearchProfiles(parsed.state?.profiles);`
         - Return to Zustand: `{ state: { profiles: safeProfiles, legacyTargetPctDropped: false }, version: CURRENT_VERSION }`.
         - **Key Mechanism**: Because `deserializedStorageValue.version === options.version (5)`, Zustand's hydration logic evaluates `version !== options.version` as `false`. Zustand does **not** flag `migrated = true` and does **not** trigger an automatic `setItem()` overwrite during hydration!
         - **Result**: `localStorage.getItem('bamendjou:search-profiles')` remains 100% byte-for-byte identical to the original future envelope (`beforeRaw === afterRaw`), completely satisfying Finding S3.
       - If `parsed.version <= CURRENT_VERSION`:
         - Return `{ state: { profiles: sanitizeSearchProfiles(parsed.state?.profiles), legacyTargetPctDropped: parsed.state?.legacyTargetPctDropped === true }, version: parsed.version }`.
   - `setItem(name: string, value: StorageValue<PersistedSearchProfiles>): void`:
     - **Direct Disk Inspection at Write Time (resolves F-3)**:
       Do NOT rely on an in-memory flag (which would race cross-tab writes). Instead, inspect `localStorage.getItem(name)` directly at write time.
     - **Strict Write Barrier on Future Envelopes (resolves F-4)**:
       If `localStorage.getItem(name)` contains a payload with `version > CURRENT_VERSION`:
       - Refuse to overwrite or mutate it from an older client!
       - Log a console warning: `[searchProfilesStore] Write barrier: refusing write to newer schema version ${currentEnvelope.version} (current: ${CURRENT_VERSION})`.
       - Return immediately without calling `localStorage.setItem`.
       - Disk bytes remain 100% byte-exact (`beforeRaw === afterRaw`), preserving future-version profiles (e.g. unknown modes) and future sentinels intact.
     - If `localStorage.getItem(name)` is null, malformed, or has `version <= CURRENT_VERSION`:
       - Normal write: `localStorage.setItem(name, JSON.stringify(value))`.
   - `removeItem(name: string): void`:
     - Calls `localStorage.removeItem(name)`.

### C. Component Defense in `SearchProfileBar/index.tsx`
1. Defensively filter and sort `modeProfiles`:
   ```ts
   const modeProfiles = profiles
     .filter(isValidSearchProfile)
     .filter((p) => p.mode === activeMode)
     .sort((a, b) => safeCompareTimestamps(a.updatedAt, b.updatedAt));
   ```
2. Safe fallback:
   `safeCompareTimestamps(a.updatedAt, b.updatedAt)` uses `(b || '').localeCompare(a || '')`, treating missing or empty timestamps as lowest priority without throwing.
3. If no valid profiles exist for `activeMode`, the dropdown renders standard default options safely without errors.

---

## 4. File-by-File Changes

1. **`frontend/lib/searchProfileValidation.ts`** (NEW):
   - Exports `isValidSearchProfile(p: unknown): p is SearchProfile`.
   - Exports `sanitizeSearchProfiles(profiles: unknown): SearchProfile[]`.
   - Exports `safeCompareTimestamps(a?: string | null, b?: string | null): number`.

2. **`frontend/lib/__tests__/searchProfileValidation.test.ts`** (NEW):
   - Unit tests covering `isValidSearchProfile`:
     - Valid options profile passes.
     - Valid stocks profile passes (both with and without strategy & strategyParams).
     - `updatedAt: null` or invalid date string fails.
     - `createdAt: null` or invalid date string fails.
     - Missing or empty `id` / `name` fails.
     - Invalid `mode` fails.
     - Missing `direction` or invalid string fails.
     - `universe` missing string fields (`minPriceRaw`, `maxPriceRaw`, `minCapRaw`, `maxCapRaw`) fails (resolves F-5).
     - `confidenceGate` missing `atrMult` or missing horizon pairs fails (resolves F-6).
     - Stocks profile with `strategyParams` but missing `strategy` fails (resolves F-7).
     - Options profile with stocks `strategy` or `strategyParams` fails.
     - `sanitizeSearchProfiles` filters out malformed items and preserves valid items.

3. **`frontend/lib/searchProfilesStore.ts`**:
   - Imports `isValidSearchProfile`, `sanitizeSearchProfiles`, and `safeCompareTimestamps`.
   - Implements `searchProfilesPersistStorage: PersistStorage<PersistedSearchProfiles>` directly without `createJSONStorage` (resolves F-2).
   - In `searchProfilesPersistStorage.getItem`: returns current version for future envelopes to suppress hydration rewrite (satisfies S3).
   - In `searchProfilesPersistStorage.setItem`: inspects `localStorage.getItem` directly at write time (resolves F-3) and refuses write if disk contains `version > CURRENT_VERSION` (resolves F-4).
   - In `persist`: adds `options.merge` with `sanitizeSearchProfiles` (resolves F-1).
   - In `migrate`: applies `sanitizeSearchProfiles` across legacy version branches (<3, <4, <5).

4. **`frontend/components/organisms/SearchProfileBar/index.tsx`**:
   - Uses `isValidSearchProfile` to filter profiles.
   - Uses `safeCompareTimestamps(a.updatedAt, b.updatedAt)`.

5. **`frontend/components/organisms/SearchProfileBar/__tests__/SearchProfileBar.malformed.test.tsx`** (NEW):
   - Integration tests:
     - Injects version 5 localStorage payload with `[ { ...base, updatedAt: null }, validProfile ]`.
     - Rehydrates store: asserts only `validProfile` is retained in store (`profiles.length === 1`).
     - Injects single profile with `updatedAt: null`: asserts `profiles.length === 0`.
     - Renders `SearchProfileBar` on Step 3: asserts Search Profile control renders without crash and dropdown is visible and accessible.
     - Future-version envelope (`version: 9999` with `futureAuditSentinel`):
       - Rehydrates store and opens Step 3.
       - Asserts `localStorage.getItem('bamendjou:search-profiles')` preserves `version: 9999` and `futureAuditSentinel` byte-for-byte (`beforeRaw === afterRaw`).
       - Asserts dropdown still displays the profile in UI.
       - Asserts subsequent `saveProfile` does not downgrade version to 5 or strip `futureAuditSentinel` on disk.

6. **`docs/superpowers/PROJECT_STATE.json`**:
   - Register phase `APP-AUDIT-B-PROFILE-VALIDATION`:
     - `status`: `"in_progress"`
     - `branch`: `"board/app-audit-b-profile-validation-0d83ab07"`
     - `tracking_issue`: `381`
     - `verify`: probe matching `isValidSearchProfile` in `frontend/lib/searchProfileValidation.ts`

---

## 5. Verification & Test Plan
1. `npm --prefix frontend test -- searchProfileValidation.test.ts` -> 100% green.
2. `npm --prefix frontend test -- SearchProfileBar.malformed.test.tsx` -> 100% green.
3. `npm --prefix frontend test -- searchProfile` -> all existing search profile tests pass.
4. `npm --prefix frontend run typecheck` (`tsc --noEmit`) -> 0 errors.
5. Node probe check:
   Run `source-probe.cjs` logic verifying `check('malformed current profile rejected', 0, ...)` passes.
6. `python scripts/state.py` -> verify presence probe and 0 drift.
