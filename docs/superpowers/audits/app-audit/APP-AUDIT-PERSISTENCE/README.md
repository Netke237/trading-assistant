# Lane I Audit: Browser & Backend Persistence Verification (`APP-AUDIT-PERSISTENCE`)

This directory houses the comprehensive audit artifacts, inventory matrices, defect tracking, and verification evidence for Lane I of the Application Audit Programme (#357).

---

## Artifact Index

| File | Description |
|---|---|
| [`report.md`](./report.md) | **Authoritative Final Audit Report** — Executive summary, gate-level findings (0 blocking), verification evidence, and sign-off. Serves as the verify probe for `PROJECT_STATE.json`. |
| [`storage-matrix.json`](./storage-matrix.json) | Complete, structured inventory of all 15 Zustand persist stores, 13 ephemeral stores, 6 direct browser storage call sites, 9 backend YAML stores, and 20 database model definitions. |
| [`frontend-storage-catalog.md`](./frontend-storage-catalog.md) | Detailed technical catalog of all browser storage stores, migration functions, storage keys, version histories, and rehydration lifecycles. |
| [`backend-durable-stores.md`](./backend-durable-stores.md) | Detailed technical catalog of backend durable stores, file atomicity, `.bak` backup mechanisms, SQLAlchemy models, and Alembic migrations. |
| [`reconciliation.json`](./reconciliation.json) | Cross-audit reconciliation linking Lane I verified surfaces with the Lane A inventory and test evidence. |
| [`defects.json`](./defects.json) | Catalog of non-blocking architectural observations and documentation-only findings. |
| [`provenance.json`](./provenance.json) | Audit provenance, environment runtime specifications, git revisions, and test execution results. |

---

## Summary of Verified Surfaces

1. **Frontend Browser Storage**:
   - **15 Zustand `persist` Stores**: Verified across version migrations, schema defaults, and bounds checks (`alertStore`, `portfolioStore`, `watchedContractsStore`, `watchlistStore`, `chartStore`, `chartAlertStore`, `riskStore`, `settingsStore`, `drawingStore`, `searchProfilesStore`, `scanParamsStore`, `scanStore`, `structureStore`, `autoTradeStore`, `themeStore`).
   - **Direct Browser Storage Call Sites**: Verified QuotaExceededError boundary handling (`bamendjou-audit-log`), tombstone sanitization (`bamendjou:alert-tombstones`), session state (`bamendjou:wfo:jobId`, `bamendjou:wfo:adopted`), and UI collapsed states (`bamendjou:trade-card:collapsed`, `bamendjou:score-card:collapsed`).
   - **Store Rehydration & Scan Recovery**: Verified `StoreHydration` and `resultMatchesContext` logic across mode transitions (Options, Stocks, Pre-Breakout).
2. **Backend Durable Storage**:
   - **YAML Stores**: Verified `CredentialStore` plaintext YAML with 0600 permissions, memory masking (`all_masked()`), and corrupt fallback. Verified `ScanScheduleStore` atomic backup/rollback and schema migration. Verified atomic backup and rollback across ingestion, edgar, sp500, and tuning schedule stores.
   - **Relational Databases & Migrations**: Verified 14 core tables in `app.database.Base`, 2 tables in `OhlcvBase`, 3 tables in `ScanReportBase`. Verified single Alembic migration head integrity.

---

## Reproduction & Verification Commands

```bash
# Frontend test suite (19/19 passing)
cd frontend
npm run test -- --testPathPattern=auditPersistence
npm run typecheck

# Backend test suite (7/7 passing)
cd backend
.venv\Scripts\python.exe -m pytest tests/test_audit_persistence_lane_i.py
```
