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


def _flat_bars(n=400):
    """Genuinely flat/oscillating bars on a strictly increasing date index.

    NOT `_synth_bars(trend=False)`. That helper stamps every bar with
    `2022-01-{(i % 28) + 1}`, so a 400-bar fixture carries only 28 distinct
    dates, ~14 bars deep each. `_bars_to_df` turns `time` into a DatetimeIndex
    and `backtesting.Backtest` silently sorts a non-monotonic index, which
    regroups those bars by day-of-month — and because `price` is a function of
    `i % 7` while the date is a function of `i % 28`, every bar within a date
    group has the SAME price. The sorted series is therefore not an oscillation
    at all but a 28-step staircase, on which pullback_ema really does find two
    pullback-to-EMA setups.

    Those two signals fired on the old exit formula too; they simply never
    became trades, because the old `entry + 2R` target (~53.4) was unreachable
    on a series whose high never exceeds ~50.9, so both positions sat open and
    `# Trades` stayed 0. The strategy-aware target (the prior swing extreme,
    ~50.7) IS reachable, so the same two signals now close as real trades. That
    is the intended consequence of the exit rework, not a regression in the NaN
    guard this test exists to protect — so the fixture is fixed instead of the
    assertion being weakened. With unique sequential dates there is no re-sort,
    the series is the flat oscillation the docstring always claimed, and
    pullback_ema produces zero *signals* (verified), which is a far more robust
    zero-trade precondition than an unreachable target.
    """
    from datetime import date, timedelta
    d0 = date(2022, 1, 3)
    bars = []
    for i in range(n):
        price = 50.0 + (i % 7 - 3) * 0.1
        bars.append({
            "time": (d0 + timedelta(days=i)).isoformat(),
            "open": price * 0.998, "high": price * 1.01,
            "low":  price * 0.99,  "close": price, "volume": 1000 + i,
        })
    return bars


def test_zero_trades_does_not_produce_nan_stats():
    """A window with zero trades makes the underlying `backtesting` library
    return NaN for Win Rate/Sharpe internally (division by zero trades) --
    left unguarded this poisons expectancy (nan*x is nan) and reaches the
    API response, where Python's default JSON encoder emits the bare,
    invalid-JSON token `NaN`. Flat/oscillating bars with no real trend
    reliably produce zero trades for pullback_ema (no pullback-to-EMA setup
    ever fires)."""
    import math
    bars = _flat_bars(400)
    result = run_strategy_backtest(bars, strategy="pullback_ema", direction="Bullish")
    assert result.n_trades == 0, "fixture must produce zero trades for this test to be meaningful"
    assert not math.isnan(result.win_rate)
    assert not math.isnan(result.sharpe)
    assert not math.isnan(result.expectancy)
    assert result.win_rate == 0.0
    assert result.expectancy == 0.0


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
    result = run_strategy_backtest(bars, strategy="ma_crossover", direction="Bullish")
    assert result.n_trades >= 10, "expected ma_crossover on this fixture to produce enough trades to test the real formula"
    # Recompute what the OLD (buggy) formula would have produced from the same
    # aggregate fields, to prove the new expectancy is NOT that.
    wins = round(result.win_rate * result.n_trades)
    losses = result.n_trades - wins
    old_avg_win = abs(result.total_return_pct / wins) if wins > 0 else 0
    old_avg_loss = abs(result.max_drawdown_pct / losses) if losses > 0 else 1
    old_formula_expectancy = round(result.win_rate * old_avg_win - (1 - result.win_rate) * old_avg_loss, 3)
    assert result.expectancy != old_formula_expectancy


