# Execution Plan: Recalibrate the 18 Options Search Profiles (SEARCH-PROFILES-RECAL-OPTIONS, #187)

**Phase ID:** `SEARCH-PROFILES-RECAL-OPTIONS`  
**Tracking Issue:** [#187](https://github.com/Netke237/trading-assistant/issues/187)  
**Parent Programme:** Issue #151 (Board Queue Tier 3, Item 4)  
**Date:** 2026-10-22  
**Owner:** Agent (`board/search-profiles-recal-options-20a39a3a`)  
**Design / Spec:** `docs/search-profiles/README.md`  
**Decisions Cited:**
- Kenneth 2026-10-15 on issue #187 (approved all 3 recommendations: proceed after #121 and #161; provide mini-PC script + runbook for live profile runs; keep 3x3x2 structure).
- `MEAS-DAY2-ANSWERS-2026-10-11` (min_stock_score 45 on both directions; bearish_min_trend Swing 30, Position 40; confidence_reject_below 35; preferred_iv_rank_max stays at 55 until #189).
- `CONTRACT-LIQUIDITY-DTE` (#161, PR #213 merged): volume is an optional floor (default 0), one liquidity soft flag.

---

## 1. Goal & Boundaries

### Goal
Re-derive and recalibrate every filter and threshold value across all 18 Options search profiles (`Intraday` / `Swing` / `SemiAnnual` × `Baseline` / `Restrictive` / `Loose` × `Bullish` / `Bearish`) based on measured evidence from MEAS Days 1 & 2 (#121) and the post-#161 contract liquidity rules. Provide a reproducible measurement script and runbook for Kenneth to execute profile scans on the mini PC with live market data, update all export artifacts (`search-profiles-export.json`, `import-search-profiles.js`, `Bamendjou_Options_Search_Profiles.xlsx`, `docs/search-profiles/README.md`), and verify via comprehensive backend and frontend test suites.

### Boundaries & Invariants
- **Stable Profile IDs:** All 18 profile IDs must remain 100% stable (`mu2n6u2bxt11` through `mu2n6y1r5fyf`) to preserve compatibility with existing user localStorage backups and scheduled scan entries.
- **Store Schema Compatibility:** Export artifacts must match `searchProfilesStore` Schema Version 5 (`CURRENT_SEARCH_PROFILES_SCHEMA_VERSION = 5`), passing `isValidSearchProfile` runtime validation without requiring ad-hoc manual migrations.
- **Zero Production Logic Modifications:** No changes to `backend/config/*.yaml`, scoring algorithms (`stock_scorer.py`, `contract_validator.py`), or core broker execution logic.
- **No Stocks Mode Intrusion:** All 18 profiles are strictly `mode: 'options'` with `strategy: undefined` and `strategyParams: undefined`.
- **Runtime Environment:** Python 3.11 for all backend scripts and test suites.

---

## 2. Evidence Basis & Parameter Matrix

The 18 profiles are organized into a 3 × 3 × 2 grid:
- **3 Horizon Groups:**
  - `Intraday`: Hold 0–2 days, DTE window 1–4 days.
  - `Swing`: Hold 5–15 days, DTE window 10–30 days.
  - `SemiAnnual`: Hold 90–105 days, DTE window 180–210 days.
- **3 Tiers:**
  - `Baseline`: Unmodified application defaults (`scanOverrides: {}` except SemiAnnual event windows).
  - `Restrictive`: Tighter liquidity/spread floors (`max_bid_ask_spread_pct: 0.08`, `min_open_interest: 1000`, `min_volume: 200` for Intraday/Swing and `50` for SemiAnnual).
  - `Loose`: Wider floors to increase yield (`max_bid_ask_spread_pct: 0.30`, `preferred_spread_pct_max: 0.30`, `min_volume: 0`, `preferred_volume_min: 20`, `min_open_interest: 75`, `preferred_oi_min: 75`, `shortlistMaxCandidates: 20`).
- **2 Directions:**
  - `Bullish`: `fundamentalsGate.deReject: 3`
  - `Bearish`: `fundamentalsGate.deReject: 10` (permitting heavy debt for short put/put buyer setups where loss is capped at premium)

### Detailed Parameter Evidence Table
| Parameter | Baseline | Restrictive | Loose | Evidence / Rationale |
|---|---|---|---|---|
| `min_stock_score` | 45 (inherited) | 45 (inherited) | 45 (inherited) | MEAS Day 2 (#121, decision `MEAS-DAY2-ANSWERS-2026-10-11`): lowered from 55 to 45 in `contract_rules.yaml`. |
| `max_bid_ask_spread_pct` | 0.20 (inherited) | 0.08 (explicit) | 0.30 (explicit) | MEAS Day 1 & 2 C6 liquidity observations: 0.08 enforces tight institutional quotes; 0.30 accommodates wider retail spreads. |
| `preferred_spread_pct_max` | 0.08 (inherited) | 0.08 (inherited) | 0.30 (explicit) | Soft rank floor alignment (PR #213 / commit `ab705ea7`). Loose tier widens soft penalty ceiling to prevent `too_many_soft_failures`. |
| `min_volume` | 0 (inherited) | 200 (Intraday/Swing), 50 (SemiAnnual) | 0 (explicit) | PR #213: volume is optional floor (0 = off). SemiAnnual 50 is a measured judgement from 200-DTE strike trading volumes. |
| `preferred_volume_min` | 200 (inherited) | 200 (inherited) | 20 (explicit) | Loose tier lowers soft volume floor to 20 contracts. |
| `min_open_interest` | 200 (inherited) | 1000 (explicit) | 75 (explicit) | Restrictive enforces 1000 OI; Loose relaxes to 75 OI to permit trading early-cycle contracts. |
| `preferred_oi_min` | 1000 (inherited) | 1000 (inherited) | 75 (explicit) | Soft OI threshold matched to hard floor for Loose tier. |
| `event_reject_days` | 21 Swing / 45 SemiAnnual (inherited) | Same (Intraday/Swing) / 7 (SemiAnnual) | Same (Intraday/Swing) / 7 (SemiAnnual) | SemiAnnual hold of 90-105d crosses earnings; 7/30 window blocks entering immediately before earnings while allowing long-cycle holds. |
| `event_caution_days` | 45 Swing / 60 SemiAnnual (inherited) | Same (Intraday/Swing) / 30 (SemiAnnual) | Same (Intraday/Swing) / 30 (SemiAnnual) | 30d caution window for SemiAnnual. |
| `shortlistMaxCandidates` | 10 | 10 | 20 | Loose tier raises candidate cap to 20 so wider filters do not artificially truncate candidate visibility. |
| `deReject` (Bullish) | 3 | 3 | 3 | Standard safety gate protecting bullish equity exposure against excessive leverage. |
| `deReject` (Bearish) | 10 | 10 | 10 | Bearish put strategies cap risk at premium; high debt is integral to the short thesis. |

---

## 3. Work Breakdown & Implementation Tasks

### Task 1: Mini PC Measurement Harness & Runbook
1. **Script (`backend/scripts/run_options_profiles_measurement.py`):**
   - Headless CLI script executable in Python 3.11.
   - Iterates through all 18 profiles defined in `docs/search-profiles/search-profiles-export.json`.
   - Resolves each profile to an `OptionsScanRequestBody` using pure logic matching `resolveOptionsScanRequest.ts`.
   - Executes scan against backend services or mock/offline fixtures (with `--dry-run` and `--live` flags).
   - Generates summary report containing candidate counts, contract score distributions, and rejection reason breakdown.
2. **Runbook (`docs/search-profiles/MINI_PC_RUNBOOK.md`):**
   - Step-by-step instructions for Kenneth to run the harness on the mini PC with live market data.
   - Outlines prerequisites, environment setup, execution commands, and output verification.

### Task 2: Profile Export Artifacts & Recalibration
1. **`docs/search-profiles/search-profiles-export.json`:**
   - Update schema version to `5`.
   - Preserve all 18 exact profile IDs (`mu2n6u2bxt11` ... `mu2n6y1r5fyf`).
   - Validate that all 18 profiles conform strictly to `SearchProfile` schema:
     - `universe`: `pick: "SP500"`, `customRaw: ""`, `minPriceRaw: ""`, `maxPriceRaw: ""`, `minCapRaw: ""`, `maxCapRaw: ""`, `capUnit: "B"`.
     - `confidenceGate`: `enabled: true`, `cautionBelow: 50`, `rejectBelow: 35`, full `atrMult` block.
     - `spreads`: `shortLegDelta: 0.3`, `widthPoints: 5`, `ivRankThreshold: 50`, `ivAbsThreshold: 50`, `minCredit: 0.5`, `maxDebitPctOfWidth: 40`.
     - `strategy: undefined`, `strategyParams: undefined`.
   - Set `updatedAt` to `2026-10-22T08:00:00.000Z`.
2. **`docs/search-profiles/import-search-profiles.js`:**
   - Synchronize embedded `RAW` JSON string to match `search-profiles-export.json` exactly.
3. **`docs/search-profiles/Bamendjou_Options_Search_Profiles.xlsx`:**
   - Update workbook using `openpyxl`:
     - Update sheet `Search Profiles` with calibrated values.
     - Update sheet `Legend & Notes` with `Recalibration of 2026-10-22` section documenting #121 (min_stock_score 45) and #161 liquidity rule alignment.
4. **`docs/search-profiles/README.md`:**
   - Add new section `## Recalibration of 2026-10-22 (after #121 and #161)`.
   - Document evidence basis per filter value (MEAS day 1/2 vs judgement).

### Task 3: Test Suites & Parity Verification
1. **Frontend Tests (`frontend/lib/__tests__/optionsSearchProfilesRecalibration.test.ts`):**
   - Validate `search-profiles-export.json` against `isValidSearchProfile` (18/18 valid).
   - Validate `import-search-profiles.js` embedded JSON matches `search-profiles-export.json` object-for-object.
   - Verify `buildOptionsScanRequestBody` converts each profile into a valid request without type errors or NaN.
   - Verify all 18 IDs are preserved and unique.
2. **Backend Tests (`backend/tests/test_search_profiles_recalibration.py`):**
   - Validate that `ScanRequest.model_validate()` succeeds for all 18 resolved profile request dictionaries.
   - Validate that `run_options_profiles_measurement.py` executes cleanly in `--dry-run` mode.

---

## 4. Verification & Gate Checklist

- [ ] All 18 profiles maintain identical IDs from previous releases.
- [ ] Export files match `version: 5` and pass strict `isValidSearchProfile` validation.
- [ ] `buildOptionsScanRequestBody` and backend `ScanRequest` parse all 18 profiles without errors.
- [ ] `Bamendjou_Options_Search_Profiles.xlsx` and `import-search-profiles.js` match `search-profiles-export.json`.
- [ ] Mini PC harness script runs cleanly in `--dry-run` mode under Python 3.11.
- [ ] `npm run typecheck` (`tsc --noEmit`) passes with 0 errors.
- [ ] Jest frontend test suite passes 100%.
- [ ] Pytest backend test suite passes 100% under Python 3.11.
- [ ] `python scripts/state.py` passes with 0 drift.
- [ ] Independent plan audit and code audit clean under `audit_rule`.
