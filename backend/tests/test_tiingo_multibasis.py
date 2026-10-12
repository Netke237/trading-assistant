"""Verify tiingo.fetch_historical_candles returns multi-basis bars."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch
import pytest

import httpx

from app.data.tiingo import fetch_historical_candles


def _tiingo_resp(rows: list[dict]) -> httpx.Response:
    req = httpx.Request("GET", "https://api.tiingo.com/tiingo/daily/AAPL/prices")
    return httpx.Response(200, json=rows, request=req)


TIINGO_ROW = {
    "date":        "2024-01-02T00:00:00+00:00",
    "open":        183.0,
    "high":        187.0,
    "low":         182.0,
    "close":       185.0,
    "volume":      1_500_000,
    "adjOpen":     191.0,
    "adjHigh":     195.0,
    "adjLow":      190.0,
    "adjClose":    194.25,
    "adjVolume":   1_500_000,
    "splitFactor": 1.0,
    "divCash":     0.25,
}


@pytest.mark.asyncio
async def test_returns_raw_close():
    with patch("app.data.tiingo.httpx.get") as mock_get:
        mock_get.return_value = _tiingo_resp([TIINGO_ROW])
        bars = await fetch_historical_candles("AAPL", date(2024, 1, 1), date(2024, 1, 31))
    assert len(bars) == 1
    bar = bars[0]
    assert bar["close"] == 185.0          # raw close, NOT adjClose


@pytest.mark.asyncio
async def test_returns_adj_factor():
    with patch("app.data.tiingo.httpx.get") as mock_get:
        mock_get.return_value = _tiingo_resp([TIINGO_ROW])
        bars = await fetch_historical_candles("AAPL", date(2024, 1, 1), date(2024, 1, 31))
    bar = bars[0]
    expected_adj_factor = round(194.25 / 185.0, 8)
    assert abs(bar["adj_factor"] - expected_adj_factor) < 1e-6


@pytest.mark.asyncio
async def test_returns_split_factor_and_div_cash():
    with patch("app.data.tiingo.httpx.get") as mock_get:
        mock_get.return_value = _tiingo_resp([TIINGO_ROW])
        bars = await fetch_historical_candles("AAPL", date(2024, 1, 1), date(2024, 1, 31))
    bar = bars[0]
    assert bar["split_factor"] == 1.0
    assert bar["div_cash"] == 0.25


@pytest.mark.asyncio
async def test_returns_source_tiingo():
    with patch("app.data.tiingo.httpx.get") as mock_get:
        mock_get.return_value = _tiingo_resp([TIINGO_ROW])
        bars = await fetch_historical_candles("AAPL", date(2024, 1, 1), date(2024, 1, 31))
    assert bars[0]["source"] == "tiingo"


@pytest.mark.asyncio
async def test_adj_factor_defaults_to_1_when_raw_close_is_zero():
    zero_row = {**TIINGO_ROW, "close": 0, "adjClose": 194.25}
    with patch("app.data.tiingo.httpx.get") as mock_get:
        mock_get.return_value = _tiingo_resp([zero_row])
        bars = await fetch_historical_candles("AAPL", date(2024, 1, 1), date(2024, 1, 31))
    assert bars[0]["adj_factor"] == 1.0


@pytest.mark.asyncio
async def test_returns_empty_on_http_error():
    with patch("app.data.tiingo.httpx.get") as mock_get:
        mock_get.side_effect = Exception("network error")
        bars = await fetch_historical_candles("AAPL", date(2024, 1, 1), date(2024, 1, 31))
    assert bars == []


@pytest.fixture(autouse=True)
def fast_tiingo_governor(monkeypatch):
    from app.data.governor import Governor
    gov = Governor.for_testing("tiingo", rate=100000, capacity=100000)
    monkeypatch.setattr("app.data.tiingo.get_governor", lambda: gov)