def test_min_expectancy_gate_is_applied():
    """_MIN_EXPECTANCY must actually gate passes_gate, not just exist as a
    module constant (Critical finding #6, 2026-07-15 audit)."""
    from app.services import strategy_backtest as sb
    bars = _synth_bars(500, trend=True)
    # min_win_rate=0.0 isolates the expectancy gate: with the win-rate gate
    # neutralized, passes_gate can only be blocked by n_trades or expectancy.
    result = run_strategy_backtest(bars, strategy="ma_crossover", direction="Bullish", min_win_rate=0.0)
    assert result.n_trades >= sb._MIN_TRADES, "expected enough trades to exercise the gate on this fixture"
    assert result.expectancy < sb._MIN_EXPECTANCY, "expected this fixture to produce a losing (negative) expectancy"
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
    mock_signal.targets     = [195.0]
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


def test_below_gate_result_preserves_real_trade_stats():
    """A backtest that produces real trades but fewer than min_trades must NOT
    report n_trades/win_rate/sharpe as 0 — only confidence and passes_gate are
    gated. Callers (WFO train_fold, IS/OOS re-runs) key off `n_trades > 0` to
    decide whether a window traded at all; collapsing a real sub-gate trade
    count down to 0 made those windows indistinguishable from windows with zero
    signals, which silently broke walk-forward optimization on realistic (low)
    trade counts (2026-08 audit)."""
    bars = _synth_bars(400, trend=True)
    below_gate = run_strategy_backtest(bars, strategy="pullback_ema", direction="Bullish",
                                        min_trades=1000)  # unreachable gate
    assert below_gate.n_trades > 0, "fixture must produce at least one real trade for this test to be meaningful"
    assert below_gate.passes_gate is False
    assert below_gate.confidence is None
    assert below_gate.sharpe != 0.0 or below_gate.win_rate != 0.0, (
        "real per-trade stats must survive even when the eligibility gate isn't met"
    )
    assert str(below_gate.n_trades) in below_gate.summary_text


def test_backtest_result_changes_with_params():
    """run_strategy_backtest must actually use the params dict passed to it —
    two materially different param sets on the same bars should not be
    guaranteed to produce identical trade counts (Critical finding #7, 2026-07-15 audit).
    This exercises run_strategy_backtest directly; the router-level fix (threading
    live signal_kwargs into this params argument) is verified by code inspection
    of stock_scan.py's two call sites, which have no isolated per-call unit test
    since they require a full StockAnalysisRequest fixture."""
    bars = _synth_bars(500, trend=True)
    # pullback_ema_signal's real kwarg is `tolerance` (strategy_engine.py:250,
    # default 0.04) — how close price must pull back to the EMA to count as a
    # setup. A near-zero tolerance should fire far fewer (or differently timed)
    # entries than a very loose one.
    tight = run_strategy_backtest(bars, strategy="pullback_ema", direction="Bullish",
                                   params={"tolerance": 0.005})
    loose = run_strategy_backtest(bars, strategy="pullback_ema", direction="Bullish",
                                   params={"tolerance": 0.15})
    # They must not be silently identical, which is what happens if params is
    # never forwarded into the signal function.
    assert tight.n_trades != loose.n_trades or tight.summary_text != loose.summary_text


def test_expectancy_uses_real_per_trade_returns_not_aggregate_stats():
    """H12 regression: expectancy must be derived from stats['_trades']['ReturnPct'],
    not from total_return_pct / max_drawdown_pct — those are portfolio-level aggregates
    that are not trade-additive and can yield negative expectancy for a net-profitable,
    high-win-rate strategy.
    """
    import pandas as pd
    from unittest.mock import patch, MagicMock

    # 15 wins of +1% each, 5 losses of -0.5% each — clearly net-profitable, 75% win rate.
    returns = [0.01] * 15 + [-0.005] * 5
    trades_df = pd.DataFrame({"ReturnPct": returns})

    fake_stats = {
        "# Trades": 20,
        "Win Rate [%]": 75.0,
        "Return [%]": 3.0,           # deliberately small/unrelated to trade returns
        "Max. Drawdown [%]": -18.0,  # deliberately large/unrelated to trade returns
        "Sharpe Ratio": 1.2,
        "_trades": trades_df,
    }

    bars = _synth_bars(400, trend=True)
    with patch("backtesting.Backtest") as MockBacktest:
        mock_bt_instance = MagicMock()
        mock_bt_instance.run.return_value = fake_stats
        MockBacktest.return_value = mock_bt_instance
        result = run_strategy_backtest(bars, strategy="pullback_ema", direction="Bullish")

    # avg_win = mean(1.0) = 1.0; avg_loss = mean(abs(-0.5)) = 0.5
    # expectancy = 0.75*1.0 - 0.25*0.5 = 0.75 - 0.125 = 0.625  (positive!)
    assert result.expectancy > 0, (
        f"Expected positive expectancy for a 75%-win-rate, net-profitable strategy, "
        f"got {result.expectancy}"
    )
    assert result.expectancy == pytest.approx(0.625, abs=0.01)


