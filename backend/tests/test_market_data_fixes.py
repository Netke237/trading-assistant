"""
Tests for WS-B: market.py data fixes.

Covers:
  - fetch_candles_async date-based cache TTL (O-1)
  - Interval mapping dict (_YF_INTERVAL_MAP)
  - daily/weekly yfinance interval translation
  - IBKR source wired for 1h/4h/daily/weekly
  - IBKR skipped for short intraday intervals
  - Tradier wins on timestamp conflict over IBKR
  - Fallback to yfinance when IBKR returns []
  - IV enrichment applied when IBKR returns metrics
  - IV enrichment skipped gracefully when IBKR returns None
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pandas as pd

# fetch_option_chain only selects expiries at least 21 days out, so tests must
# use a date computed relative to "today" — a hard-coded date eventually drifts
# inside the 21-day window and makes the chain come back empty.
_FUTURE_EXPIRY = (date.today() + timedelta(days=30)).isoformat()

# ── Helpers ───────────────────────────────────────────────────────────────────


def _bar(ts: int, close: float = 100.0) -> dict:
    return {
        "time": ts,
        "open": close,
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
        "volume": 1000,
    }


def _fake_chain_contract(strike: int = 150) -> dict:
    return {
        "id": f"AAPL|{strike}|2026-06-20|C",
        "symbol": "AAPL",
        "strike": strike,
        "expiry": "2026-06-20",
        "right": "C",
        "dte": 22,
        "dteTotal": 22,
        "price": 3.5,
        "delta": 0.45,
        "theta": -0.05,
        "ivRank": 30,
        "ivPercentile": 0,
        "spread": 0.10,
        "volume": 500,
        "open_interest": 1200,
        "score": 0,
    }


# ── Test 1: interval mapping — "daily" maps to "1d" ──────────────────────────


def test_interval_map_daily():
    from app.data.market import _YF_INTERVAL_MAP

    assert _YF_INTERVAL_MAP["daily"] == "1d"


# ── Test 2: interval mapping — "weekly" maps to "1wk" ────────────────────────


def test_interval_map_weekly():
    from app.data.market import _YF_INTERVAL_MAP

    assert _YF_INTERVAL_MAP["weekly"] == "1wk"


# ── Test 3: fetch_intraday_candles with interval="daily" calls yfinance with "1d" ──


def test_daily_interval_calls_yf_with_1d():
    """fetch_intraday_candles("SPY", "daily") must pass "1d" to _fetch_intraday_yf."""
    from app.data.market import fetch_intraday_candles

    captured_intervals: list[str] = []

    def _fake_yf(symbol, interval, days):
        captured_intervals.append(interval)
        return [_bar(1_700_000_000)]

    with (
        patch("app.data.market.TRADIER_TOKEN", ""),  # skip Tradier
        patch("app.data.market._fetch_intraday_yf", side_effect=_fake_yf),
        # IBKR not available
        patch("app.data.market.fetch_intraday_ibkr", return_value=[], create=True),
    ):
        result = fetch_intraday_candles("SPY", interval="daily", days=365)

    assert "1d" in captured_intervals, f"Expected '1d' in calls, got: {captured_intervals}"
    assert len(result) > 0


# ── Test: "1D" (chart-facing spelling) must resolve the same way "daily" does ──


def test_1D_interval_alias_calls_yf_with_1d_and_full_history():
    """fetch_intraday_candles("SPY", "1D") — the chart's actual interval spelling —
    must resolve identically to interval="daily": pass "1d" to yfinance AND request
    the full 3650-day window, not silently fall back to the 55-day default."""
    from app.data.market import fetch_intraday_candles

    captured_intervals: list[str] = []
    captured_days: list[int] = []

    def _fake_yf(symbol, interval, days):
        captured_intervals.append(interval)
        captured_days.append(days)
        return [_bar(1_700_000_000)]

    # Note: fetch_intraday_candles imports fetch_intraday_ibkr locally inside its
    # own body, so patching "app.data.market.fetch_intraday_ibkr" would be a no-op —
    # left unmocked; IBKR falls back to [] on its own via ibkr_available()'s real
    # (fast-failing when no gateway is running) health check.
    with (
        patch("app.data.market.TRADIER_TOKEN", ""),
        patch("app.data.market._fetch_intraday_yf", side_effect=_fake_yf),
    ):
        result = fetch_intraday_candles("SPY", interval="1D", days=3650)

    assert "1d" in captured_intervals, f"Expected '1d' in calls, got: {captured_intervals}"
    assert 3650 in captured_days, f"Expected the full 3650-day window requested, got: {captured_days}"
    assert len(result) > 0


def test_1W_interval_alias_calls_yf_with_1wk():
    """fetch_intraday_candles("SPY", "1W") must resolve the same way interval="weekly" does."""
    from app.data.market import fetch_intraday_candles

    captured_intervals: list[str] = []

    def _fake_yf(symbol, interval, days):
        captured_intervals.append(interval)
        return [_bar(1_700_000_000)]

    # Note: fetch_intraday_ibkr is imported locally inside fetch_intraday_candles,
    # so it can't be patched via "app.data.market.fetch_intraday_ibkr" — left
    # unmocked, same as the "1D" test above.
    with (
        patch("app.data.market.TRADIER_TOKEN", ""),
        patch("app.data.market._fetch_intraday_yf", side_effect=_fake_yf),
    ):
        result = fetch_intraday_candles("SPY", interval="1W", days=3650)

    assert "1wk" in captured_intervals, f"Expected '1wk' in calls, got: {captured_intervals}"
    assert len(result) > 0


@pytest.mark.asyncio
async def test_get_intraday_widens_daily_weekly_at_production_default():
    """The chart's real entry points (WS stream + /chart/history) pass days=55.
    get_intraday must widen daily/weekly to a multi-year window *at the caching
    layer* — so the cache key reflects the real window — while leaving intraday
    (and non-chart callers of fetch_intraday_candles) untouched at 55."""
    from app.data import chart_cache

    captured: list[tuple[str, int]] = []

    def _fake_fetch(symbol, interval, days):
        captured.append((interval, days))
        return [_bar(1_700_000_000)]

    chart_cache._INTRADAY_CACHE.clear()
    with patch("app.data.chart_cache.fetch_intraday_candles", side_effect=_fake_fetch):
        await chart_cache.get_intraday("SPY", "1D", days=55)
        await chart_cache.get_intraday("SPY", "1W", days=55)
        await chart_cache.get_intraday("SPY", "15min", days=55)

    # daily/weekly widened; intraday left alone
    assert ("daily", chart_cache._CHART_DAILY_DAYS) in captured, captured
    assert ("weekly", chart_cache._CHART_WEEKLY_DAYS) in captured, captured
    assert ("15min", 55) in captured, captured
    # the cache key must reflect the widened window, not the caller's 55
    assert f"SPY:daily:{chart_cache._CHART_DAILY_DAYS}" in chart_cache._INTRADAY_CACHE
    assert "SPY:daily:55" not in chart_cache._INTRADAY_CACHE


def test_ibkr_used_for_1D_interval():
    """IBKR must be attempted for interval='1D' too, not just 'daily' — same fix as above."""
    from app.data.market import fetch_intraday_candles
    import app.data.ibkr as ibkr_mod

    ibkr_bars = [_bar(1_700_000_000, close=200.0)]
    original = ibkr_mod.fetch_intraday_ibkr
    ibkr_mod.fetch_intraday_ibkr = lambda s, iv, d: ibkr_bars
    try:
        with (
            patch("app.data.market.TRADIER_TOKEN", ""),
            patch("app.data.market._fetch_intraday_yf", return_value=[]),
        ):
            result = fetch_intraday_candles("SPY", interval="1D", days=3650)
    finally:
        ibkr_mod.fetch_intraday_ibkr = original

    assert any(b["close"] == 200.0 for b in result), "Expected IBKR bar in result for '1D' interval"


# ── Test 4: IBKR source included for "1h" interval ───────────────────────────


def test_ibkr_used_for_1h_interval():
    """For interval='1h', IBKR bars should be merged into the result."""
    from app.data.market import fetch_intraday_candles

    ibkr_bars = [_bar(1_700_000_000, close=200.0)]

    def _fake_yf(symbol, interval, days):
        return []

    with (
        patch("app.data.market.TRADIER_TOKEN", ""),
        patch("app.data.market._fetch_intraday_yf", side_effect=_fake_yf),
        patch("app.data.market.fetch_intraday_ibkr", return_value=ibkr_bars, create=True),
    ):
        # Patch the local import inside fetch_intraday_candles
        with patch("app.data.ibkr.fetch_intraday_ibkr", return_value=ibkr_bars, create=True):
            # Direct patch of the module-level import path used in the function
            import app.data.market as market_mod
            import app.data.ibkr as ibkr_mod
            original = ibkr_mod.fetch_intraday_ibkr

            ibkr_mod.fetch_intraday_ibkr = lambda s, iv, d: ibkr_bars
            try:
                result = fetch_intraday_candles("SPY", interval="1h", days=730)
            finally:
                ibkr_mod.fetch_intraday_ibkr = original

    assert any(b["close"] == 200.0 for b in result), "Expected IBKR bar in result"


# ── Test 5: IBKR source skipped for "15min" interval ─────────────────────────


def test_ibkr_skipped_for_15min():
    """For interval='15min', IBKR fetch should NOT be called."""
    from app.data.market import fetch_intraday_candles
    import app.data.ibkr as ibkr_mod

    call_log: list[str] = []
    original_fn = ibkr_mod.fetch_intraday_ibkr

    def _spy_ibkr(symbol, interval, lookback):
        call_log.append(interval)
        return []

    ibkr_mod.fetch_intraday_ibkr = _spy_ibkr
    try:
        with (
            patch("app.data.market.TRADIER_TOKEN", ""),
            patch("app.data.market._fetch_intraday_yf", return_value=[_bar(1_700_000_000)]),
        ):
            fetch_intraday_candles("SPY", interval="15min", days=55)
    finally:
        ibkr_mod.fetch_intraday_ibkr = original_fn

    assert call_log == [], f"IBKR should not be called for 15min, got calls: {call_log}"


# ── Test 6: Tradier bars override IBKR bars on timestamp conflict ─────────────


def test_tradier_overrides_ibkr_on_conflict():
    """When Tradier and IBKR have bars at the same timestamp, Tradier wins.

    We patch _TRADIER_INTRADAY_INTERVALS to include "1h" so the Tradier block
    fires, and mock ibkr.fetch_intraday_ibkr to return a bar at the same timestamp
    with a different close.  The merged result must show the Tradier close.
    """
    from app.data.market import fetch_intraday_candles
    from datetime import datetime
    from zoneinfo import ZoneInfo
    import app.data.ibkr as ibkr_mod

    # Compute the exact unix timestamp Tradier parsing will produce.
    _EASTERN = ZoneInfo("America/New_York")
    tradier_time_str = "2023-11-14 09:30"
    shared_ts = int(datetime.fromisoformat(tradier_time_str).replace(tzinfo=_EASTERN).timestamp())

    ibkr_bar = _bar(shared_ts, close=111.0)

    original_fn = ibkr_mod.fetch_intraday_ibkr
    ibkr_mod.fetch_intraday_ibkr = lambda s, iv, d: [ibkr_bar]

    try:
        with (
            patch("app.data.market.TRADIER_TOKEN", "fake-token"),
            patch("app.data.market._fetch_intraday_yf", return_value=[]),
            # Expand Tradier's supported set so "1h" fires the Tradier block
            patch("app.data.market._TRADIER_INTRADAY_INTERVALS", {"1min", "5min", "15min", "1h"}),
            patch("app.data.market.httpx.get") as mock_get,
        ):
            mock_resp = MagicMock()
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.return_value = {
                "series": {
                    "data": [{
                        "time": tradier_time_str,
                        "open": 221.0,
                        "high": 223.0,
                        "low": 220.0,
                        "close": 222.0,
                        "volume": 1000,
                    }]
                }
            }
            mock_get.return_value = mock_resp
            result = fetch_intraday_candles("SPY", interval="1h", days=730)
    finally:
        ibkr_mod.fetch_intraday_ibkr = original_fn

    assert len(result) == 1
    assert result[0]["close"] == 222.0, (
        f"Expected Tradier bar (close=222.0) to win over IBKR (111.0), got {result[0]['close']}"
    )


# ── Test 7: When IBKR down (returns []), falls back to yfinance ───────────────


def test_ibkr_down_falls_back_to_yfinance():
    """If IBKR returns [], yfinance bars should still be returned."""
    from app.data.market import fetch_intraday_candles
    import app.data.ibkr as ibkr_mod

    yf_bars = [_bar(1_700_000_000, close=300.0)]
    original_fn = ibkr_mod.fetch_intraday_ibkr
    ibkr_mod.fetch_intraday_ibkr = lambda s, iv, d: []

    try:
        with (
            patch("app.data.market.TRADIER_TOKEN", ""),
            patch("app.data.market._fetch_intraday_yf", return_value=yf_bars),
        ):
            result = fetch_intraday_candles("SPY", interval="1h", days=730)
    finally:
        ibkr_mod.fetch_intraday_ibkr = original_fn

    assert len(result) == 1
    assert result[0]["close"] == 300.0


# ── Test 8: IV enrichment applied when IBKR returns metrics ──────────────────


def test_iv_enrichment_applied_when_ibkr_available():
    """fetch_option_chain should apply ivRank/ivPercentile from IBKR when available."""
    from app.data.market import fetch_option_chain
    import app.data.ibkr as ibkr_mod

    mock_contract = _fake_chain_contract(strike=150)
    ibkr_iv = {"ivRank": 72.5, "ivPercentile": 68.3}

    original_fetch_iv = ibkr_mod.fetch_iv_metrics_ibkr
    ibkr_mod.fetch_iv_metrics_ibkr = lambda s: ibkr_iv

    try:
        with patch("app.data.market.httpx.get") as mock_get:
            # First call: expirations
            exp_resp = MagicMock()
            exp_resp.raise_for_status.return_value = None
            exp_resp.json.return_value = {"expirations": {"date": [_FUTURE_EXPIRY]}}

            # Second call: option chain
            chain_resp = MagicMock()
            chain_resp.raise_for_status.return_value = None
            chain_resp.json.return_value = {
                "options": {
                    "option": [{
                        "option_type": "call",
                        "strike": 150,
                        "bid": 3.40,
                        "ask": 3.60,
                        "volume": 500,
                        "open_interest": 1200,
                        "implied_volatility": 0.30,
                        "greeks": {"delta": 0.45, "theta": -0.05},
                    }]
                }
            }

            mock_get.side_effect = [exp_resp, chain_resp]
            result = fetch_option_chain("AAPL", option_type="C")
    finally:
        ibkr_mod.fetch_iv_metrics_ibkr = original_fetch_iv

    assert len(result) == 1
    assert result[0]["ivRank"] == 72.5, f"Expected ivRank=72.5, got {result[0]['ivRank']}"
    assert result[0]["ivPercentile"] == 68.3, (
        f"Expected ivPercentile=68.3, got {result[0]['ivPercentile']}"
    )


# ── Test 9: IV enrichment gracefully skipped when IBKR returns None ──────────


def test_iv_enrichment_skipped_when_ibkr_returns_none():
    """When IBKR IV returns None, fallback ivRank/ivPercentile should stay unchanged."""
    from app.data.market import fetch_option_chain
    import app.data.ibkr as ibkr_mod

    original_fetch_iv = ibkr_mod.fetch_iv_metrics_ibkr
    ibkr_mod.fetch_iv_metrics_ibkr = lambda s: None

    try:
        with patch("app.data.market.httpx.get") as mock_get:
            exp_resp = MagicMock()
            exp_resp.raise_for_status.return_value = None
            exp_resp.json.return_value = {"expirations": {"date": [_FUTURE_EXPIRY]}}

            chain_resp = MagicMock()
            chain_resp.raise_for_status.return_value = None
            chain_resp.json.return_value = {
                "options": {
                    "option": [{
                        "option_type": "call",
                        "strike": 150,
                        "bid": 3.40,
                        "ask": 3.60,
                        "volume": 500,
                        "open_interest": 1200,
                        "implied_volatility": 0.30,
                        "greeks": {"delta": 0.45, "theta": -0.05},
                    }]
                }
            }
            # Prevent yfinance fallback from making network calls, and make the
            # tastytrade IV fallback explicitly unavailable too (not just
            # accidentally unmocked) — this test's whole premise is "no IV
            # source besides the raw Tradier value is available."
            with (
                patch("app.data.market._yf_iv_for_chain", return_value={}),
                patch("app.data.tastytrade_iv.fetch_iv_metrics_tastytrade", return_value=None),
            ):
                mock_get.side_effect = [exp_resp, chain_resp]
                result = fetch_option_chain("AAPL", option_type="C")
    finally:
        ibkr_mod.fetch_iv_metrics_ibkr = original_fetch_iv

    # When IBKR returns None, ivRank should be the raw Tradier value (int(round(0.30*100))=30)
    # and ivPercentile should stay 0.
    assert len(result) == 1
    assert result[0]["ivRank"] == 30, f"Expected ivRank=30 (fallback), got {result[0]['ivRank']}"
    assert result[0]["ivPercentile"] == 0, (
        f"Expected ivPercentile=0 (fallback), got {result[0]['ivPercentile']}"
    )


# ── O-1: Date-based candle cache TTL ─────────────────────────────────────────


def _tradier_history_response() -> dict:
    return {
        "history": {
            "day": [{"date": "2025-06-09", "open": 100.0, "high": 101.0,
                     "low": 99.0, "close": 100.5, "volume": 1000}]
        }
    }


@pytest.mark.asyncio
async def test_fetch_candles_async_cache_stores_date_string():
    """After a successful fetch, the cache entry key must be an ISO date string."""
    import app.data.market as mkt

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = _tradier_history_response()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)

    saved = dict(mkt._candles_cache)
    mkt._candles_cache.clear()
    try:
        await mkt.fetch_candles_async(mock_client, "AAPL")
        _, cache_key = mkt._candles_cache["AAPL"]
    finally:
        mkt._candles_cache.clear()
        mkt._candles_cache.update(saved)

    assert isinstance(cache_key, str), f"Expected str cache key, got {type(cache_key)}"
    assert cache_key == date.today().isoformat()


@pytest.mark.asyncio
async def test_fetch_candles_async_yesterday_entry_triggers_new_fetch():
    """A cache entry stamped with yesterday's date must NOT be served — fresh HTTP call required."""
    import app.data.market as mkt

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    stale_bars = [{"time": yesterday, "open": 50.0, "high": 51.0,
                   "low": 49.0, "close": 50.5, "volume": 500}]

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = _tradier_history_response()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)

    saved = dict(mkt._candles_cache)
    mkt._candles_cache.clear()
    mkt._candles_cache["AAPL"] = (stale_bars, yesterday)
    try:
        await mkt.fetch_candles_async(mock_client, "AAPL")
    finally:
        mkt._candles_cache.clear()
        mkt._candles_cache.update(saved)

    mock_client.get.assert_called_once()


