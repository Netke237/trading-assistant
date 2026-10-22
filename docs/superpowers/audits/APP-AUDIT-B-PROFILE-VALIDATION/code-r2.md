# Independent Adversarial Code Audit (Round 2): APP-AUDIT-B-PROFILE-VALIDATION (#381)

**Reviewer**: Fresh Independent Subagent (`580a82ab-4a1a-4eb4-89c5-794163ad1303`)  
**Target Fix Diff**: `git diff 1be70ab8..23f09a92`  
**Full Context Diff**: `git diff origin/main..HEAD`  
**Approved Plan**: `docs/superpowers/plans/2026-10-21-app-audit-b-profile-validation-plan.md`  
**Preceding Audit Record**: `docs/superpowers/audits/APP-AUDIT-B-PROFILE-VALIDATION/code-r1.md`  

---

## 1. Scope & Audit Focus
This round reviewed the Code Round 1 fix for Finding F-1 (`23f09a92`) and its interactions with the rest of the search profile system:
1. **Verification of F-1 Fix in `frontend/lib/searchProfileValidation.ts`**:
   - In Code Round 1, fields were guarded by `if (obj.field !== undefined)`, permitting incomplete profiles (e.g. omitting `confidenceGate` or `direction`) to pass validation and corrupt `settingsStore` (`bamendjou-settings`) or crash scan resolution (`resolveProfileToScanRequest`).
   - In `23f09a92`, all optional guards for core schema properties were removed and replaced with strictly mandatory non-optional assertions:
     - `mode`: strictly mandatory `'options' | 'stocks'`.
     - `createdAt` & `updatedAt`: strictly mandatory non-empty strings parseable by `Date.parse()`.
     - `direction`: strictly mandatory `'Bullish' | 'Bearish'`.
     - `horizonPreset`: strictly mandatory non-empty string.
     - `holdMin` & `holdMax`: strictly mandatory finite numbers (tested with `0` for Intraday mode).
     - `universe`: strictly mandatory object requiring non-empty string `pick`, string `customRaw`, valid `capUnit` (`'M' | 'B'`), and all 4 price/cap fields (`minPriceRaw`, `maxPriceRaw`, `minCapRaw`, `maxCapRaw`) as string primitives.
     - `scanOverrides`: strictly mandatory non-null, non-array object.
     - `scanSettings`: strictly mandatory non-null, non-array object requiring `confidenceGate` with boolean `enabled`, finite number `cautionBelow` / `rejectBelow`, and a non-null `atrMult` object with finite numeric `target` and `stop` pairs across all three horizons (`intraday`, `swing`, `position`).
     - Strategy fields: stocks-mode profiles strictly require co-presence or co-absence of `strategy` and `strategyParams`; options-mode profiles strictly require both to be undefined.

2. **Interactions Checked**:
   - **Store Hydration & Migration (`frontend/lib/searchProfilesStore.ts`)**:
     - `searchProfilesPersistStorage.getItem`: When `version > 5` (future schema), returns `version: 5` with sanitized profiles, preventing Zustand from running `migrate` or writing to disk during hydration. Byte-exact preservation (`beforeRaw === afterRaw`) is preserved.
     - When `version < 5` (legacy schema), `getItem` passes raw profiles to `migrate()` so legacy fields (e.g., `iv_rank_pass_max`, `rr_bullish_target_pct`, strategy defaults) can be upgraded before `options.merge()` applies `sanitizeSearchProfiles()`.
     - `options.merge`: Unconditionally runs `sanitizeSearchProfiles()` on hydration across all versions, preventing malformed objects from reaching in-memory store state.
   - **Future-Version Write Barrier (`searchProfilesPersistStorage.setItem`)**:
     - At write time (`saveProfile`, `updateProfile`, `deleteProfile`), disk contents are inspected via `localStorage.getItem(name)`. If a future version (`version > 5`) is present on disk, write is refused with a warning, preserving future unknown modes and sentinels.
   - **Search Profile Bar Rendering & Selection (`SearchProfileBar/index.tsx`)**:
     - `modeProfiles` filters with `isValidSearchProfile` and sorts using `safeCompareTimestamps(a.updatedAt, b.updatedAt)`.
     - Selection and application (`applySearchProfile`) safely pass guaranteed valid structures to `setContext` and `setConfidenceGate`.
   - **Target Migration Test (`searchProfilesTargetMigration.test.ts`)**:
     - Verified that test fixtures were updated with full valid `baseProfile` fields, ensuring the test exercises actual migration without being rejected by `sanitizeSearchProfiles`.
   - **Production Profiles Compatibility**:
     - Evaluated all 18 production search profiles from `docs/search-profiles/search-profiles-export.json` against `isValidSearchProfile`. All 18 profiles conform strictly to the mandatory schema.

3. **Runtime & Static Verification**:
   - `npm --prefix frontend test -- searchProfile` -> 6/6 test suites passed (42 tests).
   - `npm --prefix frontend run typecheck` (`tsc --noEmit`) -> 0 errors.
   - `python scripts/state.py` -> 0 drift; presence probe for `isValidSearchProfile` intact.

---

## 2. Gate Evaluation
A finding blocks only if it can put a WRONG NUMBER in front of a user or on a broker order, or CORRUPT PERSISTED DATA.
- The schema requirements in `isValidSearchProfile` are strictly mandatory and exhaustive.
- All potential corruption paths identified in Round 1 (such as `setConfidenceGate(undefined)` or `direction: undefined`) are completely blocked.
- No reachable scenario was found that could corrupt persisted data, crash React rendering, or present incorrect scan/order values.

---

GATE FINDINGS: 0
