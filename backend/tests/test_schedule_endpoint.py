import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app
from app.schemas.schedule import ScheduleConfig
from app.services.scan_scheduler import ScanScheduler

client = TestClient(app)

SETTINGS_YAML = Path(__file__).parent.parent / "config" / "settings.yaml"


@pytest.fixture(autouse=True)
def restore_settings_yaml():
    """Restore settings.yaml to its original content after each test."""
    original = SETTINGS_YAML.read_text() if SETTINGS_YAML.exists() else None
    yield
    if original is not None:
        SETTINGS_YAML.write_text(original)


def test_get_schedule_returns_defaults():
    response = client.get("/settings/schedule")
    assert response.status_code == 200
    data = response.json()
    assert "cadence_minutes" in data
    assert "days_of_week" in data
    assert "enabled_options" in data
    assert "enabled_stocks" in data


def test_put_schedule_persists():
    payload = {
        "enabled_options": True, "enabled_stocks": False,
        "cadence_minutes": 60, "days_of_week": [0, 1, 2, 3, 4],
        "window_start_hour": 9, "window_end_hour": 17,
        "timezone_name": "America/New_York",
    }
    r = client.put("/settings/schedule", json=payload)
    assert r.status_code == 200
    r2 = client.get("/settings/schedule")
    assert r2.json()["cadence_minutes"] == 60
    assert r2.json()["enabled_options"] is True


def test_scheduler_skips_weekend():
    """_should_run_now() must return False when current day is not in days_of_week."""
    from unittest.mock import patch
    from datetime import datetime
    from zoneinfo import ZoneInfo

    cfg = ScheduleConfig(
        days_of_week=[0, 1, 2, 3, 4],  # Mon-Fri only
        window_start_hour=9,
        window_end_hour=17,
        timezone_name="America/New_York",
    )
    scheduler = ScanScheduler()
    scheduler.configure(cfg)

    # Mock datetime.now() to return a Saturday (weekday 5) at 10 AM ET
    saturday_10am = datetime(2026, 6, 21, 10, 0, tzinfo=ZoneInfo("America/New_York"))
    with patch("app.services.scan_scheduler.datetime") as mock_dt:
        mock_dt.now.return_value = saturday_10am
        assert scheduler._should_run_now() is False, "Should skip Saturday"


def test_scheduler_cadence_clamped():
    scheduler = ScanScheduler()
    scheduler.set_cadence(1)     # below minimum of 5
    assert scheduler.cadence == 5
    scheduler.set_cadence(9999)  # above maximum of 1440
    assert scheduler.cadence == 1440