# ── Day-scoped caches: fetch_fundamentals_calendar + option-chain expirations ──


@pytest.mark.asyncio
async def test_fetch_fundamentals_calendar_cache_stores_date_string():
    """After a successful fetch, the cache entry key must be an ISO date string,
    mirroring _candles_cache's pattern (test_fetch_candles_async_cache_stores_date_string)."""
    import app.data.market as mkt

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = [{"results": [{"tables": {"earnings": {"report_date": "2026-09-01"}}}]}]

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)

    saved = dict(mkt._fundamentals_calendar_cache)
    mkt._fundamentals_calendar_cache.clear()
    try:
        await mkt.fetch_fundamentals_calendar(mock_client, "AAPL")
        _, cache_key = mkt._fundamentals_calendar_cache["AAPL"]
    finally:
        mkt._fundamentals_calendar_cache.clear()
        mkt._fundamentals_calendar_cache.update(saved)

    assert isinstance(cache_key, str), f"Expected str cache key, got {type(cache_key)}"
    assert cache_key == date.today().isoformat()


@pytest.mark.asyncio
async def test_fetch_fundamentals_calendar_second_call_skips_network():
    """A second call for the same symbol on the same day must be served from
    cache -- exactly one HTTP call total, not two."""
    import app.data.market as mkt

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = [{"results": [{"tables": {"earnings": {"report_date": "2026-09-01"}}}]}]

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)

    saved = dict(mkt._fundamentals_calendar_cache)
    mkt._fundamentals_calendar_cache.clear()
    try:
        first = await mkt.fetch_fundamentals_calendar(mock_client, "AAPL")
        second = await mkt.fetch_fundamentals_calendar(mock_client, "AAPL")
    finally:
        mkt._fundamentals_calendar_cache.clear()
        mkt._fundamentals_calendar_cache.update(saved)

    mock_client.get.assert_called_once()
    assert first == second


