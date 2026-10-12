"""The live scan and Analysis pass the hold to the backtest (STOCKS-HORIZON-T1 H2).

hold_for_backtest(req.horizon, bt_strategy, req.hold_max_days) reaches
run_strategy_backtest as hold_max_days and is part of _backtest_key.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
from unittest.mock import MagicMock, patch

import pytest

from tests.test_stock_scan_backtest_commission import (
    _fake_bt_result,
    _fake_signal,
    _measured_trend,
)


def _card():
    card = MagicMock()
    card.status = "PASS"
    card.score = 70
    card.rules = [_measured_trend()]
    return card


def _bars(n: int = 130):
    return [{"close": 150.0, "open": 148.0, "high": 152.0, "low": 147.0,
             "volume": 1_000_000, "date": "2024-01-01", "time": i} for i in range(n)]


def _run_process_stock(req, strategy: str):
    from app.routers import stock_scan as ss

    ss._BACKTEST_CACHE.clear()
    captured: dict = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return _fake_bt_result()

    async def run():
        with patch("app.routers.stock_scan.score_stock", return_value=_card()), \
             patch("app.routers.stock_scan.get_historical_bars", return_value=_bars()), \
             patch("app.routers.stock_scan.fetch_intraday_candles", return_value=_bars(300)), \
             patch("app.routers.stock_scan.compute_omm", return_value=None), \
             patch("app.routers.stock_scan.compute_confidence", return_value=None), \
             patch("app.routers.stock_scan._get_fundamentals", return_value=None), \
             patch("app.routers.stock_scan.run_strategy_backtest", side_effect=fake_run), \
             patch("app.routers.stock_scan.fetch_company_name_async", return_value="Apple Inc"), \
             patch("app.routers.stock_scan.fetch_price_async", return_value=None), \
             patch("app.routers.stock_scan.get_active", return_value={}), \
             patch("app.routers.stock_scan.get_cached", return_value={"confidence": None, "sample_size": 0}), \
             patch("app.routers.stock_scan.set_cached", return_value=None), \
             patch("app.routers.stock_scan._BACKTEST_POOL", concurrent.futures.ThreadPoolExecutor(max_workers=1)), \
             patch.dict(ss._SIGNAL_FNS, {strategy: lambda *a, **k: _fake_signal()}):
            await ss._process_stock("AAPL", req, "test-scan-id", {}, [])

    asyncio.run(run())
    keys = list(ss._BACKTEST_CACHE)
    return captured, keys


@pytest.mark.parametrize("horizon, strategy, hold, expected", [
    ("Swing", "pullback_ema", None, 15),
    ("Position", "pullback_ema", None, 45),
    ("Swing", "pullback_ema", 30, 30),
    ("Intraday", "pullback_ema", None, None),
    ("Swing", "mean_reversion_vwap", None, None),
])
def test_process_stock_passes_hold(horizon, strategy, hold, expected):
    from app.schemas.stock_scan import StockScanRequest

    req = StockScanRequest(universe=["AAPL"], direction="Bullish", horizon=horizon,
                           strategy=strategy, hold_max_days=hold)
    captured, keys = _run_process_stock(req, strategy)

    assert "hold_max_days" in captured, "run_strategy_backtest was not given hold_max_days="
    assert captured["hold_max_days"] == expected
    assert len(keys) == 1
    assert keys[0].endswith(f"|hold={expected}")


def test_analyze_core_passes_hold():
    from app.routers import stock_scan as ss
    from app.schemas.stock_scan import StockAnalysisRequest

    ss._BACKTEST_CACHE.clear()
    captured: dict = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return _fake_bt_result()

    req = StockAnalysisRequest(symbol="AAPL", direction="Bullish", horizon="Swing",
                               strategy="pullback_ema")

    async def run():
        with patch("app.routers.stock_scan.get_historical_bars", return_value=_bars()), \
             patch("app.routers.stock_scan.fetch_quotes", return_value={}), \
             patch("app.routers.stock_scan.fetch_price_async", return_value=150.0), \
             patch("app.routers.stock_scan.fetch_company_name_async", return_value="Apple Inc"), \
             patch("app.routers.stock_scan.fetch_intraday_candles", return_value=[]), \
             patch("app.routers.stock_scan.score_stock", return_value=_card()), \
             patch("app.routers.stock_scan._get_fundamentals", return_value=None), \
             patch("app.routers.stock_scan.run_strategy_backtest", side_effect=fake_run),              patch("app.routers.stock_scan.get_cached", return_value={"confidence": 80, "sample_size": 50}),              patch("app.routers.stock_scan.set_cached", return_value=None), \
             patch("app.routers.stock_scan._BACKTEST_POOL", concurrent.futures.ThreadPoolExecutor(max_workers=1)), \
             patch.dict(ss._SIGNAL_FNS, {"pullback_ema": lambda *a, **k: _fake_signal()}):
            await ss._analyze_core("AAPL", req)

    asyncio.run(run())
    assert captured.get("hold_max_days", "missing") == 15
    assert [k for k in ss._BACKTEST_CACHE][0].endswith("|hold=15")


def test_backtest_key_differs_by_hold():
    from app.routers.stock_scan import _backtest_key

    bars = _bars(30)
    k15 = _backtest_key("AAPL", "pullback_ema", "Bullish", bars, {}, hold_max_days=15)
    k45 = _backtest_key("AAPL", "pullback_ema", "Bullish", bars, {}, hold_max_days=45)
    knone = _backtest_key("AAPL", "pullback_ema", "Bullish", bars, {})
    assert len({k15, k45, knone}) == 3
