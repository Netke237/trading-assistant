# APP-AUDIT-PERSISTENCE — Lane I execution plan

Tracking: #357, programme #348. Source baseline: `e5be63a1fa97b95c354f34075676281845bd6385`.
Phase: APP-AUDIT-PERSISTENCE. Audit/report scope only: no application fixes, calibration, shared fixtures, storage-key renames, live broker orders, or real notification sends. Each discovered defect will be recorded in `defects.json` with reproduction, expected/actual, affected SHA, owning lane, regression requirements, and separately linked issue.

## Goal and Deliverables

Verify cross-store migrations, reloads, restarts and data recovery across frontend browser storage and backend durable stores. Provide reproducible automated evidence, an authoritative storage matrix, and separately tracked defects.

Artifacts generated under `docs/superpowers/audits/app-audit/APP-AUDIT-PERSISTENCE/`:
1. `storage-matrix.json`: Authoritative ownership, key naming, engine, schema version, partialize/retention, and migration matrix.
2. `provenance.json`: Frozen environment, Node, Python 3.11, Chromium, commit SHAs, config hashes, and fixture provenance.
3. `reconciliation.json`: Explicit mapping between Lane A inventoried surfaces/states and Lane I persistence touchpoints.
4. `defects.json`: Separated numbers/persistence and presentation/usability defect ledger with full reproduction steps.
5. `README.md` & `report.md`: Complete audit findings, verified assertions, reproduction evidence, and open residuals.
6. Automated evidence harnesses and tests: deterministic scripts verifying migrations, corruptions, rollbacks, and recovery in isolated environments.

## Method and Independent Gates

1. **Independent Plan Review**:
   - Spawn a fresh independent subagent using `bmad-review-adversarial-general` against this plan and the real code it touches.
   - Enforce the numeric/persistence gate: 0 gate findings. Cap: 3 rounds per stage.
2. **Implementation Tickets**:
   - Break execution into scoped sub-issues of #357 linked via native GitHub `blocked_by` dependencies.
3. **Execution & Evidence Gathering**:
   - Use isolated temporary directories and mock storage; never mutate developer or production databases/configs.
   - Execute verification scripts and record exact outputs and hashes.
4. **Independent Code & Evidence Review**:
   - Merge `origin/main` before code audit to ensure clean divergence.
   - Spawn a fresh independent subagent using `bmad-review-adversarial-general` to audit the diff `origin/main..HEAD` against the plan and the gate.
   - Cap: 3 rounds; 0 gate findings required for `audit_clean: true`.

---

## Task 1 — Authoritative Frontend Storage Catalog & Ownership Matrix

Enumerate every persistent and session storage surface in the frontend:
1. **Zustand Persist Stores (`frontend/lib/`)**:
   - `alertStore.ts` (`bamendjou-alerts-v2`, version 3; version 3 backfills `STRUCTURAL_STOP_BREACHED`)
   - `autoTradeStore.ts` (`bamendjou-auto-trade`, version 2)
   - `chartAlertStore.ts` (`bamendjou:alerts`, version 2)
   - `chartStore.ts` (`bamendjou:chart`, version 2)
   - `drawingStore.ts` (`bamendjou:drawings`, version 1)
   - `portfolioStore.ts` (`bamendjou-portfolio-v1`, version 7)
   - `riskStore.ts` (`bamendjou-risk-v1`, version 4)
   - `scanParamsStore.ts` (`bamendjou:scan-params`, version 12)
   - `scanStore.ts` (`bamendjou-scan-store`, version 19)
   - `searchProfilesStore.ts` (`bamendjou:search-profiles`, version 5)
   - `settingsStore.ts` (`bamendjou-settings`, version 24)
   - `structureStore.ts` (`bamendjou:structure`, version 2)
   - `theme.ts` (`bamendjou:theme`, version 1)
   - `watchedContractsStore.ts` (`bamendjou-watched-contracts-v1`, version 3)
   - `watchlistStore.ts` (`bamendjou-watchlist-v1`, version 1)
