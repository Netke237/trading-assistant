import asyncio
import concurrent.futures
import functools
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.strategy_backtest import run_strategy_backtest


def _fake_signal():
    sig = MagicMock()
    sig.entry_price = 150.0
    sig.stop_price = 145.0
    sig.target_price = 160.0
    sig.targets = [160.0]
    sig.rr_ratio = 2.0
    sig.atr = 3.0
    sig.detail = {}
    return sig


def _fake_bt_result():
    bt = MagicMock()
    bt.passes_gate = True
    bt.n_trades = 10
    bt.win_rate = 0.6
    bt.total_return_pct = 5.0
    bt.max_drawdown_pct = 2.0
    bt.expectancy = 1.5
    bt.sharpe = 1.2
    bt.summary_text = "ok"
    bt.n_time_exits = 0     # a real int: BacktestOut reads it (F2)
    return bt


def test_process_stock_passes_commission_from_get_costs():
    """_process_stock's run_strategy_backtest call (stock_scan.py ~line 793)
    must pass commission= sourced from strategy_param_store.get_costs(),
    not the previous hardcoded commission-free default."""
    from app.routers import stock_scan as ss
    from app.schemas.stock_scan import StockScanRequest

    ss._BACKTEST_CACHE.clear()
    captured: dict = {}

    def fake_run_strategy_backtest(*args, **kwargs):
        captured.update(kwargs)
        return _fake_bt_result()

    req = StockScanRequest(
        universe=["AAPL"], direction="Bullish", horizon="Swing", strategy="pullback_ema",
    )
    fake_bars = [{"close": 150.0, "open": 148.0, "high": 152.0, "low": 147.0,
                  "volume": 1_000_000, "date": "2024-01-01", "time": i} for i in range(130)]

    card = MagicMock()
    card.status = "PASS"
    card.score = 70
    card.rules = [_measured_trend()]

    async def run():
        # _process_stock always dispatches run_strategy_backtest through the
        # module's real _BACKTEST_POOL (a ProcessPoolExecutor — see S-3 audit
        # fix), which requires pickling the callable across a process boundary.
        # A patched MagicMock side_effect isn't picklable, so swap the pool for
        # a ThreadPoolExecutor for the duration of this test — same
        # run_in_executor dispatch shape, but in-process so the mock survives.
        with patch("app.routers.stock_scan.score_stock", return_value=card), \
             patch("app.routers.stock_scan.get_historical_bars", return_value=fake_bars), \
             patch("app.routers.stock_scan.compute_omm", return_value=None), \
             patch("app.routers.stock_scan.compute_confidence", return_value=None), \
             patch("app.routers.stock_scan._get_fundamentals", return_value=None), \
             patch("app.routers.stock_scan.run_strategy_backtest", side_effect=fake_run_strategy_backtest), \
             patch("app.routers.stock_scan.fetch_company_name_async", return_value="Apple Inc"), \
             patch("app.routers.stock_scan.fetch_price_async", return_value=None), \
             patch("app.routers.stock_scan.get_active", return_value={}), \
             patch("app.routers.stock_scan.get_costs", return_value={"fee_pct": 0.002, "slippage_pct": 0.003}), \
             patch("app.routers.stock_scan.get_cached", return_value={"confidence": None, "sample_size": 0}), \
             patch("app.routers.stock_scan.set_cached", return_value=None), \
             patch("app.routers.stock_scan._BACKTEST_POOL", concurrent.futures.ThreadPoolExecutor(max_workers=1)), \
             patch.dict(ss._SIGNAL_FNS, {"pullback_ema": lambda *a, **k: _fake_signal()}):
            await ss._process_stock("AAPL", req, "test-scan-id", {}, [])

    asyncio.run(run())
    assert "commission" in captured, "run_strategy_backtest was not called with a commission= kwarg"
    assert captured["commission"] == 0.005, (
        f"expected commission = fee_pct(0.002) + slippage_pct(0.003) = 0.005, got {captured['commission']}"
    )


def test_run_strategy_backtest_with_commission_works_through_real_process_pool():
    """Production call-shape check (2026-08-19 adversarial audit finding):
    every commission test above swaps stock_scan.py's real _BACKTEST_POOL
    (a ProcessPoolExecutor) for a ThreadPoolExecutor because a MagicMock
    side_effect isn't picklable across a process boundary — which means no
    test exercised the actual production dispatch path. This test uses the
    real run_strategy_backtest (no mocks) submitted to a real
    ProcessPoolExecutor via the same run_in_executor(pool, functools.partial(...))
    shape stock_scan.py uses in production, proving the function + a float
    commission kwarg genuinely round-trip across a process boundary."""
    bars = [
        {"time": f"2022-01-{(i % 28) + 1:02d}", "open": (50 + i * 0.05) * 0.998,
         "high": (50 + i * 0.05) * 1.01, "low": (50 + i * 0.05) * 0.99,
         "close": 50 + i * 0.05, "volume": 1000 + i}
        for i in range(500)
    ]

    async def run():
        loop = asyncio.get_running_loop()
        with concurrent.futures.ProcessPoolExecutor(max_workers=1) as pool:
            return await loop.run_in_executor(
                pool,
                functools.partial(run_strategy_backtest, bars, strategy="ma_crossover",
                                  direction="Bullish", commission=0.002),
            )

    result = asyncio.run(run())
    assert result.n_trades > 0, "fixture must produce real trades to prove the round-trip actually ran"
    assert isinstance(result.total_return_pct, float)


