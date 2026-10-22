"""Tests atomic rollback and sidecar cleanup on failed schedule store writes (#374).

Covers:
- IngestionScheduleStore
- EdgarScheduleStore
- Sp500ScheduleStore
- TuningScheduleStore
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

from app.services.ingestion_schedule_store import IngestionScheduleStore
from app.services.edgar_schedule_store import EdgarScheduleStore
from app.services.sp500_schedule_store import Sp500ScheduleStore
from app.services.tuning_schedule_store import TuningScheduleStore


@pytest.fixture
def temp_config_dir(tmp_path: Path) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


class TestScheduleStoreRollback:
    """Verifies atomic persistence, in-memory rollback, and sidecar cleanup."""

    @pytest.mark.parametrize(
        "store_cls,default_time",
        [
            (IngestionScheduleStore, "02:00"),
            (EdgarScheduleStore, "03:00"),
            (Sp500ScheduleStore, "04:00"),
        ],
    )
    def test_standard_stores_normal_save_and_rollback(
        self, temp_config_dir: Path, store_cls: type, default_time: str
    ) -> None:
        file_path = temp_config_dir / f"{store_cls.__name__}.yaml"
        store = store_cls(path=file_path)

        # 1. Initial defaults
        assert store.get() == {"enabled": False, "time": default_time}

        # 2. Successful save
        store.set(enabled=True, time="01:17")
        assert store.get() == {"enabled": True, "time": "01:17"}
        disk_data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        assert disk_data == {"enabled": True, "time": "01:17"}

        # Fresh instance reads identical disk state
        fresh_store = store_cls(path=file_path)
        assert fresh_store.get() == {"enabled": True, "time": "01:17"}

        # 3. Injected os.replace failure during second save
        sidecar = file_path.with_suffix(".yaml.tmp")
        with patch("os.replace", side_effect=OSError("Injected replace error")):
            with pytest.raises(OSError, match="Injected replace error"):
                store.set(enabled=False, time="22:59")

        # Memory MUST NOT be updated to the failed draft
        assert store.get() == {"enabled": True, "time": "01:17"}

        # Disk MUST retain the prior committed values
        disk_data_after_fail = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        assert disk_data_after_fail == {"enabled": True, "time": "01:17"}

        # Sidecar temporary file MUST NOT be leaked
        assert not sidecar.exists()

        # Fresh store instance also sees prior committed state
        fresh_after_fail = store_cls(path=file_path)
        assert fresh_after_fail.get() == {"enabled": True, "time": "01:17"}

    def test_tuning_schedule_store_normal_save_and_rollback(
        self, temp_config_dir: Path
    ) -> None:
        file_path = temp_config_dir / "tuning_schedule.yaml"
        store = TuningScheduleStore(path=file_path)

        # 1. Initial defaults
        assert store.get() == {"enabled": False, "time": "05:00", "days_of_week": [5]}

        # 2. Successful save with custom days_of_week
        store.set(enabled=True, time="06:30", days_of_week=[0, 2, 4])
        expected = {"enabled": True, "time": "06:30", "days_of_week": [0, 2, 4]}
        assert store.get() == expected
        disk_data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        assert disk_data == expected

        # Fresh instance
        assert TuningScheduleStore(path=file_path).get() == expected

        # 3. Injected write failure
        sidecar = file_path.with_suffix(".yaml.tmp")
        with patch("os.replace", side_effect=OSError("Injected disk failure")):
            with pytest.raises(OSError, match="Injected disk failure"):
                store.set(enabled=False, time="23:15", days_of_week=[1, 3])

        # In-memory state remains untouched
        assert store.get() == expected
        # Disk remains untouched
        assert yaml.safe_load(file_path.read_text(encoding="utf-8")) == expected
        # No sidecar leaked
        assert not sidecar.exists()
        # Fresh instance consistent
        assert TuningScheduleStore(path=file_path).get() == expected

    def test_write_text_failure_cleans_up_sidecar(
        self, temp_config_dir: Path
    ) -> None:
        file_path = temp_config_dir / "ingestion_write_fail.yaml"
        store = IngestionScheduleStore(path=file_path)
        store.set(enabled=True, time="01:00")
        committed = {"enabled": True, "time": "01:00"}

        sidecar = file_path.with_suffix(".yaml.tmp")
        with patch.object(Path, "write_text", side_effect=OSError("Disk full")):
            with pytest.raises(OSError, match="Disk full"):
                store.set(enabled=False, time="09:00")

        assert store.get() == committed
        assert not sidecar.exists()


class TestRouterScheduleRollback:
    """Verifies that router failures return 500 without modifying in-memory state or schedulers."""

    def test_ingestion_router_rollback(self, temp_config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import app.routers.ingestion as ing_router

        file_path = temp_config_dir / "ingestion_router.yaml"
        test_store = IngestionScheduleStore(path=file_path)

        # Initial successful config
        test_store.set(enabled=True, time="02:30")
        mock_scheduler = MagicMock()
        mock_scheduler.next_run_time.return_value = None

        monkeypatch.setattr(ing_router, "ingestion_schedule_store", test_store)
        monkeypatch.setattr(ing_router, "ingestion_scheduler", mock_scheduler)

        app = FastAPI()
        app.include_router(ing_router.router)
        client = TestClient(app, raise_server_exceptions=False)

        # GET returns committed state
        resp = client.get("/api/data/ingest/schedule")
        assert resp.status_code == 200
        assert resp.json() == {"enabled": True, "time": "02:30", "next_run": None}

        # POST fails on replace
        with patch("os.replace", side_effect=OSError("Filesystem locked")):
            fail_resp = client.post("/api/data/ingest/schedule", json={"enabled": False, "time": "23:00"})
            assert fail_resp.status_code == 500

        # Scheduler configure was NOT called on failed save
        mock_scheduler.configure.assert_not_called()

        # Subsequent GET returns committed state, not the failed draft
        get_after = client.get("/api/data/ingest/schedule")
        assert get_after.status_code == 200
        assert get_after.json() == {"enabled": True, "time": "02:30", "next_run": None}
        assert test_store.get() == {"enabled": True, "time": "02:30"}

    def test_strategy_tuning_router_rollback(self, temp_config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import app.routers.strategy_tuning as tuning_router
        import app.services.tuning_schedule_store as tuning_store_mod
        import app.services.tuning_scheduler as tuning_sched_mod

        file_path = temp_config_dir / "tuning_router.yaml"
        test_store = TuningScheduleStore(path=file_path)
        test_store.set(enabled=True, time="05:30", days_of_week=[5])
        mock_scheduler = MagicMock()
        mock_scheduler.next_run_time.return_value = None

        monkeypatch.setattr(tuning_store_mod, "tuning_schedule_store", test_store)
        monkeypatch.setattr(tuning_sched_mod, "configure", mock_scheduler.configure)
        monkeypatch.setattr(tuning_sched_mod, "next_run_time", mock_scheduler.next_run_time)

        app = FastAPI()
        app.include_router(tuning_router.router)
        client = TestClient(app, raise_server_exceptions=False)

        # GET returns committed state
        resp = client.get("/api/strategy-tuning/schedule")
        assert resp.status_code == 200
        assert resp.json() == {
            "enabled": True,
            "time": "05:30",
            "days_of_week": [5],
            "next_run": None,
        }

        # POST fails on replace
        with patch("os.replace", side_effect=OSError("Disk failure")):
            fail_resp = client.post(
                "/api/strategy-tuning/schedule",
                json={"enabled": False, "time": "12:00", "days_of_week": [1, 2]},
            )
            assert fail_resp.status_code == 500

        mock_scheduler.configure.assert_not_called()

        # GET returns committed state
        get_after = client.get("/api/strategy-tuning/schedule")
        assert get_after.status_code == 200
        assert get_after.json() == {
            "enabled": True,
            "time": "05:30",
            "days_of_week": [5],
            "next_run": None,
        }
        assert test_store.get() == {
            "enabled": True,
            "time": "05:30",
            "days_of_week": [5],
        }
