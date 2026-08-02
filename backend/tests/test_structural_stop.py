import json
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.scoring.structural_stop import find_structural_stop

FIXTURES = Path(__file__).parent / "fixtures"


def _ob(direction: str, price_low: float, price_high: float, mitigated: bool = False, confidence: int = 75) -> dict:
    return {
        "kind": "OrderBlock", "direction": direction,
        "time_start": "2024-01-02", "time_end": None,
        "price_low": price_low, "price_high": price_high,
        "mitigated": mitigated, "confidence": confidence, "mtf_aligned": False,
    }


def _swing(price: float) -> dict:
    return {"index": 0, "time": "2024-01-01", "price": price}


_DUMMY_CANDLES = [{"time": str(i), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1} for i in range(20)]


class TestBullish:
    @patch("app.scoring.structural_stop.detect_bos_choch", return_value=[])
    @patch("app.scoring.structural_stop.detect_order_blocks")
    def test_picks_closest_order_block_below_reference(self, mock_obs, _mock_bos):
        mock_obs.return_value = [
            _ob("bullish", price_low=90, price_high=92),
            _ob("bullish", price_low=95, price_high=97),   # closest below 100
            _ob("bullish", price_low=105, price_high=107),  # above reference — ignored
        ]
        result = find_structural_stop(_DUMMY_CANDLES, "Bullish", reference_price=100)
        assert result is not None
        assert result.source == "order_block"
        assert result.price == 95

    @patch("app.scoring.structural_stop.detect_bos_choch", return_value=[])
    @patch("app.scoring.structural_stop.detect_order_blocks")
    def test_ignores_mitigated_order_blocks(self, mock_obs, _mock_bos):
        mock_obs.return_value = [
            _ob("bullish", price_low=98, price_high=99, mitigated=True),  # closest but mitigated
        ]
        with patch("app.scoring.structural_stop.find_swings", return_value=([], [_swing(90)])):
            result = find_structural_stop(_DUMMY_CANDLES, "Bullish", reference_price=100)
        assert result is not None
        assert result.source == "swing_low"
        assert result.price == 90

    @patch("app.scoring.structural_stop.detect_bos_choch", return_value=[])
    @patch("app.scoring.structural_stop.detect_order_blocks", return_value=[])
    def test_falls_back_to_nearest_swing_low(self, _mock_obs, _mock_bos):
        with patch(
            "app.scoring.structural_stop.find_swings",
            return_value=([], [_swing(80), _swing(90), _swing(60)]),
        ):
            result = find_structural_stop(_DUMMY_CANDLES, "Bullish", reference_price=100)
        assert result is not None
        assert result.source == "swing_low"
        assert result.confidence == 60
        assert result.price == 90  # nearest below reference

    @patch("app.scoring.structural_stop.detect_bos_choch", return_value=[])
    @patch("app.scoring.structural_stop.detect_order_blocks", return_value=[])
    def test_returns_none_when_nothing_qualifies(self, _mock_obs, _mock_bos):
        with patch("app.scoring.structural_stop.find_swings", return_value=([], [])):
            result = find_structural_stop(_DUMMY_CANDLES, "Bullish", reference_price=100)
        assert result is None

    @patch("app.scoring.structural_stop.detect_bos_choch", return_value=[])
    @patch("app.scoring.structural_stop.detect_order_blocks")
    def test_distance_pct_computed(self, mock_obs, _mock_bos):
        mock_obs.return_value = [_ob("bullish", price_low=90, price_high=92)]
        result = find_structural_stop(_DUMMY_CANDLES, "Bullish", reference_price=100)
        assert result.distance_pct == pytest.approx(10.0)


class TestBearish:
    @patch("app.scoring.structural_stop.detect_bos_choch", return_value=[])
    @patch("app.scoring.structural_stop.detect_order_blocks")
    def test_picks_closest_order_block_above_reference(self, mock_obs, _mock_bos):
        mock_obs.return_value = [
            _ob("bearish", price_low=108, price_high=110),
            _ob("bearish", price_low=103, price_high=105),  # closest above 100
            _ob("bearish", price_low=95, price_high=97),    # below reference — ignored
        ]
        result = find_structural_stop(_DUMMY_CANDLES, "Bearish", reference_price=100)
        assert result is not None
        assert result.source == "order_block"
        assert result.price == 105

    @patch("app.scoring.structural_stop.detect_bos_choch", return_value=[])
    @patch("app.scoring.structural_stop.detect_order_blocks", return_value=[])
    def test_falls_back_to_nearest_swing_high(self, _mock_obs, _mock_bos):
        with patch(
            "app.scoring.structural_stop.find_swings",
            return_value=([_swing(120), _swing(110), _swing(140)], []),
        ):
            result = find_structural_stop(_DUMMY_CANDLES, "Bearish", reference_price=100)
        assert result is not None
        assert result.source == "swing_high"
        assert result.price == 110  # nearest above reference


class TestGuards:
    def test_returns_none_for_short_history(self):
        result = find_structural_stop(_DUMMY_CANDLES[:5], "Bullish", reference_price=100)
        assert result is None


class TestRealCandles:
    """Smoke test against real historical candles — no mocking of the detectors."""

    def test_runs_end_to_end_without_error(self):
        candles = json.loads((FIXTURES / "AAPL_candles.json").read_text())
        reference_price = candles[-1]["close"]

        bull = find_structural_stop(candles, "Bullish", reference_price)
        bear = find_structural_stop(candles, "Bearish", reference_price)

        if bull is not None:
            assert bull.price < reference_price
            assert bull.source in ("order_block", "swing_low")
            assert bull.distance_pct == pytest.approx(
                abs(reference_price - bull.price) / reference_price * 100
            )
        if bear is not None:
            assert bear.price > reference_price
            assert bear.source in ("order_block", "swing_high")


class TestEndpoint:
    def _client(self) -> TestClient:
        from app.routers.contracts import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_returns_structural_level_when_found(self):
        candles = json.loads((FIXTURES / "AAPL_candles.json").read_text())
        with patch("app.routers.contracts.fetch_candles_async", AsyncMock(return_value=candles)):
            r = self._client().post("/api/contracts/structural-stop", json={
                "symbol": "AAPL", "direction": "Bullish", "stock_price": candles[-1]["close"],
            })
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body["available"], bool)
        if body["available"]:
            assert body["price"] < candles[-1]["close"]
            assert body["source"] in ("order_block", "swing_low")

    def test_returns_unavailable_for_short_history(self):
        with patch("app.routers.contracts.fetch_candles_async", AsyncMock(return_value=[{"time": "1", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}])):
            r = self._client().post("/api/contracts/structural-stop", json={
                "symbol": "AAPL", "direction": "Bullish", "stock_price": 100,
            })
        assert r.status_code == 200, r.text
        assert r.json() == {"available": False, "price": None, "source": None, "confidence": None, "distancePct": None}

    def test_rejects_nonpositive_stock_price(self):
        r = self._client().post("/api/contracts/structural-stop", json={
            "symbol": "AAPL", "direction": "Bullish", "stock_price": 0,
        })
        assert r.status_code == 422