@pytest.mark.asyncio
async def test_fetch_fundamentals_calendar_empty_success_is_cached():
    """A genuinely empty response (Tradier successfully answers 'no calendar
    entries for this symbol') is a different case from a network failure
    (test_fetch_fundamentals_calendar_network_failure_not_cached) and must
    still be cached -- otherwise every call for a symbol with no calendar
    data re-fetches every time, defeating the point of this cache. Pins the
    property that distinguishes the two: cache on genuine response (empty or
    not), never cache on exception."""
    import app.data.market as mkt

    empty_resp = MagicMock()
    empty_resp.raise_for_status.return_value = None
    empty_resp.json.return_value = [{"results": []}]

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=empty_resp)

    saved = dict(mkt._fundamentals_calendar_cache)
    mkt._fundamentals_calendar_cache.clear()
    try:
        first = await mkt.fetch_fundamentals_calendar(mock_client, "AAPL")
        second = await mkt.fetch_fundamentals_calendar(mock_client, "AAPL")
    finally:
        mkt._fundamentals_calendar_cache.clear()
        mkt._fundamentals_calendar_cache.update(saved)

    assert first is None
    assert second is None
    mock_client.get.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_fundamentals_calendar_yesterday_entry_triggers_new_fetch():
    """A cache entry stamped with yesterday's date must NOT be served -- fresh
    HTTP call required, mirroring test_fetch_candles_async_yesterday_entry_triggers_new_fetch."""
    import app.data.market as mkt

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    stale_entry = {"tables": {"earnings": {"report_date": "2025-01-01"}}}

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = [{"results": [{"tables": {"earnings": {"report_date": "2026-09-01"}}}]}]

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)

    saved = dict(mkt._fundamentals_calendar_cache)
    mkt._fundamentals_calendar_cache.clear()
    mkt._fundamentals_calendar_cache["AAPL"] = (stale_entry, yesterday)
    try:
        await mkt.fetch_fundamentals_calendar(mock_client, "AAPL")
    finally:
        mkt._fundamentals_calendar_cache.clear()
        mkt._fundamentals_calendar_cache.update(saved)

    mock_client.get.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_fundamentals_calendar_network_failure_not_cached():
    """A transient HTTP failure (timeout, 5xx, etc.) must NOT be memoized --
    unlike a genuine empty response, it should not poison same-day calls for
    this symbol. The second call (a fresh, successful response) must make its
    own HTTP call rather than reusing a cached None from the first failure."""
    import app.data.market as mkt
    import httpx

    fail_resp = MagicMock()
    fail_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "server error", request=MagicMock(), response=MagicMock(status_code=503)
    )

    ok_resp = MagicMock()
    ok_resp.raise_for_status.return_value = None
    ok_resp.json.return_value = [{"results": [{"tables": {"earnings": {"report_date": "2026-09-01"}}}]}]

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[fail_resp, ok_resp])

    saved = dict(mkt._fundamentals_calendar_cache)
    mkt._fundamentals_calendar_cache.clear()
    try:
        first = await mkt.fetch_fundamentals_calendar(mock_client, "AAPL")
        second = await mkt.fetch_fundamentals_calendar(mock_client, "AAPL")
    finally:
        mkt._fundamentals_calendar_cache.clear()
        mkt._fundamentals_calendar_cache.update(saved)

    assert first is None
    assert second is not None
    assert mock_client.get.call_count == 2, (
        "the failed first call must not have cached a None result -- the "
        "second call should have retried against Tradier, not served a "
        "cached failure"
    )


