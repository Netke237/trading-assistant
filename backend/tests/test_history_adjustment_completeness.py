"""HISTORY must reject whole provider replies with invented adjustment factors."""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.data.alpaca import (
    AlpacaClient,
    _normalize_bars,
    fetch_daily_bars_batch,
    fetch_daily_bars_single,
)
from app.data.tiingo import fetch_historical_candles


START = date(2016, 1, 4)
END = date(2016, 1, 12)
DATES = ["2016-01-04", "2016-01-05", "2016-01-06", "2016-01-07",
         "2016-01-08", "2016-01-11", "2016-01-12"]
MISSING = object()
INVALID_CLOSES = [MISSING, None, 0, -1, float("nan"), float("inf"), float("-inf"), "invalid"]
INVALID_IDS = ["missing", "null", "zero", "negative", "nan", "inf", "negative-inf", "invalid"]


def _alpaca_rows(close=100.0):
    return [
        {"t": f"{day}T05:00:00Z", "o": 99.0, "h": 101.0,
         "l": 98.0, "c": close, "v": 1000}
        for day in DATES
    ]


def _tiingo_rows():
    return [
        {"date": f"{day}T00:00:00+00:00", "open": 99.0, "high": 101.0,
         "low": 98.0, "close": 100.0, "adjClose": 50.0, "volume": 1000,
         "splitFactor": 1.0, "divCash": 0.0}
        for day in DATES
    ]


def _set_close(row, key, value):
    if value is MISSING:
        row.pop(key)
    else:
        row[key] = value


def _client(raw, adj):
    client = MagicMock(spec=AlpacaClient)
    client.fetch_raw = AsyncMock(return_value=raw)
    client.fetch_adj = AsyncMock(return_value=adj)
    return client


def _mock_tiingo(monkeypatch, rows):
    response = MagicMock()
    response.json.return_value = rows
    get = MagicMock(return_value=response)
    monkeypatch.setattr("app.data.tiingo.httpx.get", get)
    return get


@pytest.mark.parametrize("bad_index", [0, 6], ids=["before-overlap", "after-overlap"])
@pytest.mark.parametrize("bad_close", INVALID_CLOSES, ids=INVALID_IDS)
@pytest.mark.asyncio
async def test_alpaca_strict_rejects_whole_symbol_beyond_five_valid_overlap_dates(
    bad_index, bad_close,
):
    raw = _alpaca_rows()
    adj = _alpaca_rows(50.0)
    if bad_close is MISSING:
        adj.pop(bad_index)
    else:
        adj[bad_index]["c"] = bad_close
    client = _client({"BAD": raw, "GOOD": raw}, {"BAD": adj, "GOOD": _alpaca_rows(50.0)})

    result = await fetch_daily_bars_batch(
        ["BAD", "GOOD"], START, END, client=client, strict_adjustments=True
    )

    assert set(result) == {"GOOD"}
    assert len(result["GOOD"]) == len(DATES)
    assert [row["adj_factor"] for row in result["GOOD"]] == [0.5] * len(DATES)
    client.fetch_raw.assert_awaited_once_with(["BAD", "GOOD"], START, END)
    client.fetch_adj.assert_awaited_once_with(["BAD", "GOOD"], START, END)


@pytest.mark.parametrize("bad_close", INVALID_CLOSES, ids=INVALID_IDS)
def test_alpaca_strict_rejects_invalid_raw_close_without_inventing_factor_one(bad_close):
    raw = _alpaca_rows()
    _set_close(raw[6], "c", bad_close)
    assert _normalize_bars(
        {"BAD": raw}, {"BAD": _alpaca_rows(50.0)}, strict_adjustments=True
    ) == {}


@pytest.mark.asyncio
async def test_alpaca_single_forwards_strict_mode_and_returns_empty_for_incomplete_symbol():
    client = _client({"BAD": _alpaca_rows()}, {"BAD": _alpaca_rows(50.0)[1:]})
    assert await fetch_daily_bars_single(
        "BAD", START, END, client=client, strict_adjustments=True
    ) == []


