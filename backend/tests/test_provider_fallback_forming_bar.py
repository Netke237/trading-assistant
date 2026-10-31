"""PROVIDER-FALLBACK-FORMING-BAR (#536): fetch_candles_async returns completed
daily bars only.

The Options scan's DB-miss fallback (`scan._process_symbol` ->
`fetch_candles_async`) asked Tradier/yfinance for history ending
`date.today()` and kept a today-dated bar whose OHLCV was still moving, so a
DB-miss symbol mid-session was scored, stopped and targeted on a partial bar.
The fix trims with `composite_trigger_evaluator.completed_daily_rows` (the
repo's `todays_bar_is_unclosed` rule for ISO-date rows, anchored in MARKET_TZ)
on whatever the function returns, keeps the raw rows in `_candles_cache`, and
serves a cache hit only inside the session-boundary interval it was written in
(`_candles_cache_cutoff`), so an 11:00 snapshot is not served as the closed bar
at 16:30. Plan: docs/superpowers/plans/2026-10-31-provider-fallback-forming-bar-plan.md
sections 2, 2b, 2c, 4.

The clock is pinned through `market._daily_bar_clock`; the host-date stamp of
the cache is still the real `date.today()`, which a write and a read within one
test share.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

import app.data.market as mkt

NY = ZoneInfo("America/New_York")
D = date(2026, 6, 10)            # a Wednesday
D_ISO = D.isoformat()
D_MINUS_1 = "2026-06-09"


def _ny(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 6, 10, hour, minute, tzinfo=NY)


def _days(last_close: float = 100.5) -> list[dict]:
    """Tradier `history.day` items, weekdays 2026-05-11 .. D, newest last."""
    out = []
    day = date(2026, 5, 11)
    while day <= D:
        if day.weekday() < 5:
            out.append({"date": day.isoformat(), "open": 100.0, "high": 101.0,
                        "low": 99.0, "close": 100.25, "volume": 1000})
        day += timedelta(days=1)
    out[-1]["close"] = last_close
    return out


def _resp(days: list[dict]) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"history": {"day": days}}
    return resp


def _client(*resps) -> AsyncMock:
    client = AsyncMock()
    client.get = AsyncMock(side_effect=list(resps))
    return client


def _pin(monkeypatch, now: datetime) -> None:
    # raising=False so the unchanged code (no seam yet) fails on the behaviour
    # assertions, not on the monkeypatch.
    monkeypatch.setattr(mkt, "_daily_bar_clock", lambda: now, raising=False)


# 1 -- mid-session, Tradier history ending NY-today -> ends at D-1.
@pytest.mark.asyncio
async def test_mid_session_drops_today_bar_from_tradier(monkeypatch):
    _pin(monkeypatch, _ny(11))
    out = await mkt.fetch_candles_async(_client(_resp(_days())), "AAPL")
    assert out[-1]["time"] == D_MINUS_1
    assert all(r["time"] != D_ISO for r in out)


# 2 -- pre-open the D row is dropped; after the close it is kept.
@pytest.mark.asyncio
@pytest.mark.parametrize("hour, last", [(8, D_MINUS_1), (17, D_ISO)])
async def test_pre_open_drops_after_close_keeps(monkeypatch, hour, last):
    _pin(monkeypatch, _ny(hour))
    out = await mkt.fetch_candles_async(_client(_resp(_days())), "AAPL")
    assert out[-1]["time"] == last


# 3 -- Tradier fails, yfinance returns a today-dated row mid-session -> dropped.
@pytest.mark.asyncio
async def test_yfinance_fallback_today_bar_dropped(monkeypatch):
    _pin(monkeypatch, _ny(11))
    bad = MagicMock()
    bad.status_code = 500
    bad.raise_for_status.side_effect = RuntimeError("tradier down")
    yf_rows = [{"time": d["date"], "open": d["open"], "high": d["high"], "low": d["low"],
                "close": d["close"], "volume": d["volume"]} for d in _days()]
    monkeypatch.setattr(mkt, "_fetch_daily_yf", lambda symbol: list(yf_rows))
    out = await mkt.fetch_candles_async(_client(bad), "AAPL")
    assert out, "the yfinance fallback must still serve history"
    assert out[-1]["time"] == D_MINUS_1


# 4 -- cache hit inside one session-boundary interval: no second provider call,
# the returned list is trimmed, the cached entry is still the raw list.
@pytest.mark.asyncio
async def test_cache_hit_is_trimmed_and_cache_stays_raw(monkeypatch):
    _pin(monkeypatch, _ny(10))
    client = _client(_resp(_days()))
    first = await mkt.fetch_candles_async(client, "AAPL")
    cached_rows, _ = mkt._candles_cache["AAPL"]
    raw_len = len(cached_rows)
    assert cached_rows[-1]["time"] == D_ISO

    _pin(monkeypatch, _ny(11))
    second = await mkt.fetch_candles_async(client, "AAPL")

    assert client.get.call_count == 1
    assert second[-1]["time"] == D_MINUS_1
    assert second == first
    after_rows, _ = mkt._candles_cache["AAPL"]
    assert after_rows is cached_rows
    assert len(after_rows) == raw_len
    assert after_rows[-1]["time"] == D_ISO


# 4b -- a snapshot is valid for one session boundary, not one host date.
@pytest.mark.asyncio
async def test_async_written_snapshot_refetched_after_close(monkeypatch):
    _pin(monkeypatch, _ny(11))
    client = _client(_resp(_days(last_close=100.5)), _resp(_days(last_close=107.75)))
    await mkt.fetch_candles_async(client, "AAPL")

    _pin(monkeypatch, _ny(16, 30))
    out = await mkt.fetch_candles_async(client, "AAPL")

    assert client.get.call_count == 2
    assert out[-1]["time"] == D_ISO
    assert out[-1]["close"] == 107.75     # the refetched bar, not the 11:00 snapshot


@pytest.mark.asyncio
async def test_sync_written_snapshot_hits_in_session_and_refetched_after_close(monkeypatch):
    _pin(monkeypatch, _ny(11))
    with patch("app.data.market.httpx.get", return_value=_resp(_days(last_close=100.5))):
        mkt.fetch_candles("AAPL", bars=10)
    assert mkt._candles_cache["AAPL"][0][-1]["close"] == 100.5

    # Same session-boundary interval: the sync writer's cutoff record makes
    # this a hit (no async provider call), served trimmed.
    _pin(monkeypatch, _ny(11, 30))
    client = _client(_resp(_days(last_close=107.75)))
    hit = await mkt.fetch_candles_async(client, "AAPL")
    assert client.get.call_count == 0
    assert hit[-1]["time"] == D_MINUS_1

    # After the close: the 11:00 snapshot is a miss and is refetched.
    _pin(monkeypatch, _ny(16, 30))
    out = await mkt.fetch_candles_async(client, "AAPL")
    assert client.get.call_count == 1
    assert out[-1]["time"] == D_ISO
    assert out[-1]["close"] == 107.75


@pytest.mark.asyncio
async def test_entry_without_cutoff_record_is_refetched(monkeypatch):
    _pin(monkeypatch, _ny(11))
    stale = [{"time": d["date"], "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0,
              "volume": 1} for d in _days()]
    mkt._candles_cache["AAPL"] = (stale, date.today().isoformat())
    getattr(mkt, "_candles_cache_cutoff", {}).pop("AAPL", None)

    client = _client(_resp(_days()))
    out = await mkt.fetch_candles_async(client, "AAPL")

    assert client.get.call_count == 1
    assert out[-1]["close"] == 100.25     # refetched D-1 row, not the stale 1.0
    assert mkt._candles_cache_cutoff["AAPL"] == datetime(2026, 6, 9, 16, 0, tzinfo=NY)


# 4c -- confidences persisted from forming bars must miss.
def test_confidence_basis_is_b4():
    import app.data.confidence_cache as cc

    assert cc.BARS_BASIS_VERSION == "b4"
    key = cc.cache_key("AAPL", "Bullish", "Swing", None, None, scoring_mode="options")
    assert key.endswith("|b4")


# 5 -- host-zone independence: the same instant given in UTC.
@pytest.mark.asyncio
async def test_utc_instant_equal_to_mid_session_same_result(monkeypatch):
    _pin(monkeypatch, datetime(2026, 6, 10, 15, 0, tzinfo=timezone.utc))  # 11:00 EDT
    out = await mkt.fetch_candles_async(_client(_resp(_days())), "AAPL")
    assert out[-1]["time"] == D_MINUS_1


def test_daily_bar_clock_is_market_tz():
    now = mkt._daily_bar_clock()
    assert now.tzinfo is not None
    assert now.utcoffset() == datetime.now(NY).utcoffset()
    assert str(now.tzinfo) == "America/New_York"


# 6 -- acceptance at the Options scan seam: a DB-miss symbol mid-session is
# measured on completed bars only.
@pytest.mark.asyncio
async def test_options_scan_db_miss_scores_completed_bars_only(monkeypatch):
    from app.routers.scan import _process_symbol

    _pin(monkeypatch, _ny(11))
    sem = MagicMock()
    sem.__aenter__ = AsyncMock(return_value=sem)
    sem.__aexit__ = AsyncMock(return_value=False)
    client = _client(_resp(_days()))

    with patch("app.routers.scan.fetch_price_async", new_callable=AsyncMock, return_value=100.5), \
         patch("app.routers.scan.fetch_company_name_async", new_callable=AsyncMock, return_value="Apple Inc."), \
         patch("app.routers.scan.fetch_fundamentals_calendar", new_callable=AsyncMock, return_value={}), \
         patch("app.routers.scan.fetch_calendar_dates_async", new_callable=AsyncMock, return_value=(None, None)), \
         patch("app.routers.scan.get_daily_regime_bars", new_callable=AsyncMock, return_value=[]), \
         patch("app.routers.scan.score_stock") as mock_score, \
         patch("app.routers.scan.log_event"):
        mock_score.return_value = MagicMock(status="REJECT", score=20, rules=[], components={})

        result = await _process_symbol(
            symbol="AAPL",
            direction="Bullish",
            horizon="Swing",
            client=client,
            sem=sem,
            scan_id="test-forming-bar",
            bars_map={"MSFT": [{"time": D_MINUS_1, "open": 1.0, "high": 1.0, "low": 1.0,
                                "close": 1.0, "volume": 1}]},
        )

    assert result is not None
    assert client.get.call_count == 1          # the real fallback reached Tradier
    mock_score.assert_called()
    scored = mock_score.call_args.args[3]
    assert scored[-1]["time"] == D_MINUS_1
    assert all(c["time"] != D_ISO for c in scored)