2. **Direct Storage Call Sites**:
   - `frontend/app/layout.tsx`: inline no-flash theme script reading `localStorage.getItem('bamendjou:theme')`
   - `frontend/app/(frame)/dashboard/page.tsx`: earnings toggle reading/writing `localStorage.getItem('bamendjou:showEarnings')`
   - `frontend/app/(frame)/settings/page.tsx`: WFO tuning sessions in `sessionStorage`:
     - `const SESSION_JOB_KEY = 'bamendjou:wfo:jobId'` (tuning job ID string)
     - `const SESSION_ADOPTED_KEY = 'bamendjou:wfo:adopted'` (JSON array of adopted strategy names: `Set<string>`)
   - `frontend/components/molecules/CollapsibleSection/index.tsx`: section collapsed states using caller-supplied keys in `localStorage`:
     - `bamendjou:tradecard-scores-collapsed` (`TradeCard/index.tsx`)
     - `bamendjou:tradecard-ladder-collapsed` (`TradeCard/index.tsx`)
     - `bamendjou:tradecard:${qualification.kind}:scoring-evidence:collapsed` (`ScoreCardPanel/index.tsx`)
   - `frontend/lib/audit.ts`: audit log buffer writing to `localStorage` under `const AUDIT_STORAGE_KEY = 'bamendjou-audit-log'`
   - `frontend/lib/chartAlertStore.ts`: alert deletion tombstones reading/writing `localStorage` under `const TOMBSTONE_KEY = 'bamendjou:alert-tombstones'`
3. **In-Memory & API-Synchronized Stores**:
   - Document non-persisted stores (`universeStore`, `tradeCardUiStore`, `portfolioUiStore`, `watchlistUiStore`, `configHealthStore`, `directSendNotesStore`, `journalStore`, `notesStore`, `analysisStore`, `eventThresholdsStore`, `ivThresholdsStore`, `performanceStore`, `strategyProfilesStore`, `strategyWatchStore`).
4. **Matrix Dimensions**:
   - Key name, naming style (colon `'bamendjou:*'` vs legacy hyphen `'bamendjou-*'`), storage engine (`localStorage` / `sessionStorage` / memory), current version number, `partialize` filter (persisted keys vs volatile keys), `migrate` handler presence, default fallback, and cross-store data dependencies.
   - Output: `docs/superpowers/audits/app-audit/APP-AUDIT-PERSISTENCE/storage-matrix.json`.

---

## Task 2 — Frontend Migrations, Corruption, Quota & Concurrency Verification

Develop and execute automated test harnesses (`frontend/lib/__tests__/auditPersistence.test.ts` or standalone Node harness) verifying:
1. **Historical Version Migrations**:
   - Test each persisted store against fixtures representing older versions:
     - `scanStore` versions v0, v1, v8, v12, v13, v14, v15, v16, v17, v18 -> v19 (verifying stop migration, candidate normalization, card edits, strategy persistence, and horizon preset migration under `scanStore.context.horizonPreset` for version < 10).
     - `alertStore` versions v0..v2 -> v3 (verifying `STRUCTURAL_STOP_BREACHED` backfill into `config.enabledTypes`).
     - `portfolioStore` versions v0..v6 -> v7 (`migratePortfolioPersist`: stop flooring, `premiumStopPct` conversion, IV basis stripping, `holdMaxDays`, `premiumStopDollar` removal; verify that position deduplication is handled at hydration by `merge()` via `dedupePositions`).
     - `settingsStore` versions v0..v23 -> v24 (verifying broker fields, gate thresholds, markov configs, timezone persistence).
     - `searchProfilesStore` versions v0..v4 -> v5 (verifying target normalization, profile snapshots).
     - `watchedContractsStore` versions v0..v2 -> v3 (verifying contract parsing and metadata).
     - `riskStore` versions v0..v3 -> v4 (verifying max portfolio loss, position limits).
     - `scanParamsStore` versions v0..v11 -> v12 (verifying execution parameter overrides, `pullbackTolerancePct`, `btMinWinRate`; note horizon presets are in `scanStore`).
     - `chartStore` (v1 -> v2), `chartAlertStore` (v1 -> v2), `structureStore` (v1 -> v2), `autoTradeStore` (v1 -> v2), `drawingStore` (v0 -> v1), `themeStore` (v0 -> v1).
