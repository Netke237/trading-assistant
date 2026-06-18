import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from app.routers.regime import _derive_regime_direction
from app.main import app


# ── Unit tests: pure derivation logic ────────────────────────────────────────

def test_bull_omm_state():
    assert _derive_regime_direction("Bull", None, None) == "BULL"


def test_bear_omm_state():
    assert _derive_regime_direction("Bear", None, None) == "BEAR"


def test_choppy_omm_is_mixed():
    # OMM 'Choppy' → MIXED regardless of EMA statuses
    assert _derive_regime_direction("Choppy", "PASS", "PASS") == "MIXED"


def test_no_omm_both_pass_is_bull():
    assert _derive_regime_direction(None, "PASS", "PASS") == "BULL"


def test_no_omm_both_reject_is_bear():
    assert _derive_regime_direction(None, "REJECT", "REJECT") == "BEAR"


def test_no_omm_mixed_ema():
    assert _derive_regime_direction(None, "PASS", "REJECT") == "MIXED"


def test_no_omm_no_ema():
    assert _derive_regime_direction(None, None, None) == "MIXED"


def test_no_omm_one_caution_is_mixed():
    assert _derive_regime_direction(None, "PASS", "CAUTION") == "MIXED"


# ── Endpoint smoke test: regime_direction is present in HTTP response ─────────

def test_regime_endpoint_includes_regime_direction():
    """GET /regime must include regime_direction — BULL, BEAR, or MIXED (never absent)."""
    client = TestClient(app)
    with patch("app.routers.regime.fetch_price", return_value=15.0), \
         patch("app.routers.regime._spx_ndx_metric") as mock_metric, \
         patch("app.routers.regime.compute_omm", return_value=None), \
         patch("app.routers.regime.fetch_candles", return_value=[]), \
         patch("app.routers.regime.fetch_intraday_candles", return_value=[]), \
         patch("app.routers.regime.compute_intraday_hmm", return_value=None), \
         patch("app.routers.regime._compute_directional_hmm", return_value=None):
        from app.schemas import RegimeMetric
        mock_metric.return_value = RegimeMetric(label="SPX trend (200 EMA)", value="Above", status="PASS", trend="up")
        response = client.get("/api/regime")
    assert response.status_code == 200
    data = response.json()
    assert "regime_direction" in data
    assert data["regime_direction"] in ("BULL", "BEAR", "MIXED", None)