@pytest.mark.asyncio
async def test_fetch_option_chain_async_expirations_cache_stores_date_string():
    """Mirrors test_fetch_candles_async_cache_stores_date_string for the
    expirations-list cache inside fetch_option_chain_async."""
    import app.data.market as mkt

    exp_resp = MagicMock()
    exp_resp.raise_for_status.return_value = None
    exp_resp.json.return_value = {"expirations": {"date": [_FUTURE_EXPIRY]}}

    chain_resp = MagicMock()
    chain_resp.raise_for_status.return_value = None
    chain_resp.json.return_value = {"options": {"option": []}}

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[exp_resp, chain_resp])

    saved = dict(mkt._expirations_cache)
    mkt._expirations_cache.clear()
    try:
        with (
            patch("app.data.ibkr.fetch_iv_metrics_ibkr", return_value=None),
            patch("app.data.tastytrade_iv.fetch_iv_metrics_tastytrade", return_value=None),
        ):
            await mkt.fetch_option_chain_async(mock_client, "AAPL", dte_bounds=(20, 40))
        _, cache_key = mkt._expirations_cache["AAPL"]
    finally:
        mkt._expirations_cache.clear()
        mkt._expirations_cache.update(saved)

    assert isinstance(cache_key, str), f"Expected str cache key, got {type(cache_key)}"
    assert cache_key == date.today().isoformat()


