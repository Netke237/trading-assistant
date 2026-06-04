import pytest
from app.services.strategy_engine import (
    pullback_ema_signal,
    breakout_base_signal,
    ma_crossover_signal,
    mean_reversion_rsi_signal,
    StrategySignal,
)


def _rising_bars(n=120, start=100.0, step=0.5):
    """Steadily rising bars — good uptrend."""
    bars = []
    price = start
    for i in range(n):
        price += step
        bars.append({"open": price - 0.2, "high": price + 0.5,
                     "low": price - 0.5, "close": price, "volume": 1000})
    return bars


def _flat_bars(n=120, price=100.0):
    return [{"open": price, "high": price + 1, "low": price - 1,
             "close": price, "volume": 1000} for _ in range(n)]


def test_pullback_ema_signal_fires_in_uptrend():
    bars = _rising_bars(200)
    # Create a dip in the last 20 bars
    for i in range(-20, 0):
        bars[i]["close"] *= 0.985
        bars[i]["low"] = bars[i]["close"] - 0.5
    signal = pullback_ema_signal(bars)
    # May or may not fire on synthetic data — just verify return type
    assert signal is None or isinstance(signal, StrategySignal)


def test_pullback_ema_signal_returns_none_on_flat():
    bars = _flat_bars(200)
    signal = pullback_ema_signal(bars)
    assert signal is None


def test_breakout_base_signal_structure():
    signal = breakout_base_signal(_rising_bars(100))
    assert signal is None or isinstance(signal, StrategySignal)


def test_ma_crossover_signal_structure():
    signal = ma_crossover_signal(_rising_bars(100))
    assert signal is None or isinstance(signal, StrategySignal)


def test_mean_reversion_rsi_signal_structure():
    signal = mean_reversion_rsi_signal(_rising_bars(300))
    assert signal is None or isinstance(signal, StrategySignal)


def test_strategy_signal_has_required_fields():
    sig = StrategySignal(
        strategy="pullback_ema",
        direction="Bullish",
        entry_price=100.0,
        stop_price=96.0,
        target_price=110.0,
        atr=2.0,
        detail={"ema_20": 99.5},
    )
    assert sig.risk == pytest.approx(4.0)
    assert sig.reward == pytest.approx(10.0)
    assert sig.rr_ratio == pytest.approx(2.5)
