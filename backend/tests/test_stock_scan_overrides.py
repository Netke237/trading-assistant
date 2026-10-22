import asyncio
from unittest.mock import MagicMock, patch
from app.schemas.stock_scan import StockScanRequest


def test_stock_scan_request_accepts_overrides():
    """StockScanRequest must accept an overrides dict."""
    req = StockScanRequest(
        universe=["AAPL"],
        direction="Bullish",
        horizon="Swing",
        strategy="pullback_ema",
        overrides={"weight_trend": 50, "weight_pullback": 10, "weight_trigger": 15,
                   "weight_event": 15, "weight_vol": 10},
    )
    assert req.overrides["weight_trend"] == 50


def test_stock_scan_request_overrides_defaults_to_empty():
    """When omitted, overrides must default to empty dict (not None)."""
    req = StockScanRequest(
        universe=["AAPL"], direction="Bullish", horizon="Swing", strategy="pullback_ema"
    )
    assert req.overrides == {}


def test_score_stock_receives_overrides_from_request():
    """_process_stock must forward req.overrides to score_stock as the overrides kwarg."""
    captured: dict = {}

    def fake_score_stock(**kwargs):
        captured.update(kwargs)
        card = MagicMock()
        card.status = "PASS"
        card.score = 70
        card.rules = []
        return card

    req = StockScanRequest(
        universe=["AAPL"], direction="Bullish", horizon="Swing", strategy="pullback_ema",
        overrides={"weight_trend": 50},
    )

    fake_signal = MagicMock()
    fake_signal.entry_price = 150.0
    fake_signal.stop_price = 145.0
    fake_signal.target_price = 160.0
    fake_signal.targets = [160.0]
    fake_signal.rr_ratio = 2.0
    fake_signal.atr = 3.0
    fake_signal.detail = {}

    fake_bt = MagicMock()
    fake_bt.passes_gate = True
    fake_bt.n_trades = 10
    fake_bt.win_rate = 0.6
    fake_bt.total_return_pct = 5.0
    fake_bt.max_drawdown_pct = 2.0
    fake_bt.expectancy = 1.5
    fake_bt.sharpe = 1.2
    fake_bt.summary_text = "ok"
    fake_bt.n_time_exits = 0     # a real int: BacktestOut reads it (F2)

    fake_bars = [{"close": 150.0, "open": 148.0, "high": 152.0, "low": 147.0, "volume": 1000000, "date": "2024-01-01"}] * 130

    async def run():
        with patch("app.routers.stock_scan.score_stock", side_effect=fake_score_stock), \
             patch("app.routers.stock_scan.get_historical_bars", return_value=fake_bars), \
             patch("app.routers.stock_scan.compute_omm", return_value=None), \
             patch("app.routers.stock_scan.compute_confidence", return_value=None), \
             patch("app.routers.stock_scan._get_fundamentals", return_value=None), \
             patch("app.routers.stock_scan.pullback_ema_signal", return_value=fake_signal), \
             patch("app.routers.stock_scan.run_strategy_backtest", return_value=fake_bt), \
             patch("app.routers.stock_scan.fetch_company_name_async", return_value="Apple Inc"), \
             patch("app.routers.stock_scan.fetch_price_async", return_value=None), \
             patch("app.routers.stock_scan.get_active", return_value={}), \
             patch("app.routers.stock_scan.get_cached", return_value={"confidence": None, "sample_size": 0}), \
             patch("app.routers.stock_scan.set_cached", return_value=None):
            from app.routers.stock_scan import _process_stock
            await _process_stock("AAPL", req, "test-scan-id", {}, [])

    asyncio.run(run())
    assert captured.get("overrides") == {"weight_trend": 50}, (
        f"score_stock was not called with overrides=req.overrides. Got: {captured.get('overrides')}"
    )
