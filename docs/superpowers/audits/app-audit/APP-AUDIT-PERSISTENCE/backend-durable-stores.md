# Backend Durable Stores & Persistence Architecture

This document catalogs the durable persistence layers of the Bamendjou FastAPI backend, as verified under Lane I (APP-AUDIT-PERSISTENCE, #357, #468).

---

## 1. YAML Configuration & State Stores

The backend utilizes 9 YAML-backed configuration and state stores located under `backend/config/` (or runtime directory):

| Store Class | File Path | Schema Version | Atomic Write & Backup | Rollback on Error | Notes |
|---|---|---|---|---|---|
| `CredentialStore` | `local_credentials.yaml` | N/A | Yes (atomic rename, 0600) | Yes | Plaintext YAML storage with POSIX 0600 file permissions and in-memory masking via `all_masked()`. Corrupt files fall back safely to default empty templates. |
| `ScanScheduleStore` | `scan_schedules.yaml` | 3 | Yes (`.bak` backup file) | Yes | Auto-migrates v1/v2 percentage weight overrides and legacy presets upon load under re-entrant lock. |
| `IngestionScheduleStore`| `ingestion_schedule.yaml` | 1 | Yes (`.bak` backup file) | Yes | Atomic write with rollback to previous in-memory state on write/validation failure. |
| `EdgarScheduleStore` | `edgar_schedule.yaml` | 1 | Yes (`.bak` backup file) | Yes | Atomic write with rollback on error. |
| `Sp500ScheduleStore` | `sp500_schedule.yaml` | 1 | Yes (`.bak` backup file) | Yes | Atomic write with rollback on error. |
| `TuningScheduleStore` | `tuning_schedule.yaml` | 1 | Yes (`.bak` backup file) | Yes | Atomic write with rollback on error. |
| `ContractRulesStore` | `contract_rules.yaml` | N/A | Read-only runtime config | N/A | Option contract filter thresholds. |
| `RiskRulesStore` | `risk_rules.yaml` | N/A | Read-only runtime config | N/A | Risk limits and position sizing rules. |
| `ScoringRulesStore` | `scoring_rules.yaml` | N/A | Read-only runtime config | N/A | Multi-horizon technical scoring rules and event thresholds. |

---

## 2. Relational Database Models & Storage Engines

The backend separates database persistence across distinct storage engines depending on data durability and performance characteristics:

### A. Main Application Database (`app.database.Base`)
- **Default Engine**: SQLite (`sqlite+aiosqlite:///trading_assistant.db` in local/dev; PostgreSQL in production).
- **Schema Management**: Managed via Alembic migrations in PostgreSQL; bootstrapped via `Base.metadata.create_all()` in SQLite dev/testing.
- **Models (14 Tables)**:
  1. `portfolio_positions`: Open option and stock positions, cost basis, quantities, status.
  2. `watchlist_symbols`: Starred stock tickers and monitoring tags.
  3. `audit_events`: System audit events and user action trails.
  4. `alert_rules`: User-configured price, technical, and composite alert rules.
  5. `alert_history`: Historical alert trigger records and delivery confirmations.
  6. `broker_attempts`: Durable broker order dispatch records and idempotency locks.
  7. `closed_positions`: Historical closed trades, realized P&L, exit reasons.
  8. `daily_risk_attempts`: Intraday execution attempts tracked against daily risk limits.
  9. `daily_risk_budgets`: Daily risk allocation caps and cumulative draws.
  10. `daily_risk_losses`: Cumulative daily realized and unrealized loss tallies.
  11. `equity_snapshots`: Periodic portfolio equity curve tracking.
  12. `exposure_guards`: Dynamic risk exposure guardrails.
  13. `exposure_holds`: Active capital lock records per strategy/asset.
  14. `fundamentals`: SEC EDGAR parsed corporate financial ratios and scores.

### B. Dedicated Scheduled Scan Run Store (`ScheduledScanRunBase`)
- **Engine**: Dedicated SQLite store (`scan_schedules.db`).
- **Models**:
  1. `scheduled_scan_runs`: Execution logs, status, error payloads, and result JSON of automated scheduled scans.

### C. Dedicated Historical Price Store (`OhlcvBase`)
- **Engine**: Dedicated SQLite store (`ohlcv_cache.db`).
- **Models**:
  1. `ohlcv_daily`: Daily OHLCV price bars, volume, split adjustments, dividend cash, fetched timestamp.
  2. `ohlcv_history_state`: Per-symbol historical tracking floor date, seam date, provider provenance, basis verification signatures.

### D. Dedicated Scan Report Cache (`ScanReportBase`)
- **Engine**: Dedicated SQLite store (`scan_reports.db`).
- **Models**:
  1. `scan_reports`: Category, generation counter, execution status, and serialized envelope JSON payloads.
  2. `scan_report_heads`: Monotonic category head pointers (`latest_id`, `usable_id`, `generation`).
  3. `backtest_artifacts`: Strategy backtest cache payloads, schema version, creation time, expiration timestamp.

---

## 3. Database Migrations & Single Head Verification

- Alembic migrations reside in `backend/migrations/versions/`.
- Verified via `TestAlembicMigrationIntegrity.test_exactly_one_alembic_head`: exactly one head revision is active without branching or ambiguous merge heads.
- PostgreSQL migrations employ strict column typing, primary keys, and indices.
- SQLite dev/test environments bootstrap cleanly via declarative metadata creation without running dialect-incompatible Alembic DDL.