@pytest.mark.asyncio
async def test_fetch_option_chain_async_second_sequential_call_skips_expirations_call():
    """Two SEQUENTIAL chain fetches (one awaited fully before the next starts)
    for the same symbol on the same day must reuse the cached expirations
    list -- one expirations HTTP call total, even though each call still
    makes its own chain HTTP call (the chain itself is NOT cached, only the
    expirations list).

    Deliberately does NOT claim this holds for concurrent calls: scan.py's
    _build_spreads fetches the put and call legs for the same symbol via
    asyncio.gather (concurrently), so on a cache-cold symbol both coroutines
    can race past the cache-empty check before either writes to it, each
    issuing its own expirations call. This is a known, accepted gap in the
    cache's coverage for that one specific concurrent call site, not a bug in
    the cache itself -- subsequent calls (same day) still hit the now-warm
    cache. Not fixed here to avoid adding a lock/coalescing mechanism for a
    single-pair edge case."""
    import app.data.market as mkt

    exp_resp = MagicMock()
    exp_resp.raise_for_status.return_value = None
    exp_resp.json.return_value = {"expirations": {"date": [_FUTURE_EXPIRY]}}

    chain_resp = MagicMock()
    chain_resp.raise_for_status.return_value = None
    chain_resp.json.return_value = {"options": {"option": []}}

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[exp_resp, chain_resp, chain_resp])

    saved = dict(mkt._expirations_cache)
    mkt._expirations_cache.clear()
    try:
        with (
            patch("app.data.ibkr.fetch_iv_metrics_ibkr", return_value=None),
            patch("app.data.tastytrade_iv.fetch_iv_metrics_tastytrade", return_value=None),
        ):
            await mkt.fetch_option_chain_async(mock_client, "AAPL", dte_bounds=(20, 40))
            await mkt.fetch_option_chain_async(mock_client, "AAPL", dte_bounds=(20, 40))
    finally:
        mkt._expirations_cache.clear()
        mkt._expirations_cache.update(saved)

    urls_called = [c.args[0] if c.args else c.kwargs.get("url") for c in mock_client.get.call_args_list]
    expirations_calls = [u for u in urls_called if u and "expirations" in u]
    assert len(expirations_calls) == 1, f"expected exactly 1 expirations call, got {len(expirations_calls)}"
    assert mock_client.get.call_count == 3  # 1 expirations + 2 chain


