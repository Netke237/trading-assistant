# Plan Audit Round 1: APP-AUDIT-B-PROFILE-VALIDATION (#381)

**Date**: 2026-10-21  
**Reviewer**: Fresh independent subagent `62cee8e5-b069-4a8d-a27c-a5f531642c0b` (role: `Independent Plan Auditor`)  
**Target Plan**: `docs/superpowers/plans/2026-10-21-app-audit-b-profile-validation-plan.md`  
**Target Issue**: #381 (Malformed current-version profile crashes the Search Profile controls)  

---

## Adversarial Findings

### Finding F-1
- **File & Line**: `docs/superpowers/plans/2026-10-21-app-audit-b-profile-validation-plan.md:77-81`, `97-99`, `149` (Sections 3.B.1, 3.B.2, 4.3)
- **Problem**: In Zustand persist middleware, `migrate` only executes when stored version differs from configured version (`deserialized.version !== options.version`). When stored version is 5 and configured version is 5, `migrate` is skipped entirely. Relying solely on `migrate` for profile sanitization leaves version 5 malformed profiles unsanitized in memory on rehydration.
- **Fix**: Hook profile sanitization into `options.merge` (which runs unconditionally on every hydration across all versions) and in `storage.getItem`.

### Finding F-2
- **File & Line**: `docs/superpowers/plans/2026-10-21-app-audit-b-profile-validation-plan.md:148` (Section 4.3) vs `lines 83-112` (Section 3.B.2)
- **Problem**: Section 4.3 instructed wrapping the storage adapter in `createJSONStorage`, but Section 3.B.2 defined an adapter returning `{ state, version }` objects. `createJSONStorage` internally calls `JSON.parse()` on the return of `getItem`, which throws `SyntaxError: Unexpected token 'o', "[object Object]" is not valid JSON` when passed an object.
- **Fix**: Directly implement the typed `PersistStorage<SearchProfilesState>` interface and pass it directly to `persist(..., { storage: searchProfilesPersistStorage })` without `createJSONStorage`.

### Finding F-3
- **File & Line**: `docs/superpowers/plans/2026-10-21-app-audit-b-profile-validation-plan.md:100-111` (Section 3.B.2)
- **Problem**: In `setItem`, checking an in-memory `activeFutureEnvelope` flag fails to detect cross-tab or external writes where a future envelope was written to localStorage after Tab A mounted.
- **Fix**: In `setItem`, inspect `localStorage.getItem(name)` directly at write time. If `localStorage.getItem(name)` contains `version > CURRENT_VERSION`, trigger the future envelope preservation/write-barrier logic.

### Finding F-4
- **File & Line**: `docs/superpowers/plans/2026-10-21-app-audit-b-profile-validation-plan.md:105` (Section 3.B.2)
- **Problem**: If an older client saves a profile while a future envelope is present, overwriting `envelope.state.profiles = value.state.profiles` would delete valid future-version profiles (e.g. unknown modes like `crypto`) that the older client filtered out.
- **Fix**: Enforce a strict write barrier: when `version > CURRENT_VERSION`, refuse writes / disallow modifications to future-version stores from an older client, keeping disk bytes completely intact and untouched as specified by Finding S3.

### Finding F-5
- **File & Line**: `docs/superpowers/plans/2026-10-21-app-audit-b-profile-validation-plan.md:62` (Section 3.A.1)
- **Problem**: `universe` validation did not require `minPriceRaw`, `maxPriceRaw`, `minCapRaw`, `maxCapRaw` to be strings. If `null`, `Number(null) === 0` and `null !== ''` causes `min_price: 0, max_price: 0` to be sent on scan requests.
- **Fix**: In `isValidSearchProfile`, require `minPriceRaw`, `maxPriceRaw`, `minCapRaw`, and `maxCapRaw` to be strings.

### Finding F-6
- **File & Line**: `docs/superpowers/plans/2026-10-21-app-audit-b-profile-validation-plan.md:67` (Section 3.A.1)
- **Problem**: `confidenceGate` missing `atrMult` causes `TypeError` in `resolveProfileToScanRequest` (`settingsStore.ts:94`).
- **Fix**: In `isValidSearchProfile`, validate that `confidenceGate` contains boolean `enabled`, finite numeric `cautionBelow` and `rejectBelow`, and a valid `atrMult` object with per-horizon target and stop pairs (or ensure `sanitizeSearchProfiles` backfills `DEFAULT_CONFIDENCE_GATE.atrMult`).

### Finding F-7
- **File & Line**: `docs/superpowers/plans/2026-10-21-app-audit-b-profile-validation-plan.md:68-70` (Section 3.A.1)
- **Problem**: A stocks profile with `strategyParams` but `strategy: undefined` passes validation and sets `scanStore.activeStrategy` to `null` while loading strategy params, breaking scan execution and schedule resolution.
- **Fix**: In `isValidSearchProfile`, enforce that for `p.mode === 'stocks'`: `((p.strategy === undefined && p.strategyParams === undefined) || (typeof p.strategy === 'string' && typeof p.strategyParams === 'object' && p.strategyParams !== null && !Array.isArray(p.strategyParams)))`.

---

GATE FINDINGS: 7
