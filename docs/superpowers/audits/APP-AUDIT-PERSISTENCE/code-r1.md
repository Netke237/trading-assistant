# Adversarial Audit Review: Lane I (APP-AUDIT-PERSISTENCE, Issue #357) — Code Round 1

**Reviewed Diff:** `origin/main..HEAD` (`3582fc91`)  
**Scope:** Browser storage, Zustand persist stores, direct call sites, backend YAML stores, database models and migrations, against `docs/superpowers/plans/2026-10-21-app-audit-persistence-plan.md` and the real codebase.  
**Reviewer:** Subagent `a2ff4c5e-1c01-4c32-ae59-dc7965708d45` (Independent Adversarial Auditor)  
**Date:** 2026-10-21  

---

### Gate Findings

#### Finding F-1
- **file:line**: `docs/superpowers/audits/app-audit/APP-AUDIT-PERSISTENCE/report.md:50,52-55` and `docs/superpowers/audits/app-audit/APP-AUDIT-PERSISTENCE/reconciliation.json:138`
- **concrete failing scenario (inputs -> wrong number / corrupted data)**:
  `report.md` Section 3.1 stated that `scanStore`, `searchProfilesStore`, `autoTradeStore`, `structureStore`, and `themeStore` had schema version 0 (and `reconciliation.json:138` asserted `scanStore` version 0).
  In reality: `scanStore` is version 19, `searchProfilesStore` is version 5, `autoTradeStore` is version 2, `structureStore` is version 2, and `themeStore` is version 1.
  A developer bumping version to 1 relying on the audit report would have migrations skipped on all existing persisted client data (`storedVersion >= configuredVersion`), defaulting parameters or failing rehydration.
- **disposition**: Valid gate finding (comment-truth exception). Fixed in `report.md` and `reconciliation.json` by updating schema versions to their exact production values: `scanStore` (19), `searchProfilesStore` (5), `autoTradeStore` (2), `structureStore` (2), and `themeStore` (1).

#### Finding F-2
- **file:line**: `docs/superpowers/audits/app-audit/APP-AUDIT-PERSISTENCE/backend-durable-stores.md:32-46` and `docs/superpowers/audits/app-audit/APP-AUDIT-PERSISTENCE/report.md:77`
- **concrete failing scenario (inputs -> wrong number / corrupted data)**:
  `backend-durable-stores.md` and `report.md` listed phantom tables (`fundamentals_cache`, `sp500_tickers`) and attributed `scheduled_scan_runs` to `app.database.Base` (it belongs to `ScheduledScanRunBase`), while omitting `broker_attempts`, `daily_risk_attempts`, and `daily_risk_losses`.
  An engineer performing database backup/restore or disaster recovery without these tables risks omitting idempotency tracking (`broker_attempts`, causing duplicate live broker orders) or daily loss limits (`daily_risk_attempts`, `daily_risk_losses`).
- **disposition**: Valid gate finding (comment-truth exception). Fixed in `backend-durable-stores.md`, `report.md`, and `reconciliation.json` by accurately listing the 14 tables on `app.database.Base` and documenting `ScheduledScanRunBase`.

---

GATE FINDINGS: 2 (both addressed)