@pytest.mark.asyncio
async def test_fetch_option_chain_async_yesterday_expirations_triggers_new_fetch():
    """A cache entry stamped with yesterday's date must NOT be served for the
    expirations list -- fresh HTTP call required."""
    import app.data.market as mkt

    yesterday = (date.today() - timedelta(days=1)).isoformat()

    exp_resp = MagicMock()
    exp_resp.raise_for_status.return_value = None
    exp_resp.json.return_value = {"expirations": {"date": [_FUTURE_EXPIRY]}}

    chain_resp = MagicMock()
    chain_resp.raise_for_status.return_value = None
    chain_resp.json.return_value = {"options": {"option": []}}

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[exp_resp, chain_resp])

    saved = dict(mkt._expirations_cache)
    mkt._expirations_cache.clear()
    mkt._expirations_cache["AAPL"] = (["2025-01-17"], yesterday)
    try:
        with (
            patch("app.data.ibkr.fetch_iv_metrics_ibkr", return_value=None),
            patch("app.data.tastytrade_iv.fetch_iv_metrics_tastytrade", return_value=None),
        ):
            await mkt.fetch_option_chain_async(mock_client, "AAPL", dte_bounds=(20, 40))
    finally:
        mkt._expirations_cache.clear()
        mkt._expirations_cache.update(saved)

    urls_called = [c.args[0] if c.args else c.kwargs.get("url") for c in mock_client.get.call_args_list]
    expirations_calls = [u for u in urls_called if u and "expirations" in u]
    assert len(expirations_calls) == 1


# ── O-7: Rate-limit yfinance IV chain fallback ────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_option_chain_async_yf_iv_fallback_acquires_semaphore():
    """When >50% of chain contracts have zero IV, the yfinance fallback must
    acquire _get_yf_sem() — preventing request storms during batch scans."""
    import app.data.market as mkt
    from datetime import timedelta

    future_exp = (date.today() + timedelta(days=30)).isoformat()

    mock_client = AsyncMock()
    exp_resp = MagicMock()
    exp_resp.raise_for_status.return_value = None
    exp_resp.json.return_value = {"expirations": {"date": [future_exp]}}

    chain_resp = MagicMock()
    chain_resp.raise_for_status.return_value = None
    chain_resp.json.return_value = {
        "options": {
            "option": [{
                "option_type": "call",
                "strike": 185,
                "bid": 2.40,
                "ask": 2.60,
                "volume": 500,
                "open_interest": 1000,
                "implied_volatility": 0.0,  # zero IV — triggers yfinance fallback
                "greeks": {"delta": 0.45, "theta": -0.05},
            }]
        }
    }
    mock_client.get.side_effect = [exp_resp, chain_resp]

    # Mock the semaphore getter so we can track if it was called
    mock_sem = MagicMock()
    mock_sem.__aenter__ = AsyncMock(return_value=mock_sem)
    mock_sem.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("app.data.market._get_yf_sem", return_value=mock_sem) as mock_sem_getter,
        patch("app.data.market._yf_iv_for_chain", return_value={}),
        patch("app.data.ibkr.fetch_iv_metrics_ibkr", return_value=None),
        patch("app.data.tastytrade_iv.fetch_iv_metrics_tastytrade", return_value=None),
    ):
        await mkt.fetch_option_chain_async(mock_client, "AAPL", option_type="C")

    mock_sem_getter.assert_called()


# ── Fix: yfinance leg must respect the caller-supplied `days` param ──────────


def test_yfinance_leg_respects_requested_days_below_cap():
    """fetch_intraday_candles's `days` param must be honored on the yfinance leg —
    previously it always passed the interval's max cap (yf_max), ignoring a smaller
    caller-requested days value. 15min's cap is 55 days; request fewer."""
    from app.data.market import fetch_intraday_candles

    captured_days: list[int] = []

    def _fake_yf(symbol, interval, days):
        captured_days.append(days)
        return [_bar(1_700_000_000)]

    with (
        patch("app.data.market.TRADIER_TOKEN", ""),
        patch("app.data.market._fetch_intraday_yf", side_effect=_fake_yf),
    ):
        result = fetch_intraday_candles("SPY", interval="15min", days=10)

    assert captured_days == [10], f"Expected yfinance to be asked for 10 days, got: {captured_days}"
    assert len(result) > 0


