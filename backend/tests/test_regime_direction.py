from types import SimpleNamespace

from fastapi.testclient import TestClient
from unittest.mock import patch
from app.routers.regime import _derive_regime_direction
from app.schemas import RegimeMetric
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
    """GET /regime must include regime_direction — always BULL, BEAR, or MIXED."""
    client = TestClient(app)
    with patch("app.routers.regime.fetch_price", return_value=15.0), \
         patch("app.routers.regime._spx_ndx_metric") as mock_metric, \
         patch("app.routers.regime.compute_omm", return_value=None), \
         patch("app.routers.regime.fetch_candles", return_value=[]), \
         patch("app.routers.regime.fetch_intraday_candles", return_value=[]), \
         patch("app.routers.regime.compute_intraday_hmm", return_value=None), \
         patch("app.routers.regime._compute_directional_hmm", return_value=None):
        mock_metric.return_value = RegimeMetric(label="SPX trend (200 EMA)", value="Above", status="PASS", trend="up")
        response = client.get("/api/regime")
    assert response.status_code == 200
    data = response.json()
    assert "regime_direction" in data
    assert data["regime_direction"] in ("BULL", "BEAR", "MIXED")


def test_regime_echoes_compute_omm_stride():
    """Daily and intraday OMM echo the lookback compute_omm was called with."""
    client = TestClient(app)
    lookbacks: list[int] = []
    stub_p_stay = 0.8

    def stub_compute_omm(closes, *, lookback=20, **_kwargs):
        lookbacks.append(lookback)
        return SimpleNamespace(
            state="Bull",
            p_stay=stub_p_stay,
            stability="Stable",
            regime_age_days=40,
            avg_regime_duration=5.0,
            transition_row=[0.8, 0.1, 0.1],
            state_order=["Bull", "Bear", "Choppy"],
            conviction_pct=12,
            conviction_label="Tailwind",
        )

    def fake_candles(symbol, bars=252):
        if symbol == "SPX":
            return [{"close": 100.0}]
        return []

    with patch("app.routers.regime.fetch_price", return_value=15.0), \
         patch("app.routers.regime._spx_ndx_metric") as mock_metric, \
         patch("app.routers.regime.compute_omm", side_effect=stub_compute_omm), \
         patch("app.routers.regime.fetch_candles", side_effect=fake_candles), \
         patch("app.routers.regime.fetch_intraday_candles", return_value=[]), \
         patch("app.routers.regime.completed_intraday_bars", return_value=[{"close": 100.0, "time": 1}]), \
         patch("app.routers.regime.compute_intraday_hmm", return_value=None), \
         patch("app.routers.regime._compute_directional_hmm", return_value=None):
        mock_metric.return_value = RegimeMetric(
            label="SPX trend (200 EMA)", value="Above", status="PASS", trend="up",
        )
        response = client.get("/api/regime?lookback=50")

    assert response.status_code == 200, response.text
    data = response.json()
    omm = data["omm"]
    assert omm["regime_age_days"] == 40
    assert omm["avg_regime_duration"] == 5.0
    assert omm["p_stay"] == stub_p_stay
    assert 50 in lookbacks
    assert 26 in lookbacks
    assert data["intraday_omm"]["regime_age_days"] == 40
    assert data["intraday_omm"]["p_stay"] == stub_p_stay
    assert omm.get("duration_stride_bars") == 50
    assert data["intraday_omm"].get("duration_stride_bars") == 26
