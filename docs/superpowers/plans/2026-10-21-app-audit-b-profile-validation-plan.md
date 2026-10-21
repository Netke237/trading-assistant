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
   - `universe`: non-null object with `typeof p.universe.pick === 'string'`, `typeof p.universe.customRaw === 'string'`, `p.universe.capUnit === 'M' || p.universe.capUnit === 'B'`.
   - `horizonPreset`: `typeof p.horizonPreset === 'string' && p.horizonPreset.trim().length > 0`.
   - `holdMin`: `typeof p.holdMin === 'number' && !isNaN(p.holdMin)`.
   - `holdMax`: `typeof p.holdMax === 'number' && !isNaN(p.holdMax)`.
   - `scanOverrides`: `typeof p.scanOverrides === 'object' && p.scanOverrides !== null && !Array.isArray(p.scanOverrides)`.
   - `scanSettings`: `typeof p.scanSettings === 'object' && p.scanSettings !== null && typeof p.scanSettings.confidenceGate === 'object' && p.scanSettings.confidenceGate !== null`.
   - If `p.mode === 'stocks'`:
     - If `p.strategy !== undefined`: must be string.
     - If `p.strategyParams !== undefined`: must be non-null object.
2. `sanitizeSearchProfiles(profiles: unknown): SearchProfile[]`:
   - If `!Array.isArray(profiles)`, returns `[]`.
   - Filters entries using `isValidSearchProfile`.
   - Returns only structurally valid profiles.

### B. Store Rehydration, Migration & Future-Version Write Barrier (`frontend/lib/searchProfilesStore.ts`)
1. **Migration Sanitization**:
   - In `migrate(persistedState, version)`:
     - After running version-specific branches (<3, <4, <5), apply `sanitizeSearchProfiles`:
       `st.profiles = sanitizeSearchProfiles(st.profiles);`
     - Ensures corrupt or malformed profiles never enter `state.profiles`.
2. **Future-Version Write Barrier in Storage Adapter**:
   Wrap `localStorage` in a dedicated storage adapter for `useSearchProfilesStore`:
   - `CURRENT_VERSION = 5`.
   - `getItem(name: string)`:
     - Reads raw string from `localStorage.getItem(name)`.
     - If null, empty, or unparseable JSON, passes through to default handling.
     - Parses JSON:
       - If `typeof parsed.version === 'number' && parsed.version > CURRENT_VERSION`:
         - Future envelope detected (e.g. `version: 9999` with `futureAuditSentinel`).
         - Cache future envelope metadata in a module-scoped record: `activeFutureEnvelope = { raw: rawString, version: parsed.version, parsed }`.
         - Extract and sanitize profiles from `parsed.state?.profiles`:
           `const safeProfiles = sanitizeSearchProfiles(parsed.state?.profiles);`
         - Return to Zustand: `{ state: { profiles: safeProfiles, legacyTargetPctDropped: false }, version: CURRENT_VERSION }`.
         - **Key Mechanism**: Because `deserializedStorageValue.version === options.version (5)`, Zustand's `hydrate()` evaluates `version !== options.version` as `false`. Zustand does **not** flag `migrated = true` and does **not** call `setItem()` during hydration!
         - **Result**: `localStorage.getItem('bamendjou:search-profiles')` remains 100% byte-for-byte identical to the original future envelope (`beforeRaw === afterRaw`).
       - If `parsed.version <= CURRENT_VERSION`:
         - Clear `activeFutureEnvelope = null`.
         - Return parsed object.
   - `setItem(name: string, value: StorageValue<SearchProfilesState>)`:
     - If `activeFutureEnvelope` is set (a future envelope is on disk):
       - Re-read `localStorage.getItem(name)`. If it still contains a future version (`version > CURRENT_VERSION`):
         - Parse the stored future envelope:
           `const envelope = JSON.parse(currentRaw);`
         - Update `envelope.state.profiles = value.state.profiles;`
         - If `value.state.legacyTargetPctDropped !== undefined`: `envelope.state.legacyTargetPctDropped = value.state.legacyTargetPctDropped;`
         - Preserve `envelope.version` (e.g. 9999) and all unknown root/state properties (e.g. `futureAuditSentinel`)!
         - Write back `localStorage.setItem(name, JSON.stringify(envelope))`.
         - Never downgrade `version` to 5!
     - Else:
       - Normal write: `localStorage.setItem(name, JSON.stringify(value))`.

### C. Component Defense in `SearchProfileBar/index.tsx`
1. Defensively filter and sort `modeProfiles`:
   ```ts
   const modeProfiles = profiles
     .filter(isValidSearchProfile)
     .filter((p) => p.mode === activeMode)
     .sort((a, b) => (b.updatedAt || '').localeCompare(a.updatedAt || ''));
   ```
2. Safe fallback:
   If `a.updatedAt` or `b.updatedAt` is missing or null, `(b.updatedAt || '').localeCompare(a.updatedAt || '')` treats missing timestamps as lowest priority without throwing.
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
     - Valid stocks profile passes.
     - `updatedAt: null` or invalid date string fails.
     - `createdAt: null` or invalid date string fails.
     - Missing or empty `id` / `name` fails.
     - Invalid `mode` fails.
     - Missing `direction` or invalid string fails.
     - Corrupt `universe` or `scanSettings` fails.
     - `sanitizeSearchProfiles` filters out malformed items and preserves valid items.

3. **`frontend/lib/searchProfilesStore.ts`**:
   - Imports `isValidSearchProfile` and `sanitizeSearchProfiles`.
   - Wraps storage with future-version write barrier in `createJSONStorage`.
   - In `migrate`: applies `sanitizeSearchProfiles` across all versions.
   - Preserves future envelopes on subsequent writes without downgrade.

4. **`frontend/components/organisms/SearchProfileBar/index.tsx`**:
   - Uses `isValidSearchProfile` to filter profiles.
   - Uses safe timestamp comparator `(b.updatedAt || '').localeCompare(a.updatedAt || '')`.

5. **`frontend/components/organisms/SearchProfileBar/__tests__/SearchProfileBar.malformed.test.tsx`** (NEW):
   - Integration tests:
     - Injects version 5 localStorage payload with `[ { ...base, updatedAt: null }, validProfile ]`.
     - Rehydrates store: asserts only `validProfile` is retained in store (`profiles.length === 1`).
     - Injects single profile with `updatedAt: null`: asserts `profiles.length === 0`.
     - Renders `SearchProfileBar` on Step 3: asserts Search Profile control renders without crash and dropdown is visible and accessible.
     - Future-version envelope (`version: 9999` with `futureAuditSentinel`):
       - Rehydrates store and opens Step 3.
       - Asserts `localStorage.getItem('bamendjou:search-profiles')` preserves `version: 9999` and `futureAuditSentinel`.
       - Asserts dropdown still displays the profile in UI.
       - Asserts modifying or saving a profile does not downgrade version to 5 or strip `futureAuditSentinel`.

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
