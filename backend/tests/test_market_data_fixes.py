"""
Tests for WS-B: market.py data fixes.

Covers:
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

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
            exp_resp.json.return_value = {"expirations": {"date": ["2026-06-20"]}}

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
            exp_resp.json.return_value = {"expirations": {"date": ["2026-06-20"]}}

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
            # Prevent yfinance fallback from making network calls
            with patch("app.data.market._yf_iv_for_chain", return_value={}):
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
