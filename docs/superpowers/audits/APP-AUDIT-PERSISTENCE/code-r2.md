# Adversarial Audit Review: Lane I (APP-AUDIT-PERSISTENCE, Issue #357) — Code Round 2

**Reviewed Diff:** `3582fc91..38da086c`  
**Scope:** Verification of Code Round 1 fixes (F-1 and F-2) and their interactions across `report.md`, `reconciliation.json`, `backend-durable-stores.md`, `PROJECT_STATE.json`, and the codebase.  
**Reviewer:** Subagent `97e5f667-a3e2-45d2-a8f7-8c3ce80dd624` (Independent Adversarial Auditor)  
**Date:** 2026-10-21  

---

### Audit Analysis & Verification of Round 1 Fixes

#### 1. Verification of Fix for F-1 (Schema Versions Alignment)
- **scanStore**: Schema version updated from 0 to 19 in `report.md:52` and `reconciliation.json:138`. Cross-checked against production code `frontend/lib/scanStore.ts:716` (`version: 19`). Verified that migrations v0..v18 -> v19 execute accumulated inline transformations (duration timestamps, pre-breakout, Fibonacci pullback, horizon preset migration).
- **searchProfilesStore**: Schema version updated from 0 to 5 in `report.md:50` and `reconciliation.json:163`. Cross-checked against production code `frontend/lib/searchProfilesStore.ts:86` (`version: 5`). Verified migration normalizes target profit percentages from legacy decimals.
- **autoTradeStore**: Schema version updated from 0 to 2 in `report.md:54` and `reconciliation.json:175`. Cross-checked against production code `frontend/lib/autoTradeStore.ts:85` (`version: 2`). Verified partialize filter demotes `armed` to `manual` on restart to prevent unintended broker order dispatch.
- **structureStore**: Schema version updated from 0 to 2 in `report.md:53` and `reconciliation.json:187`. Cross-checked against production code `frontend/lib/structureStore.ts:87` (`version: 2`). Verified migration backfills structure visibility flags.
- **themeStore**: Schema version updated from 0 to 1 in `report.md:55` and `reconciliation.json:199`. Cross-checked against production code `frontend/lib/theme.ts:44` (`version: 1`).
- **Comprehensive Cross-Store Matrix Verification**: Cross-checked all 15 Zustand persist stores across `frontend/lib/*.ts`, `storage-matrix.json`, `frontend-storage-catalog.md`, `reconciliation.json`, and `report.md`. All 15 schema versions match across all files:
  - `alertStore`: 3
  - `autoTradeStore`: 2
  - `chartAlertStore`: 2
  - `chartStore`: 2
  - `drawingStore`: 1
  - `portfolioStore`: 7
  - `riskStore`: 4
  - `scanParamsStore`: 12
  - `scanStore`: 19
  - `searchProfilesStore`: 5
  - `settingsStore`: 24
  - `structureStore`: 2
  - `theme`: 1
  - `watchedContractsStore`: 3
  - `watchlistStore`: 1

#### 2. Verification of Fix for F-2 (Relational Models & Database Base Attribution)
- **Phantom Table Removal**: Removed non-existent tables `fundamentals_cache` and `sp500_tickers` from `backend-durable-stores.md`, `report.md:77`, and `reconciliation.json:239`. Verified no orphaned references exist.
- **Main Application Database (`app.database.Base`)**: Updated table enumeration to exactly the 14 models declared in `backend/app/models/` and verified in SQLite runtime table creation (`backend/tests/test_audit_persistence_lane_i.py:133-151`):
  1. `portfolio_positions`
  2. `watchlist_symbols`
  3. `audit_events`
  4. `alert_rules`
  5. `alert_history`
  6. `broker_attempts`
  7. `closed_positions`
  8. `daily_risk_attempts`
  9. `daily_risk_budgets`
  10. `daily_risk_losses`
  11. `equity_snapshots`
  12. `exposure_guards`
  13. `exposure_holds`
  14. `fundamentals`
  Critical risk tables previously omitted (`broker_attempts`, `daily_risk_attempts`, `daily_risk_losses`) are now accurately cataloged.
- **Scheduled Scan Run Store (`ScheduledScanRunBase`)**: Relocated `scheduled_scan_runs` out of `app.database.Base` into its dedicated base `ScheduledScanRunBase` (`backend/app/models/scheduled_scan_run.py:7, 18`) in `backend-durable-stores.md:48-51`, `report.md:78`, and `reconciliation.json:241-250`.

#### 3. Automated Test Suite & State Checks
- `npm run test -- --testPathPattern=auditPersistence`: 19 passed, 0 failed.
- `npm run typecheck`: clean (0 errors).
- `python -m pytest backend/tests/test_audit_persistence_lane_i.py`: 7 passed, 0 failed.
- `python scripts/state.py`: clean (`No drift: every declared status matches the code`).

---

### Gate Evaluation

The gate rule strictly blocks findings that put a wrong number in front of a user or broker order, corrupt persisted data, or misstate mechanism such that a competent reader acting on it would write a wrong change.

Both Code Round 1 findings F-1 and F-2 have been thoroughly and accurately remediated across all relevant documents and JSON matrices without introducing regressions, broken cross-references, or mechanism drift.

GATE FINDINGS: 0
