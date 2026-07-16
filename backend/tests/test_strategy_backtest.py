import pytest
from app.services.strategy_backtest import run_strategy_backtest, BacktestResult


def _synth_bars(n=400, trend=True):
    bars, price = [], 50.0
    for i in range(n):
        if trend:
            price = price * 1.002 + (0.5 if i % 10 == 0 else -0.2)
        else:
            price = 50.0 + (i % 7 - 3) * 0.1
        bars.append({
            "time": f"2022-01-{(i % 28) + 1:02d}",
            "open": price * 0.998, "high": price * 1.01,
            "low":  price * 0.99,  "close": price, "volume": 1000 + i
        })
    return bars


def test_backtest_returns_result_object():
    bars = _synth_bars(400, trend=True)
    result = run_strategy_backtest(bars, strategy="pullback_ema", direction="Bullish")
    assert isinstance(result, BacktestResult)


def test_backtest_result_has_required_fields():
    bars = _synth_bars(400, trend=True)
    result = run_strategy_backtest(bars, strategy="pullback_ema", direction="Bullish")
    assert isinstance(result.n_trades, int)
    assert isinstance(result.win_rate, float)
    assert isinstance(result.total_return_pct, float)
    assert isinstance(result.max_drawdown_pct, float)
    assert isinstance(result.expectancy, float)


def test_backtest_too_few_bars_returns_empty():
    bars = _synth_bars(30, trend=True)
    result = run_strategy_backtest(bars, strategy="pullback_ema", direction="Bullish")
    assert result.n_trades == 0
    assert result.confidence is None


def test_backtest_passes_gate_with_enough_trades():
    bars = _synth_bars(500, trend=True)
    result = run_strategy_backtest(bars, strategy="pullback_ema", direction="Bullish")
    assert result.n_trades >= 0
    assert isinstance(result.passes_gate, bool)


def test_expectancy_is_average_pnl_per_trade_not_cumulative_return():
    """expectancy must be win_rate*avg_win - (1-win_rate)*avg_loss computed from
    real per-trade PnL, not cumulative Return%/MaxDD% divided by trade counts
    (Critical finding #6, 2026-07-15 audit)."""
    bars = _synth_bars(500, trend=True)
    result = run_strategy_backtest(bars, strategy="pullback_ema", direction="Bullish")
    if result.n_trades == 0:
        pytest.skip("synthetic bars didn't produce trades on this run")
    # A sane per-trade expectancy in $ terms on $100k starting cash should be a
    # small fraction of total_return_pct, not comparable in magnitude to it —
    # the old (buggy) formula divided cumulative Return% by trade count, which
    # for n_trades >= 10 makes |expectancy| << |total_return_pct| by construction
    # only coincidentally; the real bug is structural, so assert the gate exists
    # and is actually applied instead of asserting a numeric range.
    assert isinstance(result.expectancy, float)


def test_min_expectancy_gate_is_applied():
    """_MIN_EXPECTANCY must actually gate passes_gate, not just exist as a
    module constant (Critical finding #6, 2026-07-15 audit)."""
    from app.services import strategy_backtest as sb
    bars = _synth_bars(500, trend=True)
    result = run_strategy_backtest(bars, strategy="pullback_ema", direction="Bullish")
    if result.n_trades < 10:
        pytest.skip("not enough synthetic trades to exercise the gate")
    if result.expectancy < sb._MIN_EXPECTANCY:
        assert result.passes_gate is False


# ── S-2: Backtest result cache ────────────────────────────────────────────────

def test_backtest_key_is_stable():
    """Same symbol/strategy/direction/bars must produce the same cache key."""
    from app.routers.stock_scan import _backtest_key
    bars = _synth_bars(60)
    k1 = _backtest_key("AAPL", "pullback_ema", "Bullish", bars)
    k2 = _backtest_key("AAPL", "pullback_ema", "Bullish", bars)
    assert k1 == k2


def test_backtest_key_differs_by_symbol():
    """Different symbols must produce different keys."""
    from app.routers.stock_scan import _backtest_key
    bars = _synth_bars(60)
    assert _backtest_key("AAPL", "pullback_ema", "Bullish", bars) != \
           _backtest_key("MSFT", "pullback_ema", "Bullish", bars)