def test_alpaca_strict_requires_matching_timestamp_even_when_calendar_date_matches():
    adj = _alpaca_rows(50.0)
    adj[0]["t"] = adj[0]["t"].replace("05:00", "06:00")
    assert _normalize_bars(
        {"BAD": _alpaca_rows()}, {"BAD": adj}, strict_adjustments=True
    ) == {}


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.asyncio
async def test_alpaca_valid_split_adjustments_preserve_raw_prices_and_real_factor_one(strict):
    raw = _alpaca_rows()
    adj = _alpaca_rows(50.0)
    adj[-1]["c"] = raw[-1]["c"]
    result = await fetch_daily_bars_single(
        "GOOD", START, END, client=_client({"GOOD": raw}, {"GOOD": adj}),
        strict_adjustments=strict,
    )
    assert [row["close"] for row in result] == [100.0] * len(DATES)
    assert [row["adj_factor"] for row in result] == [0.5] * 6 + [1.0]


@pytest.mark.asyncio
async def test_alpaca_legacy_default_still_fills_missing_adjustments_and_zero_raw_close():
    raw = _alpaca_rows()
    raw[-1]["c"] = 0
    result = await fetch_daily_bars_single(
        "LEGACY", START, END, client=_client({"LEGACY": raw}, {})
    )
    assert len(result) == len(DATES)
    assert [row["adj_factor"] for row in result] == [1.0] * len(DATES)


@pytest.mark.parametrize("bad_index", [0, 6], ids=["before-overlap", "after-overlap"])
@pytest.mark.parametrize("bad_close", INVALID_CLOSES, ids=INVALID_IDS)
@pytest.mark.asyncio
async def test_tiingo_strict_rejects_whole_reply_beyond_five_valid_overlap_dates(
    monkeypatch, bad_index, bad_close,
):
    rows = _tiingo_rows()
    _set_close(rows[bad_index], "adjClose", bad_close)
    get = _mock_tiingo(monkeypatch, rows)

    assert await fetch_historical_candles("BAD", START, END, strict_adjustments=True) == []
    get.assert_called_once()


@pytest.mark.parametrize("bad_close", INVALID_CLOSES, ids=INVALID_IDS)
@pytest.mark.asyncio
async def test_tiingo_strict_rejects_invalid_raw_close_without_inventing_factor_one(
    monkeypatch, bad_close,
):
    rows = _tiingo_rows()
    _set_close(rows[6], "close", bad_close)
    _mock_tiingo(monkeypatch, rows)
    assert await fetch_historical_candles("BAD", START, END, strict_adjustments=True) == []


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.asyncio
async def test_tiingo_valid_split_adjustments_preserve_raw_prices_and_real_factor_one(monkeypatch, strict):
    rows = _tiingo_rows()
    rows[0]["splitFactor"] = 2.0
    rows[0]["divCash"] = 0.25
    rows[-1]["adjClose"] = 100.0
    _mock_tiingo(monkeypatch, rows)
    result = await fetch_historical_candles("GOOD", START, END, strict_adjustments=strict)
    assert [row["close"] for row in result] == [100.0] * len(DATES)
    assert [row["adj_factor"] for row in result] == [0.5] * 6 + [1.0]
    assert result[0]["split_factor"] == 2.0
    assert result[0]["div_cash"] == 0.25


@pytest.mark.parametrize("bad_close", [MISSING, None, 0], ids=["missing", "null", "zero"])
@pytest.mark.asyncio
async def test_tiingo_legacy_default_still_fills_missing_or_falsey_adjusted_close(monkeypatch, bad_close):
    rows = _tiingo_rows()
    _set_close(rows[0], "adjClose", bad_close)
    _mock_tiingo(monkeypatch, rows)
    result = await fetch_historical_candles("LEGACY", START, END)
    assert len(result) == len(DATES)
    assert result[0]["adj_factor"] == 1.0
    assert result[-1]["adj_factor"] == 0.5


@pytest.mark.asyncio
async def test_tiingo_legacy_default_still_uses_factor_one_for_zero_raw_close(monkeypatch):
    rows = _tiingo_rows()
    rows[-1]["close"] = 0
    _mock_tiingo(monkeypatch, rows)
    result = await fetch_historical_candles("LEGACY", START, END)
    assert len(result) == len(DATES)
    assert result[-1]["adj_factor"] == 1.0


@pytest.fixture(autouse=True)
def fast_tiingo_governor(monkeypatch):
    from app.data.governor import Governor
    gov = Governor.for_testing("tiingo", rate=100000, capacity=100000)
    monkeypatch.setattr("app.data.tiingo.get_governor", lambda: gov)
