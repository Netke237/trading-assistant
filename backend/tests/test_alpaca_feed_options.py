"""Tests for Alpaca client feed parameter and SIP default behavior (#558)."""
from __future__ import annotations

import logging
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.data.alpaca import (
    AlpacaClient,
    fetch_daily_bars_batch,
    fetch_daily_bars_single,
)


def _make_bars_resp(
    bars: dict, status_code: int = 200, next_token: str | None = None
) -> httpx.Response:
    request = httpx.Request("GET", "https://data.alpaca.markets/v2/stocks/bars")
    body = {"bars": bars, "next_page_token": next_token}
    return httpx.Response(status_code, json=body, request=request)


def test_alpaca_client_default_feed_is_sip():
    client = AlpacaClient("test_key", "test_secret")
    assert client.feed == "sip"


@pytest.mark.asyncio
async def test_get_bars_page_sends_sip_by_default():
    client = AlpacaClient("test_key", "test_secret")
    captured_params = {}

    async def mock_get(url, headers=None, params=None):
        captured_params.update(params or {})
        return _make_bars_resp({"AAPL": []})

    with patch("httpx.AsyncClient.get", side_effect=mock_get):
        await client._get_bars_page(
            symbols=["AAPL"],
            adjustment="raw",
            start=date(2022, 3, 7),
            end=date(2022, 3, 8),
            page_token=None,
        )

    assert captured_params.get("feed") == "sip"


@pytest.mark.asyncio
async def test_get_bars_page_sends_explicit_iex():
    client = AlpacaClient("test_key", "test_secret", feed="iex")
    assert client.feed == "iex"
    captured_params = {}

    async def mock_get(url, headers=None, params=None):
        captured_params.update(params or {})
        return _make_bars_resp({"AAPL": []})

    with patch("httpx.AsyncClient.get", side_effect=mock_get):
        await client._get_bars_page(
            symbols=["AAPL"],
            adjustment="raw",
            start=date(2022, 3, 7),
            end=date(2022, 3, 8),
            page_token=None,
        )

    assert captured_params.get("feed") == "iex"


@pytest.mark.asyncio
async def test_get_bars_page_override_feed_parameter():
    client = AlpacaClient("test_key", "test_secret", feed="sip")
    captured_params = {}

    async def mock_get(url, headers=None, params=None):
        captured_params.update(params or {})
        return _make_bars_resp({"AAPL": []})

    with patch("httpx.AsyncClient.get", side_effect=mock_get):
        await client._get_bars_page(
            symbols=["AAPL"],
            adjustment="raw",
            start=date(2022, 3, 7),
            end=date(2022, 3, 8),
            page_token=None,
            feed="iex",
        )

    assert captured_params.get("feed") == "iex"


@pytest.mark.asyncio
async def test_sip_403_forbidden_logs_warning_and_falls_back_to_iex(caplog):
    client = AlpacaClient("test_key", "test_secret", feed="sip")
    requests_made = []

    async def mock_get(url, headers=None, params=None):
        requests_made.append(dict(params or {}))
        if len(requests_made) == 1:
            req = httpx.Request("GET", url)
            return httpx.Response(
                403,
                json={"message": "subscription does not permit querying SIP data"},
                request=req,
            )
        return _make_bars_resp({"AAPL": [{"t": "2022-03-08T05:00:00Z", "c": 150.0}]})

    with caplog.at_level(logging.WARNING):
        with patch("httpx.AsyncClient.get", side_effect=mock_get):
            data = await client._get_bars_page(
                symbols=["AAPL"],
                adjustment="raw",
                start=date(2022, 3, 7),
                end=date(2022, 3, 8),
                page_token=None,
            )

    assert len(requests_made) == 2
    assert requests_made[0]["feed"] == "sip"
    assert requests_made[1]["feed"] == "iex"
    assert "AAPL" in (data.get("bars") or {})
    # Warning should be logged about 403 / falling back to IEX
    assert any("403" in record.message and "falling back" in record.message.lower() for record in caplog.records)


@pytest.mark.asyncio
async def test_date_only_end_formatting_preserved():
    client = AlpacaClient("test_key", "test_secret")
    captured_params = {}

    async def mock_get(url, headers=None, params=None):
        captured_params.update(params or {})
        return _make_bars_resp({"AAPL": []})

    with patch("httpx.AsyncClient.get", side_effect=mock_get):
        await client._get_bars_page(
            symbols=["AAPL"],
            adjustment="raw",
            start=date(2022, 3, 7),
            end=date(2022, 3, 8),
            page_token=None,
        )

    # Must be date-only strings (YYYY-MM-DD), not ISO datetime with T00:00:00Z
    assert captured_params["start"] == "2022-03-07"
    assert captured_params["end"] == "2022-03-08"
    assert "T" not in captured_params["start"]
    assert "T" not in captured_params["end"]


@pytest.mark.asyncio
async def test_fetch_daily_bars_batch_accepts_feed():
    fake_client = MagicMock(spec=AlpacaClient)
    fake_client.fetch_raw = AsyncMock(return_value={"AAPL": []})
    fake_client.fetch_adj = AsyncMock(return_value={"AAPL": []})

    await fetch_daily_bars_batch(
        ["AAPL"],
        date(2022, 3, 7),
        date(2022, 3, 8),
        client=fake_client,
        feed="iex",
    )

    fake_client.fetch_raw.assert_awaited_once_with(
        ["AAPL"], date(2022, 3, 7), date(2022, 3, 8), feed="iex"
    )
    fake_client.fetch_adj.assert_awaited_once_with(
        ["AAPL"], date(2022, 3, 7), date(2022, 3, 8), feed="iex"
    )


@pytest.mark.asyncio
async def test_fetch_daily_bars_single_accepts_feed():
    fake_client = MagicMock(spec=AlpacaClient)
    fake_client.fetch_raw = AsyncMock(return_value={"AAPL": []})
    fake_client.fetch_adj = AsyncMock(return_value={"AAPL": []})

    await fetch_daily_bars_single(
        "AAPL",
        date(2022, 3, 7),
        date(2022, 3, 8),
        client=fake_client,
        feed="iex",
    )

    fake_client.fetch_raw.assert_awaited_once_with(
        ["AAPL"], date(2022, 3, 7), date(2022, 3, 8), feed="iex"
    )
    fake_client.fetch_adj.assert_awaited_once_with(
        ["AAPL"], date(2022, 3, 7), date(2022, 3, 8), feed="iex"
    )


@pytest.mark.asyncio
async def test_fetch_daily_bars_batch_defaults_to_sip():
    fake_client = MagicMock(spec=AlpacaClient)
    fake_client.fetch_raw = AsyncMock(return_value={"AAPL": []})
    fake_client.fetch_adj = AsyncMock(return_value={"AAPL": []})

    await fetch_daily_bars_batch(
        ["AAPL"],
        date(2022, 3, 7),
        date(2022, 3, 8),
        client=fake_client,
    )

    fake_client.fetch_raw.assert_awaited_once_with(
        ["AAPL"], date(2022, 3, 7), date(2022, 3, 8)
    )
    fake_client.fetch_adj.assert_awaited_once_with(
        ["AAPL"], date(2022, 3, 7), date(2022, 3, 8)
    )
