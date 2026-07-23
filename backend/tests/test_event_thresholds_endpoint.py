from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_event_thresholds_endpoint_returns_all_horizons():
    response = client.get("/api/config/event-thresholds")
    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) == {"Intraday", "Swing", "Position"}


def test_event_thresholds_swing_matches_yaml():
    response = client.get("/api/config/event-thresholds")
    assert response.status_code == 200
    swing = response.json()["Swing"]
    assert swing["reject_days"] == 21
    assert swing["caution_days"] == 45


def test_event_thresholds_intraday_matches_yaml():
    response = client.get("/api/config/event-thresholds")
    assert response.status_code == 200
    intraday = response.json()["Intraday"]
    assert intraday["reject_days"] == 1
    assert intraday["caution_days"] == 3


def test_event_thresholds_position_matches_yaml():
    response = client.get("/api/config/event-thresholds")
    assert response.status_code == 200
    position = response.json()["Position"]
    assert position["reject_days"] == 30
    assert position["caution_days"] == 60
