"""Tests: portfolio limits round-trip through GET/POST /settings/risk."""
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_risk_settings_accepts_portfolio_limits():
    payload = {
        "premiumStopPct": 0.60,
        "portfolioValue": 50000.0,
        "maxSinglePositionPct": 0.05,
        "maxTotalExposurePct": 0.20,
        "maxConcurrentPositions": 5,
        "maxDailyRecommendations": 10,
    }
    response = client.post("/settings/risk", json=payload)
    assert response.status_code == 200


def test_risk_settings_get_returns_portfolio_limits():
    response = client.get("/settings/risk")
    assert response.status_code == 200
    data = response.json()
    assert "portfolioValue" in data
    assert "maxConcurrentPositions" in data
