# Independent Adversarial Code Audit (Round 3): APP-AUDIT-B-PROFILE-VALIDATION (#381)

**Reviewer**: Fresh Independent Subagent (`cd7400dd-1aef-45a8-994f-193b02602246`)  
**Target Commit Diff**: `git diff c238a18d..b4e4e00a`  
**Full Feature Diff Context**: `git diff origin/main..HEAD`  
**Approved Plan**: `docs/superpowers/plans/2026-10-21-app-audit-b-profile-validation-plan.md`  
**Preceding Audit Record**: `docs/superpowers/audits/APP-AUDIT-B-PROFILE-VALIDATION/code-r2.md`

---

## 1. Audit Focus & Specific Checks

### Check 1: Test Fixture Conformance in `stocksHorizonProfileRequests.test.ts`
In commit `b4e4e00a`, `frontend/lib/__tests__/stocksHorizonProfileRequests.test.ts` was updated to supply `baseProfile` schema fields to the `v4 -> v5` `searchProfilesStore` migration test fixture:
- The supplied `baseProfile` provides all mandatory schema fields: valid ISO-8601 timestamps (`createdAt`, `updatedAt`), valid `direction` (`'Bullish'`), `horizonPreset` (`'Swing'`), finite `holdMin`/`holdMax` bounds (5/15), string-typed universe bounds (`pick: 'SP500'`, `capUnit: 'B'`, empty string price/cap primitives), and a complete `scanSettings.confidenceGate` structure with numeric per-horizon `atrMult` pairs (`intraday`, `swing`, `position`).
- The `stocks` profile fixture specifies co-present `strategy` and `strategyParams`, while the `options` profile fixture leaves both undefined.
- Both test fixtures now strictly satisfy `isValidSearchProfile(p)` and pass through `options.merge`'s `sanitizeSearchProfiles` without being dropped as malformed/corrupt records.

### Check 2: Integrity of `v4 -> v5` Migration Testing & Production Isolation
- **Verification of Migration Logic**: The test verifies that during store rehydration (`await useSearchProfilesStore.persist.rehydrate()`), the `version < 5` branch in `searchProfilesStore.ts` properly executes against the legacy payload, stripping all `OVERRIDE_FIELDS` from `strategyParams` to restore "follow profile" semantics, while preserving untuned parameters (`btMinTrades: 12`, `btMinWinRate: 0.5`) and `scanOverrides` (`{ fast_ema: 11 }`). Upon rehydration, Zustand advances the stored disk payload to `version: 5`.
- **Zero Production / Runtime Impact**: The diff in `b4e4e00a` is strictly confined to test code (`frontend/lib/__tests__/stocksHorizonProfileRequests.test.ts`: +32, -1 lines). No production code, runtime logic, numerical scoring algorithms, or persisted data structures were modified.

### Check 3: Static & Runtime Verification
- **Search Profile Tests**: All search profile test suites passed:
  - `frontend/lib/__tests__/stocksHorizonProfileRequests.test.ts` (10/10 tests passed)
  - `frontend/lib/__tests__/searchProfilesIvMigration.test.ts` (passed)
  - `frontend/lib/__tests__/searchProfileSnapshot.test.ts` (passed)
  - `frontend/lib/__tests__/searchProfileValidation.test.ts` (passed)
  - `frontend/lib/__tests__/searchProfilesTargetMigration.test.ts` (passed)
  - `frontend/components/organisms/SearchProfileBar/__tests__/SearchProfileBar.validation.test.tsx` (passed)
  - `frontend/components/organisms/SearchProfileBar/__tests__/SearchProfileBar.malformed.test.tsx` (passed)
- **Full Suite Verification**: 300 out of 302 suites passed (5,783 passed tests; the only 2 failures are pre-existing Windows host locale formatting differences in `StockSendDialog.session.test.tsx` and `BarrierRaceCard.test.tsx` as documented in `AGENTS.md`).
- **TypeScript Typecheck**: Clean (`npm run typecheck` / `tsc --noEmit` exited with code 0).
- **Project State Consistency**: `python scripts/state.py` verified with zero drift; the presence probe for `isValidSearchProfile` remains valid.
- **Production Profiles Validation**: Verified directly against all 18 production profiles in `docs/search-profiles/search-profiles-export.json`; all 18 profiles conform strictly to `isValidSearchProfile`.

---

## 2. Gate Evaluation

Per AUDIT-RULE-V2, a finding blocks only if it can put a **WRONG NUMBER** in front of a user or on a broker order, or **CORRUPT PERSISTED DATA**.

What was inspected to evaluate the gate:
1. `stocksHorizonProfileRequests.test.ts`: Verified that supplying `baseProfile` matches real production profiles created by `captureCurrentSnapshot` across historical versions and does not mask migration regressions.
2. `searchProfilesStore.ts`: Traced `searchProfilesPersistStorage.getItem`, `setItem`, `migrate`, and `options.merge`. Verified that future-version envelopes (`version > 5`) are preserved byte-for-byte on disk, write attempts over newer versions are refused, and malformed current or legacy profiles cannot inject undefined/corrupt state into the Zustand store.
3. `searchProfileValidation.ts`: Verified that all mandatory schema fields (mode, timestamps, direction, horizon, universe price/cap strings, confidenceGate with complete atrMult, strategy co-presence) are strictly enforced.
4. `SearchProfileBar/index.tsx`: Verified that malformed profiles cannot cause runtime exceptions in sorting or dropdown rendering, and selection safely passes validated objects.

No gate-violating conditions exist.

---

GATE FINDINGS: 0
