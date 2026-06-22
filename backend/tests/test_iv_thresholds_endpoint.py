from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_iv_thresholds_endpoint_returns_all_horizons():
    response = client.get("/api/config/iv-thresholds")
    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) == {"Intraday", "Swing", "Position"}


def test_iv_thresholds_swing_matches_yaml():
    response = client.get("/api/config/iv-thresholds")
    assert response.status_code == 200
    swing = response.json()["Swing"]
    assert swing["pass_max"] == 34
    assert swing["caution_max"] == 55


def test_iv_thresholds_intraday_is_null():
    response = client.get("/api/config/iv-thresholds")
    intraday = response.json()["Intraday"]
    assert intraday["pass_max"] is None
    assert intraday["caution_max"] is None
