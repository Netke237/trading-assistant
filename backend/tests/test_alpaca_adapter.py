"""Unit tests for the Alpaca daily bars adapter (no live network)."""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.data.alpaca import (
    AlpacaClient,
    fetch_daily_bars_batch,
    fetch_daily_bars_single,
    get_alpaca_client,
    _normalize_bars,
)


def _alpaca_resp(bars_by_symbol: dict, next_token: str | None = None) -> httpx.Response:
    request = httpx.Request("GET", "https://data.alpaca.markets/v2/stocks/bars")
    body = {"bars": bars_by_symbol, "next_page_token": next_token}
    return httpx.Response(200, json=body, request=request)


RAW_BAR = {
    "t": "2024-01-02T05:00:00Z",
    "o": 185.0, "h": 186.0, "l": 184.0, "c": 185.5, "v": 1_000_000,
}
ADJ_BAR = {
    "t": "2024-01-02T05:00:00Z",
    "o": 190.0, "h": 191.0, "l": 189.0, "c": 190.2, "v": 1_000_000,
}


def test_normalize_bars_computes_adj_factor():
    result = _normalize_bars({"AAPL": [RAW_BAR]}, {"AAPL": [ADJ_BAR]})
    assert len(result["AAPL"]) == 1
    bar = result["AAPL"][0]
    assert bar["time"] == "2024-01-02"
    assert bar["close"] == 185.5
    assert abs(bar["adj_factor"] - round(190.2 / 185.5, 8)) < 1e-6
    assert bar["source"] == "alpaca"


def test_normalize_bars_handles_missing_adj():
    result = _normalize_bars({"MSFT": [RAW_BAR]}, {})
    assert result["MSFT"][0]["adj_factor"] == 1.0


def test_normalize_bars_empty_raw():
    result = _normalize_bars({}, {"AAPL": [ADJ_BAR]})
    assert result == {}


@pytest.mark.asyncio
async def test_get_alpaca_client_returns_none_when_unconfigured():
    with patch("app.data.alpaca.credential_store") as cs:
        cs.get.return_value = {"key_id": "", "secret_key": "", "base_url": ""}
        client = await get_alpaca_client()
    assert client is None


@pytest.mark.asyncio
async def test_get_alpaca_client_uses_live_slot_when_configured():
    with patch("app.data.alpaca.credential_store") as cs:
        cs.get.side_effect = lambda slot: (
            {"key_id": "live_key", "secret_key": "live_secret", "base_url": "https://api.alpaca.markets"}
            if slot == "alpaca_live" else {"key_id": "", "secret_key": "", "base_url": ""}
        )
        client = await get_alpaca_client()
    assert client is not None
    assert isinstance(client, AlpacaClient)


@pytest.mark.asyncio
async def test_fetch_daily_bars_single_returns_bars():
    fake_client = MagicMock(spec=AlpacaClient)
    fake_client.fetch_raw = AsyncMock(return_value={"AAPL": [RAW_BAR]})
    fake_client.fetch_adj = AsyncMock(return_value={"AAPL": [ADJ_BAR]})

    bars = await fetch_daily_bars_single(
        "AAPL", date(2024, 1, 1), date(2024, 1, 31), client=fake_client
    )
    assert len(bars) == 1
    assert bars[0]["time"] == "2024-01-02"
    assert bars[0]["source"] == "alpaca"


@pytest.mark.asyncio
async def test_fetch_daily_bars_single_returns_empty_when_no_client():
    with patch("app.data.alpaca.get_alpaca_client", AsyncMock(return_value=None)):
        bars = await fetch_daily_bars_single("AAPL", date(2024, 1, 1), date(2024, 1, 31))
    assert bars == []


@pytest.mark.asyncio
async def test_fetch_daily_bars_batch_returns_empty_when_no_client():
    with patch("app.data.alpaca.get_alpaca_client", AsyncMock(return_value=None)):
        result = await fetch_daily_bars_batch(["AAPL", "MSFT"], date(2024, 1, 1), date(2024, 1, 31))
    assert result == {}