def test_yfinance_leg_still_caps_at_interval_max_when_days_exceeds_it():
    """A caller requesting more days than yfinance supports for the interval must
    still be capped at yf_max (15min's cap is 55 days), not passed through uncapped."""
    from app.data.market import fetch_intraday_candles

    captured_days: list[int] = []

    def _fake_yf(symbol, interval, days):
        captured_days.append(days)
        return [_bar(1_700_000_000)]

    with (
        patch("app.data.market.TRADIER_TOKEN", ""),
        patch("app.data.market._fetch_intraday_yf", side_effect=_fake_yf),
    ):
        result = fetch_intraday_candles("SPY", interval="15min", days=9999)

    assert captured_days == [55], f"Expected cap at 55 days, got: {captured_days}"
    assert len(result) > 0


def test_fetch_intraday_yf_4h_recursion_caps_at_730_days():
    """'4h' bars are fetched by a recursive _fetch_intraday_yf(interval='1h', ...)
    call, resampled to 4h afterward (see market.py:257-259). That recursive call's
    own min(days, 730) cap and this fix's outer fetch_intraday_candles-level cap
    both apply for '4h' — confirm the recursion itself still caps at 730 days when
    asked for more (period='2y' per _days_to_yf_period), independent of the outer fix."""
    from app.data.market import _fetch_intraday_yf

    captured_periods: list[str] = []

    def _capture_download(*args, **kwargs):
        captured_periods.append(kwargs.get("period"))
        return pd.DataFrame()  # empty df → _fetch_intraday_yf returns []

    with patch("yfinance.download", side_effect=_capture_download):
        result = _fetch_intraday_yf("SPY", interval="4h", days=9999)

    # Only the recursive '1h' call actually reaches yfinance.download for '4h'
    # (the outer '4h' branch just resamples the 1h result) — its own min(days, 730)
    # must cap 9999 down to 730 days, i.e. period='2y'.
    assert captured_periods == ["2y"], f"Expected the 730-day cap (period='2y'), got: {captured_periods}"
    assert result == []


# ── tastytrade IV fallback tier ───────────────────────────────────────────────


def test_fetch_option_chain_falls_back_to_tastytrade_when_ibkr_unavailable():
    """When IBKR returns None, tastytrade's real IV Rank/Percentile should be
    used instead of falling straight to the raw-IV proxy."""
    from app.data.market import fetch_option_chain
    import app.data.ibkr as ibkr_mod
    import app.data.tastytrade_iv as tasty_mod

    tasty_iv = {"AAPL": {"ivRank": 47.2, "ivPercentile": 51.9}}

    original_fetch_ibkr_iv = ibkr_mod.fetch_iv_metrics_ibkr
    ibkr_mod.fetch_iv_metrics_ibkr = lambda s: None  # IBKR unavailable

    original_fetch_tasty_iv = tasty_mod.fetch_iv_metrics_tastytrade
    tasty_mod.fetch_iv_metrics_tastytrade = lambda symbols: tasty_iv

    try:
        with patch("app.data.market.httpx.get") as mock_get:
            exp_resp = MagicMock()
            exp_resp.raise_for_status.return_value = None
            exp_resp.json.return_value = {"expirations": {"date": [_FUTURE_EXPIRY]}}

            chain_resp = MagicMock()
            chain_resp.raise_for_status.return_value = None
            chain_resp.json.return_value = {
                "options": {
                    "option": [{
                        "option_type": "call",
                        "strike": 150,
                        "bid": 3.40,
                        "ask": 3.60,
                        "volume": 500,
                        "open_interest": 1200,
                        "implied_volatility": 0.30,
                        "greeks": {"delta": 0.45, "theta": -0.05},
                    }]
                }
            }

            mock_get.side_effect = [exp_resp, chain_resp]

            result = fetch_option_chain("AAPL", option_type="C")
    finally:
        ibkr_mod.fetch_iv_metrics_ibkr = original_fetch_ibkr_iv
        tasty_mod.fetch_iv_metrics_tastytrade = original_fetch_tasty_iv

    assert len(result) == 1
    assert result[0]["ivRank"] == 47.2
    assert result[0]["ivPercentile"] == 51.9


