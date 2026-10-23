# Independent Adversarial Audit Report: SEARCH-PROFILES-RECAL-OPTIONS (#187)

**Target Issue:** #187 (SEARCH-PROFILES-RECAL-OPTIONS: Recalibrate the 18 Options search profiles after #121 and #161)  
**Diff Reviewed:** `origin/main` (`536da5f9`) .. `HEAD` (`30810e67`)  
**Approved Plan:** `docs/superpowers/plans/2026-10-22-search-profiles-recal-options-plan.md`  
**Reviewer:** Independent Subagent `ff1a887f-aa1f-464e-8820-c1047319286d` (Adversarial Auditor, applying `bmad-review-adversarial-general` / AUDIT-RULE-V2)  
**Date:** 2026-10-22  

---

## 1. Scope & Verification Performed

The diff between `origin/main` (`536da5f9`) and `HEAD` (`30810e67`) was inspected across all modified and newly created artifacts:
- `backend/scripts/run_options_profiles_measurement.py`
- `docs/search-profiles/MINI_PC_RUNBOOK.md`
- `docs/search-profiles/Bamendjou_Options_Search_Profiles.xlsx`
- `docs/search-profiles/README.md`
- `docs/search-profiles/import-search-profiles.js`
- `docs/search-profiles/search-profiles-export.json`
- `frontend/lib/__tests__/optionsSearchProfilesRecalibration.test.ts`
- `backend/tests/test_search_profiles_recalibration.py`
- `docs/superpowers/PROJECT_STATE.json`

Cross-checked against core production schemas, configurations, and resolvers:
- `backend/config/contract_rules.yaml` (`min_stock_score: 45`, `min_volume: 0`, `min_open_interest: 200`, `max_bid_ask_spread_pct: 0.20`)
- `backend/config/scoring_rules.yaml` (Position default event window 30/60; SemiAnnual override 7/30)
- `frontend/lib/searchProfileValidation.ts` (`isValidSearchProfile`, `sanitizeSearchProfiles`, Schema Version 5 guards)
- `frontend/lib/searchProfilesStore.ts` (Version 5, atomic persistence, write barrier, migration logic)
- `frontend/lib/resolveOptionsScanRequest.ts` (`buildOptionsScanRequestBody`)
- `frontend/lib/scanScheduleResolve.ts` (`resolveProfileToScanRequest`)
- `backend/app/schemas/__init__.py` (`ScanRequest` model fields and validation)

---

## 2. Detailed Verification Checks

1. **Preservation of Profile IDs:**
   - All 18 stable profile IDs (`mu2n6u2bxt11` through `mu2n6y1r5fyf`) are strictly preserved in their original order without drift, re-ordering, or regeneration across `search-profiles-export.json`, `import-search-profiles.js`, `Bamendjou_Options_Search_Profiles.xlsx`, and test fixtures.

2. **Schema Version 5 Conformance:**
   - Both `search-profiles-export.json` and the embedded `RAW` JSON in `import-search-profiles.js` match byte-for-byte and object-for-object with `version: 5` and a 18-element `state.profiles` array.
   - All 18 profiles pass strict runtime validation by `isValidSearchProfile`:
     - Explicit string primitives for universe bounds: `minPriceRaw: ""`, `maxPriceRaw: ""`, `minCapRaw: ""`, `maxCapRaw: ""`, `customRaw: ""`, `capUnit: "B"`.
     - Complete `atrMult` structure with valid `{ target, stop }` pairs for `intraday`, `swing`, and `position`.
     - Non-empty ISO timestamps parseable by `Date.parse`.

3. **Stocks Mode Strategy Field Omission:**
   - All 18 profiles are strictly `mode: "options"` and completely omit `strategy` and `strategyParams` (neither key is present on any profile object).

4. **3x3x2 Parameter Matrix Invariants:**
   - **Baseline:** Intraday and Swing overrides are empty `{}`; all 6 SemiAnnual profiles override `event_reject_days: 7, event_caution_days: 30`, preventing the 30/60 Position YAML default from rejecting viable 90–105d holds.
   - **Restrictive:** `max_bid_ask_spread_pct: 0.08, min_open_interest: 1000, min_volume: 50` (SemiAnnual) / `200` (Intraday/Swing).
   - **Loose:** `max_bid_ask_spread_pct: 0.3, preferred_spread_pct_max: 0.3, min_volume: 0, preferred_volume_min: 20, min_open_interest: 75, preferred_oi_min: 75, shortlistMaxCandidates: 20`.
   - **Directional Gates:** Bullish profiles set `deReject: 3`; Bearish profiles set `deReject: 10`.
   - All 18 rows and 18 columns in `Bamendjou_Options_Search_Profiles.xlsx` matched `search-profiles-export.json` exactly.

5. **Mini PC Measurement Script (`run_options_profiles_measurement.py`):**
   - Correctly translates each Schema v5 profile to a backend `ScanRequest` payload matching `buildOptionsScanRequestBody` and `ScanRequest` field-for-field.
   - Path resolution (`REPO_ROOT = Path(__file__).resolve().parents[2]`) accurately locates repo root and defaults across environments.
   - Reconfigures `sys.stdout` and `sys.stderr` for UTF-8 with fallback.
   - Standalone CLI dry-run executed successfully against all 18 profiles (`--dry-run` and `--markdown` verified).
   - Live HTTP execution (`POST /api/scan`) correctly targets the backend options scan router.

6. **Mini PC Runbook (`MINI_PC_RUNBOOK.md`):**
   - Executable instructions verified for Windows PowerShell and Linux bash, covering virtual environment activation, API token prerequisites, dry-run verification, live execution with `--symbols` or `--profile-id`, artifact paths, and troubleshooting.

7. **Persistence & Import Edge Cases:**
   - `import-search-profiles.js` creates a timestamped backup (`KEY + ":backup-" + ISO`) prior to mutating localStorage.
   - Merges by ID, safely retaining any user-defined custom profiles.
   - Preserves existing store version so standard Zustand migrations run without skipping steps.
   - Write barrier in `searchProfilesPersistStorage` prevents corruption from future schema versions.

8. **Test Execution & State Integrity:**
   - `npm run typecheck` passed with 0 errors.
   - Jest frontend test suite (`lib/__tests__/optionsSearchProfilesRecalibration.test.ts` and all 9 `searchProfile` suites, 60 tests) passed 100%.
   - Pytest backend test suite (`backend/tests/test_search_profiles_recalibration.py`, 6 tests) passed 100% under Python 3.11.15.
   - `python scripts/state.py` verified 0 drift against `PROJECT_STATE.json`.

---

## 3. Gate Findings

Under AUDIT-RULE-V2 and the adversarial audit brief:
- A finding blocks only if it can put a **WRONG NUMBER** in front of a user or on a broker order, or **CORRUPT PERSISTED DATA**.
- A comment counts only if a competent reader acting on it would write a wrong change (misstates mechanism).

Every numeric parameter, filter override, schema validation check, and persistence path was verified against production code, backend YAML configs, and test runners. No condition was found that produces wrong numbers or persists corrupted data.

GATE FINDINGS: 0