def test_backtest_key_differs_by_commission():
    """_backtest_key must fold commission into the cache key — otherwise a
    strategy_params.yaml costs.fee_pct/slippage_pct edit leaves stale
    pre-edit BacktestResult entries (including passes_gate) served out of
    _BACKTEST_CACHE for up to _BACKTEST_TTL (24h) under an unchanged key."""
    from app.routers.stock_scan import _backtest_key

    bars = [{"close": 150.0, "open": 148.0, "high": 152.0, "low": 147.0,
             "volume": 1_000_000, "time": i} for i in range(30)]
    params = {"tolerance": 0.04}

    key_low = _backtest_key("AAPL", "pullback_ema", "Bullish", bars, params, commission=0.001)
    key_high = _backtest_key("AAPL", "pullback_ema", "Bullish", bars, params, commission=0.01)
    assert key_low != key_high


def test_analyze_core_passes_commission_from_get_costs():
    """_analyze_core's run_strategy_backtest call (stock_scan.py ~line 379)
    must pass the same commission= as _process_stock."""
    from app.routers import stock_scan as ss
    from app.schemas.stock_scan import StockAnalysisRequest

    ss._BACKTEST_CACHE.clear()
    captured: dict = {}

    def fake_run_strategy_backtest(*args, **kwargs):
        captured.update(kwargs)
        return _fake_bt_result()

    req = StockAnalysisRequest(symbol="AAPL", direction="Bullish", horizon="Swing", strategy="pullback_ema")
    fake_bars = [{"close": 150.0, "open": 148.0, "high": 152.0, "low": 147.0,
                  "volume": 1_000_000, "time": i} for i in range(130)]

    # A real card, not a MagicMock: _analyze_core caps the status with
    # dataclasses.replace() (the confidence cap, the bearish cap, the earnings
    # veto), which raises on anything that is not a dataclass (#129).
    from app.scoring.stock_scorer import StockScoreCard
    card = StockScoreCard(symbol="AAPL", direction="Bullish", horizon="Swing",
                          score=70, status="PASS", rules=[_measured_trend()])

    async def run():
        # The inputs this test does not own are pinned, so its result cannot
        # depend on the confidence cache's state (machine- and order-dependent)
        # or on a live earnings lookup: a fixed MEASURED confidence, and a known
        # earnings date well outside the hold.
        # Same ProcessPoolExecutor-vs-MagicMock pickling problem as
        # test_process_stock_passes_commission_from_get_costs above — swap in
        # a ThreadPoolExecutor for this test only.
        with patch("app.routers.stock_scan.get_historical_bars", return_value=fake_bars), \
             patch("app.routers.stock_scan.fetch_quotes", return_value={}), \
             patch("app.routers.stock_scan.fetch_price_async", return_value=150.0), \
             patch("app.routers.stock_scan.fetch_company_name_async", return_value="Apple Inc"), \
             patch("app.routers.stock_scan.fetch_intraday_candles", return_value=[]), \
             patch("app.routers.stock_scan.score_stock", return_value=card), \
             patch("app.routers.stock_scan._get_fundamentals", return_value=None), \
             patch("app.routers.stock_scan.run_strategy_backtest", side_effect=fake_run_strategy_backtest), \
             patch("app.routers.stock_scan.get_costs", return_value={"fee_pct": 0.002, "slippage_pct": 0.003}), \
             patch("app.routers.stock_scan.get_cached", return_value={"confidence": 70, "sample_size": 50}), \
             patch("app.routers.stock_scan.set_cached", return_value=None), \
             patch("app.routers.stock_scan._earnings_days_for", AsyncMock(return_value=90)), \
             patch("app.routers.stock_scan._BACKTEST_POOL", concurrent.futures.ThreadPoolExecutor(max_workers=1)), \
             patch.dict(ss._SIGNAL_FNS, {"pullback_ema": lambda *a, **k: _fake_signal()}):
            await ss._analyze_core("AAPL", req)

    asyncio.run(run())
    assert "commission" in captured, "run_strategy_backtest was not called with a commission= kwarg"
    assert captured["commission"] == 0.005


def _measured_trend():
    """A measured, passing trend rule: since P3a the direction gate removes a
    card with no trend rule (or an unmeasured one) as "no data"."""
    from app.scoring.stock_scorer import RuleResult
    return RuleResult("trend", "PASS", 90, {})


def test_backtest_commission_uses_walk_forward_commission_for():
    """Phase C hygiene T7: the stock-scan backtest and the WFO tuner charge one
    per-leg commission rule (walk_forward.commission_for), so they cannot drift."""
    from app.routers.stock_scan import _backtest_commission
    from app.services.walk_forward import commission_for

    costs = {"fee_pct": 0.002, "slippage_pct": 0.003}
    with patch("app.routers.stock_scan.get_costs", return_value=costs):
        got = _backtest_commission()
    assert got == commission_for(costs) == 0.005


def test_backtest_commission_defaults_when_costs_block_empty():
    """An empty costs block falls back to fee 0.001 + slippage 0.001 per leg."""
    from app.routers.stock_scan import _backtest_commission
    from app.services.walk_forward import commission_for

    with patch("app.routers.stock_scan.get_costs", return_value={}):
        got = _backtest_commission()
    assert got == commission_for({}) == 0.002
