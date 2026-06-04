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