2. **Corrupted & Malformed Data Handling**:
   - Inject malformed JSON (`"{ invalid json"`), wrong types (array instead of object, string instead of number), missing required properties, `NaN` / `Infinity`, and invalid enums into each storage key.
   - Verify whether stores cleanly fall back to defaults, crash during hydration, or silently corrupt subsequent writes.
3. **Storage Quota & Boundary Failures**:
   - Simulate `QuotaExceededError` on `localStorage.setItem` for large stores (`scanStore` candidate trees, `portfolioStore`, `searchProfilesStore`, `audit.ts` FIFO eviction).
   - Check if errors are swallowed, logged, or surface unhandled exceptions in React components.
4. **Hydration, SSR Order & Scan Recovery**:
   - Verify the comprehensive store rehydration component `StoreHydration` (`frontend/components/StoreHydration/index.tsx`) mounted in `frontend/app/layout.tsx:82` which coordinates rehydration across stores and executes asynchronous scan result recovery (`api.getLastScan()`, `api.getLastStockScan()`).
   - Verify `InitStores` (`frontend/components/molecules/InitStores/index.tsx`) for `portfolioStore` and `watchlistStore` rehydration/sync.
   - Verify `skipHydration` behaviors, SSR hydration safety across `(frame)` pages, and the potential race condition where `StoreHydration` overlays restored scan results against `context` (`resultMatchesContext`).
5. **Multi-Tab Concurrency**:
   - Simulate simultaneous writes in two tabs (e.g. settings edits, portfolio position adds, watchlist toggles).
   - Document where storage events (`window.addEventListener('storage', ...)`) are used or omitted, and prove where lost updates occur.

---

## Task 3 — Backend Durable Stores, File Atomicity & Database Migrations

Develop and execute Python verification harnesses (`backend/tests/test_audit_persistence_lane_i.py` and standalone script) verifying:
1. **YAML File Durable Stores (`backend/app/services/`)**:
   - `scan_schedule_store.py`: schema versions v1 -> v2 -> v3, weight percentage migrations, atomic write with backup (`.bak`), rollback on validation failure.
   - `edgar_schedule_store.py`, `ingestion_schedule_store.py`, `sp500_schedule_store.py`, `tuning_schedule_store.py`: atomic rollback on write error, corrupt YAML handling, file permission failures.
   - `strategy_param_store.py`, `strategy_watch_store.py`: parameter persistence, corrupt file recovery.
   - `credential_store.py`: verify deliberate plaintext YAML serialization to `local_credentials.yaml`, filesystem permission restriction (`0600` / `stat.S_IRUSR | stat.S_IWUSR`), memory masking (`_mask_dict`), and corrupt YAML recovery (no encryption keys or ciphertext recovery).
   - `settings_migrations.py`: migration chain for `settings.yaml`.
2. **SQLAlchemy Models & Database Persistence**:
   - Inspect all SQLAlchemy database models across `backend/app/models/`:
     - `portfolio.py`: table `portfolio_positions`
     - `watchlist.py`: table `watchlist_symbols`
     - `watched_contracts.py`: table `watched_contracts`
     - `alert.py`: tables `alert_rules`, `alert_history`
     - `position_alert.py`: table `position_alert_history`
     - `broker_attempt.py`: tables `broker_attempts`, `exposure_guards`, `exposure_holds`
     - `daily_risk.py`: tables `daily_risk_budgets`, `daily_risk_attempts`, `daily_risk_losses`
     - `closed_position.py`: table `closed_positions`
     - `drawing.py`: table `drawings`
     - `symbol_note.py`: table `symbol_notes`
     - `journal.py`: table `journal_entries`
     - `scan_report.py`: table `scan_reports`
     - `scan_session.py`: table `scan_sessions`
     - `scheduled_scan_run.py`: table `scheduled_scan_runs`
     - `backtest_artifact.py`: table `backtest_artifacts`
     - `audit_event.py`: table `audit_events`
     - `fundamentals.py`: table `fundamentals`
     - `ohlcv_daily.py`: tables `ohlcv_daily`, `ohlcv_history_state`
     - `heston.py`, `heston_cache.py`, `black_scholes.py`
   - Test SQLite database creation and foreign key constraints bootstrapping via `Base.metadata.create_all()` (matching `test_alembic_heads.py:6-8` where SQLite never executes Alembic).
   - Statically verify Alembic migrations (`backend/migrations/versions/`) via `test_alembic_heads.py` for single head, and verify PostgreSQL-specific constructs (`postgresql.UUID`, partial indexes `postgresql_where`) against PostgreSQL schema specifications.
