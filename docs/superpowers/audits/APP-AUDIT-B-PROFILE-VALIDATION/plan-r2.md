# Plan Audit Round 2: APP-AUDIT-B-PROFILE-VALIDATION (#381)

**Date**: 2026-10-21  
**Reviewer**: Fresh independent subagent `ca30fe55-d9c2-4e10-8480-1c541e6793fb` (role: `Independent Plan Auditor`)  
**Target Document**: `docs/superpowers/plans/2026-10-21-app-audit-b-profile-validation-plan.md`  
**Target Issue**: #381 (Malformed current-version profile crashes Search Profile controls / future-version write barrier)  
**Review Scope**: Round 1 fixes (F-1 through F-7) and their interactions.

---

## 1. Review of Round 1 Fixes & Interaction Analysis

### F-1: Sanitization in `options.merge`, `storage.getItem`, and `migrate`
- **Verification**: Cross-checked with Zustand v5's `persistImpl` (`node_modules/zustand/middleware.js:11520-11535`). In Zustand v5, `migrate` is bypassed when `deserializedStorageValue.version === options.version (5)`. By hooking `sanitizeSearchProfiles` into `options.merge` (which executes unconditionally on every hydration across all schema versions) and in `storage.getItem`, malformed current-version (v5) profiles are guaranteed to be filtered out before store state updates.
- **Interaction with Legacy Migrations**: Evaluated `storage.getItem` running before `migrate` on older versions (`version < 5`). `isValidSearchProfile` does not check specific keys in `scanOverrides` (e.g. `iv_abs_pass_max` or dropped target pcts) or require stripped `OVERRIDE_FIELDS` from `strategyParams`, so legacy profiles are not prematurely discarded by sanitization before `migrate` runs its version-specific upgrades.

### F-2: Direct `PersistStorage<PersistedSearchProfiles>` Implementation
- **Verification**: Checked against `node_modules/zustand/middleware/persist.d.ts`. Implementing `PersistStorage<PersistedSearchProfiles>` directly and providing it to `persist(..., { storage })` without `createJSONStorage` avoids `createJSONStorage` invoking `JSON.parse` on object returns (`StorageValue`). The shape `{ state: PersistedSearchProfiles, version?: number }` matches Zustand's contract cleanly.

### F-3 & F-4: Direct Disk Inspection at Write Time & Strict Write Barrier
- **Verification**: Checked against Finding S3 and `followup/storage/browser.cjs:108` (`check('unknown future version preserves bytes until explicit compatible migration', JSON.stringify(future), after[KEY])`).
  - During hydration of `version > CURRENT_VERSION`, `storage.getItem` returns `version: CURRENT_VERSION` to Zustand. Because `deserializedStorageValue.version === options.version (5)`, Zustand does not mark `migrated = true` and does not invoke an automatic `setItem()` overwrite during hydration.
  - During subsequent writes (e.g. `saveProfile`, `updateProfile`), inspecting `localStorage.getItem(name)` directly at write time avoids in-memory race conditions across tabs. If disk contains `version > CURRENT_VERSION`, `setItem` refuses writes and returns without invoking `localStorage.setItem`. Disk bytes remain 100% byte-exact (`beforeRaw === afterRaw`), preventing the erasure of unknown future-version profiles and sentinels.

### F-5: String Primitives for Universe Price/Cap Bounds
- **Verification**: Checked against `types/searchProfile.ts` (`SearchProfileUniverse`) and `resolveOptionsScanRequest.ts:102-105` / `resolveStockScanRequest.ts`. Requiring `minPriceRaw`, `maxPriceRaw`, `minCapRaw`, and `maxCapRaw` to be string primitives prevents `null` coercion (`Number(null) === 0` with `null !== ''`), which would otherwise inject `min_price: 0, max_price: 0` into backend scan requests.

### F-6: Complete `confidenceGate` & `atrMult` Horizon Pairs Validation
- **Verification**: Checked against `settingsStore.ts:90-95` (`atrMultForHorizon`), `resolveOptionsScanRequest.ts:144`, and `resolveProfileToScanRequest`. Requiring boolean `enabled`, finite numeric `cautionBelow`/`rejectBelow`, and a non-null `atrMult` object with `intraday`, `swing`, and `position` numeric `target`/`stop` pairs prevents `TypeError: Cannot read properties of undefined (reading 'intraday'/'position'/'swing')` during scan request construction, and prevents malformed confidence gate objects from corrupting persisted `settingsStore` state on profile application.

### F-7: Stocks Strategy and `strategyParams` Co-Presence / Options Undefined
- **Verification**: Checked against `searchProfileSnapshot.ts:101-109` (`applySearchProfile`), `types/searchProfile.ts:47-50`, and `scanScheduleResolve.ts:102-107`. Requiring both `strategy` and `strategyParams` to be undefined or both present for stocks profiles (and both undefined for options profiles) prevents orphaned strategy params from running with `activeStrategy: null`, and prevents options profiles from carrying dormant strategy state that could corrupt Stocks scan execution.

### Empirical Validation on Real Fixtures
- Tested all 18 production search profiles from `docs/search-profiles/search-profiles-export.json` against the plan's `isValidSearchProfile` specification. All 18 profiles pass validation.

---

## 2. Conclusion

All 7 findings from Round 1 have been accurately addressed. Mechanisms and interactions are sound against the real code and Zustand v5 middleware contracts. No gate violations (wrong numbers in front of users / on broker orders, or persisted data corruption) were found.

GATE FINDINGS: 0