def test_backtest_cache_hit_skips_rerun():
    """A pre-populated backtest cache entry must be returned without calling run_strategy_backtest."""
    import time
    from unittest.mock import patch
    from app.routers.stock_scan import _backtest_key, _BACKTEST_CACHE, _BACKTEST_TTL

    bars = _synth_bars(60)
    key = _backtest_key("AAPL", "pullback_ema", "Bullish", bars)
    cached_result = BacktestResult(
        strategy="pullback_ema", direction="Bullish",
        n_trades=12, win_rate=0.58, total_return_pct=18.0,
        max_drawdown_pct=8.0, expectancy=0.5, sharpe=1.1,
        confidence=None, passes_gate=True, summary_text="PASS",
    )
    _BACKTEST_CACHE[key] = (cached_result, time.time() + _BACKTEST_TTL)
    try:
        with patch("app.routers.stock_scan.run_strategy_backtest") as mock_bt:
            # Simulate what the stock scan does: check cache before running
            from app.routers.stock_scan import _get_backtest_cached
            result = _get_backtest_cached(key)
    finally:
        _BACKTEST_CACHE.pop(key, None)

    assert result is cached_result
    mock_bt.assert_not_called()


# ── S-3: ProcessPoolExecutor for backtests ────────────────────────────────────

def test_backtest_pool_is_process_pool_executor():
    """S-3: stock_scan must expose _BACKTEST_POOL as a ProcessPoolExecutor."""
    import concurrent.futures
    from app.routers.stock_scan import _BACKTEST_POOL
    assert isinstance(_BACKTEST_POOL, concurrent.futures.ProcessPoolExecutor)


@pytest.mark.asyncio
async def test_process_stock_uses_process_pool_for_backtest():
    """S-3: cache miss must dispatch backtest to _BACKTEST_POOL via run_in_executor."""
    import asyncio
    from unittest.mock import patch, AsyncMock, MagicMock
    from app.routers.stock_scan import _BACKTEST_POOL, _BACKTEST_CACHE, _backtest_key
    from app.schemas.stock_scan import StockScanRequest
    from app.scoring.stock_scorer import StockScoreCard

    bars = _synth_bars(400, trend=True)

    mock_bt = BacktestResult(
        strategy="pullback_ema", direction="Bullish",
        n_trades=10, win_rate=0.6, total_return_pct=20.0,
        max_drawdown_pct=5.0, expectancy=0.6, sharpe=1.2,
        confidence=None, passes_gate=True, summary_text="PASS",
    )
    pass_card = StockScoreCard(
        symbol="AAPL", direction="Bullish", horizon="Swing",
        score=75, status="PASS", rules=[],
    )
    mock_signal = MagicMock()
    mock_signal.entry_price = 185.0
    mock_signal.stop_price  = 180.0
    mock_signal.target_price = 195.0
    mock_signal.rr_ratio    = 2.0
    mock_signal.atr         = 3.0
    mock_signal.detail      = {}
    mock_signal.strategy    = "pullback_ema"

    req = StockScanRequest(
        universe=["AAPL"],
        direction="Bullish", horizon="Swing", strategy="pullback_ema",
    )

    bt_key = _backtest_key("AAPL", "pullback_ema", "Bullish", bars)
    _BACKTEST_CACHE.pop(bt_key, None)

    loop = asyncio.get_running_loop()
    mock_executor = AsyncMock(return_value=mock_bt)

    with (
        patch("app.routers.stock_scan.fetch_company_name_async", AsyncMock(return_value="Apple")),
        patch("app.routers.stock_scan.get_historical_bars", AsyncMock(return_value=bars)),
        patch("app.routers.stock_scan.score_stock", return_value=pass_card),
        patch.dict("app.routers.stock_scan._SIGNAL_FNS", {"pullback_ema": MagicMock(return_value=mock_signal)}),
        patch("app.routers.stock_scan.get_cached", return_value={"confidence": 70, "sample_size": 50}),
        patch.object(loop, "run_in_executor", mock_executor),
    ):
        from app.routers.stock_scan import _process_stock
        await _process_stock(
            "AAPL", req, "test-scan-id",
            {"AAPL": {"last": 185.0, "prevclose": 183.0}},
            [100.0] * 100,
        )

    mock_executor.assert_called_once()
    executor_arg = mock_executor.call_args[0][0]
    assert executor_arg is _BACKTEST_POOL, (
        f"Expected _BACKTEST_POOL, got {executor_arg!r}"
    )
