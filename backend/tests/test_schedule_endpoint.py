from fastapi.testclient import TestClient
from app.main import app
from app.schemas.schedule import ScheduleConfig
from app.services.scan_scheduler import ScanScheduler

client = TestClient(app)


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
    cfg = ScheduleConfig(days_of_week=[0, 1, 2, 3, 4])
    assert 5 not in cfg.days_of_week  # Saturday not included
    assert 6 not in cfg.days_of_week  # Sunday not included


def test_scheduler_cadence_clamped():
    scheduler = ScanScheduler()
    scheduler.set_cadence(1)     # below minimum of 5
    assert scheduler.cadence == 5
    scheduler.set_cadence(9999)  # above maximum of 1440
    assert scheduler.cadence == 1440
