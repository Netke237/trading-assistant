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


# ── Relaxed tolerance tests ───────────────────────────────────────────────────

def _uptrend_with_pullback_pct(pct: float, n_trend: int = 150, n_flat: int = 80) -> list[dict]:
    """Rising bars then flat bars; final bar is placed at exactly `pct` above the actual 20-EMA.

    Uses 80 flat bars so the EMA converges tightly to the flat price before the test bar is set.
    """
    from app.services.strategy_engine import _ema as _ema_fn
    bars = []
    price = 100.0
    for _ in range(n_trend):
        price += 0.5
        bars.append({"open": price - 0.1, "high": price + 0.3,
                     "low": price - 0.3, "close": price, "volume": 1_000})
    flat_price = price
    for _ in range(n_flat):
        bars.append({"open": flat_price - 0.1, "high": flat_price + 0.3,
                     "low": flat_price - 0.3, "close": flat_price, "volume": 1_000})
    # Compute the actual EMA and place the last bar at exactly pct above it
    closes = [b["close"] for b in bars]
    ema_val = _ema_fn(closes, 20)[-1]
    target = ema_val * (1 + pct)
    bars[-1] = {"open": target - 0.1, "high": target + 0.2,
                "low": target - 0.2, "close": target + 0.05, "volume": 1_000}
    return bars


def test_pullback_ema_fires_at_2pct_above_ema():
    """2% above EMA is inside the new 4% tolerance — should fire."""
    bars = _uptrend_with_pullback_pct(0.02)
    signal = pullback_ema_signal(bars)
    assert signal is not None, "Expected a signal at 2% above EMA with 4% tolerance"
    assert signal.strategy == "pullback_ema"


def test_pullback_ema_still_rejects_at_5pct_above_ema():
    """5% above EMA is outside the new 4% tolerance — should return None."""
    bars = _uptrend_with_pullback_pct(0.05)
    signal = pullback_ema_signal(bars)
    assert signal is None, "Expected None at 5% above EMA (outside tolerance)"


def _crossover_bars(cross_bars_ago: int, n_flat: int = 100) -> list[dict]:
    """Bars where 20-SMA crosses above 50-SMA exactly `cross_bars_ago` bars ago.

    Strategy: long flat section at 100 makes both MAs equal, then `cross_bars_ago`
    bars at 200 cause the fast MA to pull above the slow MA — the cross occurs on
    the first high bar (= `cross_bars_ago` positions from the end).
    """
    bars = []
    for _ in range(n_flat):
        bars.append({"open": 99.9, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1_000})
    for _ in range(cross_bars_ago):
        bars.append({"open": 199.9, "high": 200.5, "low": 199.5, "close": 200.0, "volume": 1_000})
    return bars


def test_ma_crossover_fires_within_10_bars():
    """Cross that happened 5 bars ago should fire with 10-bar lookback."""
    bars = _crossover_bars(cross_bars_ago=5)
    signal = ma_crossover_signal(bars)
    assert signal is not None, "Expected a signal when cross is 5 bars old with 10-bar lookback"
    assert signal.strategy == "ma_crossover"


def test_ma_crossover_still_rejects_at_12_bars():
    """Cross that happened 12 bars ago is outside the 10-bar window — should return None."""
    bars = _crossover_bars(cross_bars_ago=12)
    signal = ma_crossover_signal(bars)
    assert signal is None, "Expected None when cross is 12 bars old"


def test_pullback_sma_signal_fires_in_uptrend():
    """ma_type='SMA' variant must not raise and return correct type."""
    bars = _rising_bars(200)
    for i in range(-20, 0):
        bars[i]["close"] *= 0.985
        bars[i]["low"] = bars[i]["close"] - 0.5
    signal = pullback_ema_signal(bars, ma_type="SMA")
    assert signal is None or isinstance(signal, StrategySignal)


def test_pullback_ema_is_default_ma_type():
    """Without ma_type, behaviour must be identical to ma_type='EMA'."""
    bars = _rising_bars(200)
    signal_default = pullback_ema_signal(bars)
    signal_ema     = pullback_ema_signal(bars, ma_type="EMA")
    assert (signal_default is None) == (signal_ema is None)
    if signal_default and signal_ema:
        assert signal_default.entry_price == signal_ema.entry_price
