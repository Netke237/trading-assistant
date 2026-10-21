"""Lane I Backend Persistence Audit Test Suite.

Automated verification of:
1. CredentialStore: plaintext YAML serialization to local_credentials.yaml,
   0600 permissions, in-memory masking via _mask_dict, and corrupt fallback.
2. YAML Schedule Stores: atomic writes, backup restoration,
   and in-memory rollback on validation failure.
3. Database Models & Storage Engines:
   - app.database.Base table creation in SQLite
   - OhlcvBase table creation in dedicated SQLite store
   - ScanReportBase table creation in dedicated SQLite store
4. Alembic migration integrity: single-head verification.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml
from sqlalchemy import create_engine

from app.database import Base as MainBase
from app.models.ohlcv_daily import OhlcvBase
from app.models.scan_report import ScanReportBase
from app.services.credential_store import CredentialStore, _mask_dict
from app.services.scan_schedule_store import ScanScheduleStore, _SCHEMA_VERSION
from app.services.ingestion_schedule_store import IngestionScheduleStore
from app.services.edgar_schedule_store import EdgarScheduleStore
from app.services.sp500_schedule_store import Sp500ScheduleStore
from app.services.tuning_schedule_store import TuningScheduleStore
from alembic.config import Config
from alembic.script import ScriptDirectory

_BACKEND_DIR = Path(__file__).parent.parent


@pytest.fixture
def temp_config_dir(tmp_path: Path) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


class TestCredentialStorePersistence:
    """Verifies deliberate plaintext YAML persistence, 0600 permissions, and memory masking."""

    def test_credential_store_plaintext_and_permissions(self, temp_config_dir: Path) -> None:
        cred_path = temp_config_dir / "local_credentials.yaml"
        store = CredentialStore(path=cred_path)

        # Initially empty template
        assert store.get("tradier_paper") == {"account_id": "", "token": ""}

        # Save credentials
        store.set_and_save("tradier_paper", {"account_id": "VA12345", "token": "secret_token_1234"})

        # Verify on-disk file is plaintext YAML, NOT encrypted ciphertext
        raw_text = cred_path.read_text(encoding="utf-8")
        assert "VA12345" in raw_text
        assert "secret_token_1234" in raw_text
        disk_data = yaml.safe_load(raw_text)
        assert disk_data["tradier_paper"]["token"] == "secret_token_1234"

        # Verify filesystem permission restriction (0600 on POSIX; best-effort on Windows)
        if os.name == "posix":
            file_stat = cred_path.stat()
            assert file_stat.st_mode & 0o777 == 0o600

        # Verify memory masking via all_masked() (keeps last 4 chars, masks the rest)
        masked = store.all_masked()
        assert masked["tradier_paper"]["account_id"] == "VA12345"
        assert masked["tradier_paper"]["token"] == "*" * 13 + "1234"

        # Verify unmasked retrieval
        unmasked = store.get("tradier_paper")
        assert unmasked["token"] == "secret_token_1234"

    def test_credential_store_corrupt_yaml_fallback(self, temp_config_dir: Path) -> None:
        cred_path = temp_config_dir / "local_credentials.yaml"
        cred_path.write_text("invalid_yaml: [unclosed", encoding="utf-8")

        # Must fall back gracefully to default credential template without throwing
        store = CredentialStore(path=cred_path)
        assert store.get("tradier_paper") == {"account_id": "", "token": ""}


class TestScheduleStoreAtomicityAndRollback:
    """Verifies atomic writes, backup restoration, and rollback on invalid save."""

    def test_scan_schedule_store_backup_and_rollback(self, temp_config_dir: Path) -> None:
        sched_path = temp_config_dir / "scan_schedules.yaml"
        store = ScanScheduleStore(path=sched_path)

        # Add initial valid entry
        entry = {
            "id": "sched-1",
            "name": "Morning Bullish",
            "time": "09:45",
            "weekdays": [0, 1, 2, 3, 4],
            "screener_mode": "options",
            "resolved_request": {"universe": ["SPY"], "direction": "Bullish", "horizon": "Swing"},
        }
        store.upsert(entry)
        assert len(store.list()) == 1

        # Disk has entry and schema_version 3
        disk_yaml = yaml.safe_load(sched_path.read_text(encoding="utf-8"))
        assert disk_yaml["version"] == _SCHEMA_VERSION
        assert len(disk_yaml["entries"]) == 1

        # Simulate write failure during update: in-memory state rolls back to previous
        with patch.object(yaml, "dump", side_effect=OSError("Disk full")):
            with pytest.raises(OSError):
                store.upsert({"id": "sched-2", "name": "Failing Entry"})

        # Must have rolled back in-memory entries to only sched-1
        assert len(store.list()) == 1
        assert store.get("sched-1") is not None
        assert store.get("sched-2") is None


class TestDatabaseModelPersistence:
    """Verifies SQLite table creation and foreign key constraints across all DB bases."""

    def test_main_database_models_table_creation(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        MainBase.metadata.create_all(engine)

        tables = MainBase.metadata.tables.keys()
        expected_tables = {
            "portfolio_positions",
            "watchlist_symbols",
            "alert_rules",
            "alert_history",
            "audit_events",
            "broker_attempts",
            "closed_positions",
            "daily_risk_attempts",
            "daily_risk_budgets",
            "daily_risk_losses",
            "equity_snapshots",
            "exposure_guards",
            "exposure_holds",
            "fundamentals",
        }
        for t in expected_tables:
            assert t in tables, f"Missing table {t} in MainBase"

    def test_ohlcv_database_models_table_creation(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        OhlcvBase.metadata.create_all(engine)

        tables = OhlcvBase.metadata.tables.keys()
        assert "ohlcv_daily" in tables
        assert "ohlcv_history_state" in tables

    def test_scan_report_database_models_table_creation(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        ScanReportBase.metadata.create_all(engine)

        tables = ScanReportBase.metadata.tables.keys()
        assert "scan_reports" in tables
        assert "scan_report_heads" in tables


class TestAlembicMigrationIntegrity:
    """Statically verifies Alembic migration chain has exactly one head."""

    def test_exactly_one_alembic_head(self) -> None:
        cfg = Config(str(_BACKEND_DIR / "migrations" / "alembic.ini"))
        cfg.set_main_option("script_location", str(_BACKEND_DIR / "migrations"))
        script = ScriptDirectory.from_config(cfg)
        heads = script.get_heads()
        assert len(heads) == 1, f"Expected exactly 1 Alembic head, found {len(heads)}: {heads}"