@pytest.mark.asyncio
async def test_fetch_option_chain_async_falls_back_to_tastytrade_when_ibkr_unavailable():
    """Same fallback as the sync test, but through fetch_option_chain_async,
    which takes a caller-supplied httpx.AsyncClient and wraps both the IBKR
    and tastytrade calls in asyncio.to_thread."""
    from app.data.market import fetch_option_chain_async
    import app.data.ibkr as ibkr_mod
    import app.data.tastytrade_iv as tasty_mod

    tasty_iv = {"AAPL": {"ivRank": 47.2, "ivPercentile": 51.9}}

    original_fetch_ibkr_iv = ibkr_mod.fetch_iv_metrics_ibkr
    ibkr_mod.fetch_iv_metrics_ibkr = lambda s: None

    original_fetch_tasty_iv = tasty_mod.fetch_iv_metrics_tastytrade
    tasty_mod.fetch_iv_metrics_tastytrade = lambda symbols: tasty_iv

    exp_resp = MagicMock()
    exp_resp.raise_for_status.return_value = None
    exp_resp.json.return_value = {"expirations": {"date": [_FUTURE_EXPIRY]}}

    chain_resp = MagicMock()
    chain_resp.raise_for_status.return_value = None
    chain_resp.json.return_value = {
        "options": {
            "option": [{
                "option_type": "call",
                "strike": 150,
                "bid": 3.40,
                "ask": 3.60,
                "volume": 500,
                "open_interest": 1200,
                "implied_volatility": 0.30,
                "greeks": {"delta": 0.45, "theta": -0.05},
            }]
        }
    }

    fake_client = AsyncMock()
    fake_client.get = AsyncMock(side_effect=[exp_resp, chain_resp])

    try:
        result = await fetch_option_chain_async(fake_client, "AAPL", option_type="C")
    finally:
        ibkr_mod.fetch_iv_metrics_ibkr = original_fetch_ibkr_iv
        tasty_mod.fetch_iv_metrics_tastytrade = original_fetch_tasty_iv

    assert len(result) == 1
    assert result[0]["ivRank"] == 47.2
    assert result[0]["ivPercentile"] == 51.9


# ── fetch_quotes: fallback-to-close audit logging ──────────────────────────────

def test_fetch_quotes_logs_fallback_to_close():
    """When Tradier's quote has no 'last' price and we fall back to 'close',
    that fallback must be recorded via log_event so a bad/stale price used
    by an alert can be traced back after the fact."""
    from app.data import market

    with (
        patch("app.data.market.TRADIER_TOKEN", "fake-token"),
        patch("app.data.market.httpx.get") as mock_get,
        patch("app.data.market.log_event") as mock_log_event,
    ):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "quotes": {
                "quote": [
                    {"symbol": "AAPL", "last": None, "close": 283.35, "prevclose": 282.0},
                ]
            }
        }
        mock_get.return_value = mock_resp

        result = market.fetch_quotes(["AAPL"])

    assert result["AAPL"]["last"] == 283.35
    mock_log_event.assert_called_once()
    event_type, rec_id, payload = mock_log_event.call_args.args
    assert event_type == "quote_fallback_to_close"
    assert rec_id == "AAPL"
    assert payload["raw_last"] is None
    assert payload["raw_close"] == 283.35
    assert payload["used_price"] == 283.35


def test_fetch_quotes_does_not_log_when_last_present():
    """A normal quote (last present) must not trigger the fallback log."""
    from app.data import market

    with (
        patch("app.data.market.TRADIER_TOKEN", "fake-token"),
        patch("app.data.market.httpx.get") as mock_get,
        patch("app.data.market.log_event") as mock_log_event,
    ):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "quotes": {
                "quote": [
                    {"symbol": "AAPL", "last": 301.05, "close": 300.90, "prevclose": 299.80},
                ]
            }
        }
        mock_get.return_value = mock_resp

        result = market.fetch_quotes(["AAPL"])

    assert result["AAPL"]["last"] == 301.05
    mock_log_event.assert_not_called()


# ── Fix: NaN OHLC bars from yfinance must be dropped, not passed through ──────
# yfinance occasionally returns a NaN Open/High/Low/Close for a thin or halted
# trading bar. FastAPI's response-model serialization turns that NaN into JSON
# `null`, which lightweight-charts then hard-asserts on and crashes the whole
# chart (see CandlestickChart/index.tsx and ChartPane/index.tsx's matching
# Number.isFinite guards). _fetch_daily_yf/_fetch_intraday_yf must drop the
# bad bar at the source instead of letting it reach the API response.


def test_fetch_daily_yf_drops_nan_ohlc_rows():
    from app.data.market import _fetch_daily_yf

    idx = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07"])
    df = pd.DataFrame(
        {
            "Open":   [100.0, float("nan"), 102.0],
            "High":   [101.0, float("nan"), 103.0],
            "Low":    [99.0,  float("nan"), 101.0],
            "Close":  [100.5, float("nan"), 102.5],
            "Volume": [1_000_000, 500_000, 1_200_000],
        },
        index=idx,
    )

    with patch("yfinance.download", return_value=df):
        result = _fetch_daily_yf("AAPL")

    assert [r["time"] for r in result] == ["2026-01-05", "2026-01-07"]
    assert all(
        isinstance(r[k], float) and r[k] == r[k]  # NaN != NaN
        for r in result
        for k in ("open", "high", "low", "close")
    )


def test_fetch_intraday_yf_drops_nan_ohlc_rows():
    from app.data.market import _fetch_intraday_yf

    idx = pd.to_datetime(
        ["2026-01-05 09:30", "2026-01-05 09:45", "2026-01-05 10:00"], utc=True
    )
    df = pd.DataFrame(
        {
            "Open":   [100.0, 101.0, float("nan")],
            "High":   [101.0, 102.0, float("nan")],
            "Low":    [99.0,  100.0, float("nan")],
            "Close":  [100.5, 101.5, float("nan")],
            "Volume": [10_000, 12_000, 8_000],
        },
        index=idx,
    )

    with patch("yfinance.download", return_value=df):
        result = _fetch_intraday_yf("AAPL", interval="15m", days=1)

    assert len(result) == 2
    assert all(
        isinstance(r[k], float) and r[k] == r[k]
        for r in result
        for k in ("open", "high", "low", "close")
    )
