# APP-AUDIT-PERSISTENCE — Plan Audit Round 1

- **Date**: 2026-10-21
- **Reviewer**: Subagent `be471944-a249-43fb-ac2c-7ff3647b3cbd` (independent adversarial auditor)
- **Target**: `docs/superpowers/plans/2026-10-21-app-audit-persistence-plan.md`
- **Skill**: `bmad-review-adversarial-general`
- **Result**: 11 Gate Findings (NOT CLEAN)

---

### Findings Summary

1. **F-1 (credential_store.py mechanism)**: Line 103 asserted encryption keys and ciphertext recovery. In reality, `credential_store.py` deliberately uses plaintext YAML with filesystem permissions (`0600`) and in-memory masking (`_mask_dict`).
2. **F-2 (alertStore version)**: Line 39 listed `alertStore.ts` as version 2. Current version is explicitly `ALERT_STORE_VERSION = 3` (backfilling `STRUCTURAL_STOP_BREACHED`).
3. **F-3 (portfolioStore migration scope)**: Line 75 asserted `portfolioStore` v0..v6 -> v7 tests contract deduplication, added-fill booking, and cash adjustments. Deduplication is handled by `merge()` (`dedupePositions`), added-fill booking is backend logic in `broker_router.py`, and cash adjustments do not exist in `portfolioStore`. `migratePortfolioPersist` handles stop flooring, premium stop cleanup, IV basis stripping, and `holdMaxDays`.
4. **F-4 (scanParamsStore horizon presets)**: Line 80 asserted `scanParamsStore` v0..v11 -> v12 tests horizon presets. Horizon presets are owned exclusively by `scanStore.context.horizonPreset`.
5. **F-5 (Alembic on SQLite)**: Line 107 instructed running `alembic upgrade head` on SQLite. Alembic migrations in this repo contain PostgreSQL-specific constructs (`postgresql.UUID`, partial indexes in `bpr001`) and fail syntax on SQLite. SQLite tests bootstrap via `Base.metadata.create_all()`.
6. **F-6 (chartAlertStore tombstone key)**: Line 60 listed `bamendjou:alerts:tombstones`. Actual key is `bamendjou:alert-tombstones`.
7. **F-7 (WFO session keys and engine)**: Line 57 listed `bamendjou:tuning-job-id` and `bamendjou:adopted-tuning-horizons`. Actual keys are `sessionStorage` keys: `bamendjou:wfo:jobId` and `bamendjou:wfo:adopted` (adopted strategy names, not horizon names).
8. **F-8 (audit log buffer key)**: Line 59 listed `bamendjou-audit-v1`. Actual key is `bamendjou-audit-log`.
9. **F-9 (CollapsibleSection keys)**: Line 58 listed `bamendjou:section:*`. Actual production keys are caller-supplied: `bamendjou:tradecard-scores-collapsed`, `bamendjou:tradecard-ladder-collapsed`, and `bamendjou:tradecard:${qualification.kind}:scoring-evidence:collapsed`.
10. **F-10 (Backend model naming & coverage)**: Line 106 misnamed models and omitted critical risk models (`audit_events`, `fundamentals`, `ohlcv_daily`, `ohlcv_history_state`, `exposure_guards`, `exposure_holds`, `daily_risk_budgets`, `daily_risk_attempts`, `daily_risk_losses`).
11. **F-11 (Frontend rehydration orchestrator)**: Line 89 named `InitStores` as the primary rehydration orchestrator. `InitStores` only handles `portfolioStore` and `watchlistStore`. The comprehensive store rehydration and asynchronous scan-recovery component is `StoreHydration` in `frontend/components/StoreHydration/index.tsx`.

---

### Required Plan Fixes

Update `docs/superpowers/plans/2026-10-21-app-audit-persistence-plan.md` to:
1. Fix `credential_store.py` verification to test filesystem permissions (`0600`), plaintext YAML serialization, memory masking, and corrupt YAML recovery (no encryption keys).
2. Correct `alertStore.ts` version to 3, and add v2 -> v3 to the migration test list.
3. Align `portfolioStore` migration description with `migratePortfolioPersist` (flooring, stop cleanup, IV basis stripping, `holdMaxDays`), moving deduplication to `merge()` and removing added-fill booking / cash adjustments.
4. Remove horizon presets from `scanParamsStore` and document that horizon presets belong to `scanStore.context.horizonPreset`.
5. Clarify that Alembic migrations are PostgreSQL-only / statically verified via `test_alembic_heads.py`, while SQLite test databases bootstrap via `Base.metadata.create_all()`.
6. Fix tombstone key to `bamendjou:alert-tombstones`.
7. Fix WFO session keys to `sessionStorage` keys `bamendjou:wfo:jobId` and `bamendjou:wfo:adopted` (storing adopted strategy names).
8. Fix audit log key to `bamendjou-audit-log`.
9. Replace `bamendjou:section:*` with the concrete caller keys in `TradeCard` and `ScoreCardPanel`.
10. Update backend model list to include all 20 model files and explicitly name `portfolio_positions`, `watchlist_symbols`, `alert_rules`, `alert_history`, `position_alert_history`, `exposure_guards`, `exposure_holds`, `daily_risk_budgets`, `daily_risk_attempts`, `daily_risk_losses`, etc.
11. Name `StoreHydration` (`frontend/components/StoreHydration/index.tsx`) as the primary rehydration and scan-recovery orchestrator alongside `InitStores`.