3. **Crash & Restart Recovery**:
   - Simulate process termination mid-write (unlinked temp files, truncated YAML, aborted transactions).
   - Test backend service startup when persistent files are missing, empty, or half-written.

---

## Task 4 — Cross-Store & Cross-Mode Journey Recovery Verification

Verify end-to-end data integrity across cross-mode user workflows:
1. **Cross-Mode Screener Navigation**:
   - Walk: Options mode -> Stocks mode -> Pre-Breakout mode -> Back to Options.
   - Verify whether `scanStore.context` (universe, direction, horizon) or `universeStore` leak stale selections or corrupt active scan results.
2. **Entity Identity Preservation Across Stores**:
   - Trace candidate entities across stores:
     - Contract ID format: `contractId(symbol, strike, expiry, right)` consistency between `scanStore`, `watchedContractsStore`, `portfolioStore`, `alertStore`.
     - Symbol normalization: uppercase vs mixed case, special tickers (e.g. `BRK.B` vs `BRK/B`), custom universe entries in `universeStore` vs `watchlistStore` vs `notesStore`.
3. **Cold Start & Browser Reload Restoration**:
   - Snapshot browser storage before reload -> execute complete reload -> snapshot after reload.
   - Verify exact equality of starred watchlist items, open portfolio positions, custom search profiles, drawn chart levels, and active alert rules. Prove no silent data loss.

---

## Task 5 — Lane A Reconciliation, Defect Logging & Comprehensive Publication

1. **Reconciliation with Lane A**:
   - Map all persistence-related surfaces and states from `docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/inventory.json` into `reconciliation.json`.
   - Record coverage for every applicable state: normal, empty, loading, corrupt/error, legacy/migrated, post-reload, multi-tab.
2. **Defect Cataloging**:
   - Document all discovered defects in `docs/superpowers/audits/app-audit/APP-AUDIT-PERSISTENCE/defects.json`.
   - Classify into:
     - Gate-blocking numbers/persistence defects (wrong number to user/broker or corrupted persistent data).
     - Non-blocking usability / presentation defects.
3. **Publication**:
   - Compile `README.md` and `report.md` in `docs/superpowers/audits/app-audit/APP-AUDIT-PERSISTENCE/`.
   - Include exact environment provenance, reproduction scripts, before/after snapshots, and residual gaps.
   - Verify `state.py`, run typechecks and tests, and open PR linking #357.

---

## Acceptance Checklist

- [ ] `storage-matrix.json` published documenting all frontend and backend persistent keys, versions, partialize filters, and migrations.
- [ ] Automated verification harnesses executed for frontend version migrations, malformed payloads, quota exhaustion, and multi-tab concurrency.
- [ ] Automated verification harnesses executed for backend YAML store atomicity, rollbacks, corruptions, and database models.
- [ ] Cold-start and cross-mode entity identity restoration proven without silent data loss.
- [ ] Reconciliation with Lane A inventory completed and documented in `reconciliation.json`.
- [ ] Discovered defects logged in `defects.json` with reproduction steps and classification.
- [ ] Independent plan review and code review completed clean (0 gate findings) under required subagent protocol.