def test_expectancy_avg_win_loss_independent_of_drawdown_magnitude():
    """A large max_drawdown_pct must not distort expectancy when per-trade returns
    are small and consistent — guards against reintroducing the aggregate-stat bug."""
    import pandas as pd
    from unittest.mock import patch, MagicMock

    returns = [0.002] * 18 + [-0.001] * 2  # 90% win rate, tiny consistent edges
    trades_df = pd.DataFrame({"ReturnPct": returns})
    fake_stats = {
        "# Trades": 20, "Win Rate [%]": 90.0,
        "Return [%]": 0.5, "Max. Drawdown [%]": -40.0,  # huge, unrelated drawdown
        "Sharpe Ratio": 0.8, "_trades": trades_df,
    }
    bars = _synth_bars(400, trend=True)
    with patch("backtesting.Backtest") as MockBacktest:
        mock_bt_instance = MagicMock()
        mock_bt_instance.run.return_value = fake_stats
        MockBacktest.return_value = mock_bt_instance
        result = run_strategy_backtest(bars, strategy="pullback_ema", direction="Bullish")

    assert result.expectancy > 0


def test_commission_reduces_return_versus_zero_commission():
    """A non-zero commission must actually drag down the backtest's reported
    return relative to commission=0.0 — proves the parameter is threaded
    into backtesting.py's Backtest(...) call, not just accepted and ignored."""
    bars = _synth_bars(500, trend=True)
    free = run_strategy_backtest(bars, strategy="ma_crossover", direction="Bullish", commission=0.0)
    costly = run_strategy_backtest(bars, strategy="ma_crossover", direction="Bullish", commission=0.01)
    assert free.n_trades >= 10, "fixture must produce enough trades for this comparison to be meaningful"
    # This fixture drives ma_crossover to near-total ruin (~-99.97% equity) under
    # backtesting.py's default full-equity position sizing (no explicit `size=`
    # passed to self.buy/self.sell in strategy_backtest.py). That means the tiny
    # per-trade equity difference commission introduces can, near the ruin edge,
    # tip a handful of later orders into/out of "insufficient margin" rejection —
    # verified empirically across commission values 0.0001-0.02, none of which
    # reproduce free.n_trades exactly. A wide tolerance still catches the failure
    # mode this test exists to guard against (commission=0.0 being silently
    # ignored, which would leave costly identical to free), while not asserting
    # an invariant the underlying library doesn't actually provide here.
    assert abs(costly.n_trades - free.n_trades) <= 10, (
        "commission must not wildly change which trades fire, only drag on their P&L"
    )
    assert costly.total_return_pct < free.total_return_pct
    assert costly.expectancy < free.expectancy


def test_commission_defaults_to_zero():
    """Backward compatibility: existing callers that don't pass commission=
    must see identical behavior to before this change."""
    bars = _synth_bars(500, trend=True)
    default = run_strategy_backtest(bars, strategy="ma_crossover", direction="Bullish")
    explicit_zero = run_strategy_backtest(bars, strategy="ma_crossover", direction="Bullish", commission=0.0)
    assert default.total_return_pct == explicit_zero.total_return_pct
    assert default.n_trades == explicit_zero.n_trades
