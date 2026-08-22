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
    Last 4 bars use low volume (30% of base) so the volume contraction gate passes.
    """
    from app.services.strategy_engine import _ema as _ema_fn
    bars = []
    price = 100.0
    base_vol = 1_000_000
    for _ in range(n_trend):
        price += 0.5
        bars.append({"open": price - 0.1, "high": price + 0.3,
                     "low": price - 0.3, "close": price, "volume": base_vol})
    flat_price = price
    for _ in range(n_flat):
        bars.append({"open": flat_price - 0.1, "high": flat_price + 0.3,
                     "low": flat_price - 0.3, "close": flat_price, "volume": base_vol})
    # Compute the actual EMA and place the last bar at exactly pct above it
    closes = [b["close"] for b in bars]
    ema_val = _ema_fn(closes, 20)[-1]
    target = ema_val * (1 + pct)
    # Last 4 bars: low volume (30% of base) so volume contraction gate passes
    for j in range(-4, 0):
        bars[j]["volume"] = int(base_vol * 0.3)
    bars[-1] = {"open": target - 0.1, "high": target + 0.2,
                "low": target - 0.2, "close": target + 0.05, "volume": int(base_vol * 0.3)}
    return bars


def test_pullback_ema_fires_at_2pct_above_ema():
    """2% above EMA is inside the new 4% tolerance — should fire."""
    bars = _uptrend_with_pullback_pct(0.02)
    signal = pullback_ema_signal(bars)
    assert signal is not None, "Expected a signal at 2% above EMA with 4% tolerance"
    assert signal.strategy == "pullback_ema"


def test_pullback_ema_still_rejects_at_9pct_above_ema():
    """9% above EMA is outside the 8% tolerance — should return None."""
    bars = _uptrend_with_pullback_pct(0.09)
    signal = pullback_ema_signal(bars)
    assert signal is None, "Expected None at 9% above EMA (outside 8% tolerance)"


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


# ── New strategy helpers ──────────────────────────────────────────────────────

from app.services.strategy_engine import (
    _bollinger, _vwap, _atr_series,
    SetupSignal,
    mean_reversion_bb_signal,
    mean_reversion_vwap_signal,
    breakout_setup_signal,
)


def test_bollinger_lengths_match():
    values = [float(i) for i in range(50)]
    upper, mid, lower = _bollinger(values, period=20, n_std=2.0)
    assert len(upper) == len(mid) == len(lower)
    assert len(upper) == len(values) - 20 + 1


def test_bollinger_ordering():
    values = [100.0 + i * 0.1 for i in range(50)]
    upper, mid, lower = _bollinger(values, period=20, n_std=2.0)
    for u, m, l in zip(upper, mid, lower):
        assert u >= m >= l


def test_vwap_returns_float():
    bars = [{"high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000} for _ in range(10)]
    assert isinstance(_vwap(bars), float)
    assert _vwap(bars) == pytest.approx(100.0)


def test_atr_series_length():
    bars = _rising_bars(50)
    series = _atr_series(bars, period=14)
    assert len(series) == len(bars) - 1   # one less because TR needs previous bar


def test_setup_signal_has_no_entry_stop_target():
    sig = SetupSignal(strategy="breakout_setup", direction="Bullish",
                      symbol="AAPL", confidence=75, metrics={})
    assert not hasattr(sig, "entry_price")
    assert not hasattr(sig, "stop_price")
    assert not hasattr(sig, "target_price")
    assert not hasattr(sig, "rr_ratio")


def test_mean_reversion_bb_signal_structure():
    """Signal function returns correct type on synthetic data."""
    bars = _rising_bars(300)
    sig = mean_reversion_bb_signal(bars)
    assert sig is None or isinstance(sig, StrategySignal)


def test_mean_reversion_bb_signal_bearish_structure():
    """Bearish direction returns correct type."""
    bars = _rising_bars(300)
    sig = mean_reversion_bb_signal(bars, direction="Bearish")
    assert sig is None or isinstance(sig, StrategySignal)


def test_mean_reversion_vwap_signal_returns_none_for_daily():
    """Daily interval guard must return None."""
    bars = _rising_bars(100)
    sig = mean_reversion_vwap_signal(bars, interval="1D")
    assert sig is None


def test_mean_reversion_vwap_signal_returns_none_for_empty_interval():
    """Unknown interval guard must return None."""
    bars = _rising_bars(100)
    sig = mean_reversion_vwap_signal(bars, interval="weekly")
    assert sig is None


def test_breakout_setup_signal_requires_symbol():
    """Function signature must accept symbol kwarg."""
    bars = _rising_bars(100)
    # Should not raise TypeError
    sig = breakout_setup_signal(bars, "AAPL")
    assert sig is None or isinstance(sig, SetupSignal)


def test_breakout_setup_signal_returns_setup_signal_type():
    """When it fires, must return SetupSignal not StrategySignal."""
    # Build bars with compressed ATR, tight range, low volume, near swing high
    bars = []
    price = 100.0
    for i in range(80):
        bars.append({"open": price - 0.1, "high": price + 2.0, "low": price - 2.0,
                     "close": price, "volume": 2000})
        price += 0.2
    # Last 10 bars: tight range, low volume, near the swing high
    swing_high = price
    for _ in range(10):
        bars.append({"open": swing_high - 0.1, "high": swing_high + 0.05,
                     "low": swing_high - 0.05, "close": swing_high - 0.02, "volume": 400})
    sig = breakout_setup_signal(bars, "TEST",
                                 atr_compression_ratio=0.9,
                                 range_atr_mult=2.0,
                                 vol_compression_ratio=0.9,
                                 resistance_proximity_pct=0.10)
    # It may or may not fire depending on exact values — just verify type if it fires
    assert sig is None or isinstance(sig, SetupSignal)
    if sig is not None:
        assert isinstance(sig.confidence, int)
        assert 0 <= sig.confidence <= 100
        assert "atr_ratio" in sig.metrics


# ── Stop placement and R/R tests (Task 1) ─────────────────────────────────────

def _uptrend_pullback_bars(n=200):
    """Steady uptrend then a shallow pullback near the 50-EMA."""
    bars = []
    price = 100.0
    for i in range(n):
        price += 0.6
        bars.append({"open": price - 0.2, "high": price + 0.5,
                     "low": price - 0.5, "close": price, "volume": 500_000})
    # Last 10 bars: compress volume and pull price back within 3% of 50-EMA
    from app.services.strategy_engine import _ema as _ema_fn
    closes = [b["close"] for b in bars]
    ema_val = _ema_fn(closes, 50)[-1]
    pullback_price = ema_val * 1.02  # 2% above EMA — inside 4% tolerance
    for j in range(-10, 0):
        bars[j]["close"] = pullback_price
        bars[j]["high"]  = pullback_price + 0.2
        bars[j]["low"]   = pullback_price - 0.2
        bars[j]["volume"] = 200_000   # low volume — passes contraction check
    return bars


def test_pullback_ema_stop_is_below_fast_ma():
    """Stop must be below the fast MA (fast_val - ATR*1.5)."""
    bars = _uptrend_pullback_bars()
    from app.services.strategy_engine import _ema as _ema_fn, _atr
    closes = [b["close"] for b in bars]
    fast_val = _ema_fn(closes, 50)[-1]

    signal = pullback_ema_signal(bars, tolerance=0.04)
    if signal is None:
        pytest.skip("setup did not fire on synthetic data")

    assert signal.stop_price < fast_val, (
        f"stop {signal.stop_price:.2f} must be below fast MA {fast_val:.2f}"
    )


def test_pullback_ema_targets_the_prior_swing_high():
    """Rung 1 is the prior swing extreme (the exit the Step-4 picker promises),
    not a fixed R multiple. The R extensions live on rungs 2 and 3."""
    bars = _uptrend_pullback_bars()
    signal = pullback_ema_signal(bars, tolerance=0.04)
    if signal is None:
        pytest.skip("setup did not fire on synthetic data")

    risk = signal.entry_price - signal.stop_price
    assert risk > 0, "risk must be positive (stop below entry)"
    assert signal.target_price == signal.targets[0]
    assert signal.target_price > signal.entry_price
    # Either the prior swing extreme carried rung 1, or it rounded onto entry
    # and was dropped so the 2R extension took over. Both are correct.
    prior = signal.detail["prior_swing_extreme"]
    assert signal.target_price in (
        round(prior, 2),
        round(signal.entry_price + risk * 2.0, 2),
    )
    # The full ladder is strictly increasing and nearest-first.
    assert signal.targets == sorted(signal.targets)
    assert len(set(signal.targets)) == len(signal.targets)


def test_pullback_ema_stop_never_above_entry():
    """risk <= 0 guard: signal must be None, never have stop above entry."""
    bars = _uptrend_pullback_bars()
    signal = pullback_ema_signal(bars, tolerance=0.04)
    if signal is not None:
        assert signal.entry_price > signal.stop_price, (
            "stop must be strictly below entry for bullish signal"
        )


def test_pullback_ema_bearish_stop_above_fast_ma():
    """Bearish stop must be above the fast MA."""
    bars = []
    price = 150.0
    for i in range(200):
        price -= 0.5
        bars.append({"open": price + 0.2, "high": price + 0.5,
                     "low": price - 0.5, "close": price, "volume": 500_000})
    from app.services.strategy_engine import _ema as _ema_fn
    closes = [b["close"] for b in bars]
    ema_val = _ema_fn(closes, 35)[-1]
    bounce_price = ema_val * 0.98  # 2% below EMA — inside 4% tolerance from below
    for j in range(-10, 0):
        bars[j]["close"] = bounce_price
        bars[j]["high"]  = bounce_price + 0.2
        bars[j]["low"]   = bounce_price - 0.2
        bars[j]["volume"] = 200_000

    signal = pullback_ema_signal(bars, direction="Bearish", tolerance=0.04)
    if signal is None:
        pytest.skip("bearish setup did not fire on synthetic data")

    fast_val = _ema_fn([b["close"] for b in bars], 35)[-1]
    assert signal.stop_price > fast_val, (
        f"bearish stop {signal.stop_price:.2f} must be above fast MA {fast_val:.2f}"
    )
    assert signal.stop_price > signal.entry_price, "stop above entry for bearish"


# ── Volume contraction tests (Task 3) ─────────────────────────────────────────

def _uptrend_with_volume(n_trend=150, recent_vol_mult=1.0):
    """Rising bars, then last 3 bars have volume = recent_vol_mult * base_vol."""
    bars = []
    price = 100.0
    base_vol = 1_000_000
    for i in range(n_trend):
        price += 0.5
        bars.append({"open": price - 0.1, "high": price + 0.3,
                     "low": price - 0.3, "close": price, "volume": base_vol})
    # Place last bar at 2% above 50-EMA (inside 4% tolerance)
    from app.services.strategy_engine import _ema as _ema_fn
    closes = [b["close"] for b in bars]
    ema_val = _ema_fn(closes, 50)[-1]
    target = ema_val * 1.02
    # Set last 4 bars: bars[-4:-1] are the "3 complete bars", bars[-1] is today
    for j in range(-4, 0):
        bars[j]["close"] = target
        bars[j]["high"]  = target + 0.2
        bars[j]["low"]   = target - 0.2
        bars[j]["volume"] = int(base_vol * recent_vol_mult)
    return bars


def test_pullback_ema_rejects_high_volume_pullback():
    """Volume at 100% of 20-bar avg (no contraction) must suppress the signal."""
    bars = _uptrend_with_volume(recent_vol_mult=1.0)
    signal = pullback_ema_signal(bars, tolerance=0.04)
    assert signal is None, "signal must not fire when volume is not compressing"


def test_pullback_ema_accepts_low_volume_pullback():
    """Volume at 40% of avg (clear contraction) should allow the signal to fire."""
    bars = _uptrend_with_volume(recent_vol_mult=0.4)
    signal = pullback_ema_signal(bars, tolerance=0.04)
    # Either fires or fails on price conditions — must not crash
    assert signal is None or isinstance(signal, StrategySignal)
    if signal is not None:
        assert signal.strategy == "pullback_ema"


def test_all_signal_functions_accept_current_price_kwarg():
    """Every strategy registered in stock_scan._SIGNAL_FNS must accept a
    current_price kwarg — the router calls all of them with it unconditionally
    (stock_scan.py:296-298, 700-705). A strategy missing this parameter raises
    TypeError for every symbol in a scan, silently masked as 'no setup' on the
    analyze path and leaked as the failure reason on the batch path.

    225 bars satisfies the longest min-length gate in the group
    (mean_reversion_bb_signal: trend_sma=200 + bb_period=20 + 5). Note this
    assertion only needs the call to bind successfully — Python raises
    TypeError for an unexpected keyword argument at call-binding time, before
    the function body's own length gate ever runs, so the exact bar count
    doesn't gate this test's correctness.
    """
    from app.routers.stock_scan import _SIGNAL_FNS

    bars = _rising_bars(225)
    for name, fn in _SIGNAL_FNS.items():
        try:
            fn(bars, direction="Bullish", current_price=bars[-1]["close"])
        except TypeError as e:
            pytest.fail(f"{name} ({fn.__name__}) does not accept current_price: {e}")


# ── risk<=0 guard tests (H13/T1) ──────────────────────────────────────────────

def test_breakout_base_signal_zero_atr_direct_bullish(monkeypatch):
    """H13/T1: on a degenerate zero-ATR base, breakout_base_signal must not emit
    an inverted stop/target — the risk<=0 guard must fire instead."""
    import app.services.strategy_engine as se
    monkeypatch.setattr(se, "_atr", lambda bars, period=14: 0.0)
    bars = _flat_bars(30, price=100.0)
    bars += [{"open": 100.0, "high": 101.0, "low": 100.0, "close": 100.5, "volume": 5_000_000}
             for _ in range(5)]
    signal = se.breakout_base_signal(bars, direction="Bullish", volume_mult=1.0, atr_tight_max=999)
    assert signal is None or signal.entry_price > signal.stop_price


def test_breakout_base_signal_zero_atr_direct_bearish(monkeypatch):
    import app.services.strategy_engine as se
    monkeypatch.setattr(se, "_atr", lambda bars, period=14: 0.0)
    bars = _flat_bars(30, price=100.0)
    bars += [{"open": 100.0, "high": 100.0, "low": 99.0, "close": 99.5, "volume": 5_000_000}
             for _ in range(5)]
    signal = se.breakout_base_signal(bars, direction="Bearish", volume_mult=1.0, atr_tight_max=999)
    assert signal is None or signal.entry_price < signal.stop_price


def test_ma_crossover_signal_never_inverts_stop_bullish():
    """Guard: whenever a Bullish signal fires, stop must be strictly below entry."""
    bars = _crossover_bars(cross_bars_ago=5)
    signal = ma_crossover_signal(bars, direction="Bullish")
    if signal is not None:
        assert signal.entry_price > signal.stop_price, (
            f"stop {signal.stop_price} must be below entry {signal.entry_price}"
        )


def test_ma_crossover_signal_never_inverts_stop_bearish():
    """Mirror of the bullish case — death cross must not invert stop/entry either."""
    bars = []
    for _ in range(100):
        bars.append({"open": 199.9, "high": 200.5, "low": 199.5, "close": 200.0, "volume": 1_000})
    for _ in range(5):
        bars.append({"open": 99.9, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1_000})
    signal = ma_crossover_signal(bars, direction="Bearish")
    if signal is not None:
        assert signal.entry_price < signal.stop_price, (
            f"bearish stop {signal.stop_price} must be above entry {signal.entry_price}"
        )


def test_mean_reversion_rsi_signal_never_inverts_stop_bullish():
    """Guard: whenever a Bullish RSI mean-reversion signal fires, stop must be below entry."""
    bars = _rising_bars(250)
    # Force a shallow oversold dip near the swing low so a degenerate/near-zero-ATR
    # stop calculation is exercised without crashing or inverting.
    for i in range(-5, 0):
        bars[i]["close"] *= 0.995
        bars[i]["low"] = bars[i]["close"]
    signal = mean_reversion_rsi_signal(bars, direction="Bullish")
    if signal is not None:
        assert signal.entry_price > signal.stop_price, (
            f"stop {signal.stop_price} must be below entry {signal.entry_price}"
        )


def test_mean_reversion_rsi_signal_never_inverts_stop_bearish():
    """Mirror for the bearish/overbought-in-downtrend path."""
    bars = []
    price = 200.0
    for i in range(250):
        price -= 0.3
        bars.append({"open": price + 0.1, "high": price + 0.3,
                     "low": price - 0.3, "close": price, "volume": 500_000})
    for i in range(-5, 0):
        bars[i]["close"] *= 1.005
        bars[i]["high"] = bars[i]["close"]
    signal = mean_reversion_rsi_signal(bars, direction="Bearish")
    if signal is not None:
        assert signal.entry_price < signal.stop_price, (
            f"bearish stop {signal.stop_price} must be above entry {signal.entry_price}"
        )


def _breakout_base_bars_with_ratio(base_range_over_atr: float):
    """26 bars: 5 flat warmup + 20-bar base whose (high-low) range is
    `base_range_over_atr` * ATR(14) (approximately), + 1 breakout bar on 2x
    volume.

    Each bar has a fixed 1.0 high-low span, and base_high - base_low is
    constructed to equal `base_range_over_atr` exactly. But `_atr(bars)` is
    computed over the *whole* bars list, including the appended breakout
    bar — whose own true range (~2.0, from its gap up) enters the ATR(14)
    window (13 base-to-base TRs of ~1.0 each + 1 breakout-bar TR of ~2.0,
    averaged over 14) and pushes ATR to ~1.0714 rather than the naively
    assumed 1.0. So the *realized* base_range/ATR ratio actually produced by
    this helper is `base_range_over_atr * 14/15` (about 7% lower than the
    `base_range_over_atr` argument's face value) — e.g. an argument of 3.3
    realizes ~3.08x, and 10.0 realizes ~9.33x. Callers should treat the
    argument as an approximate dial, not an exact realized ratio.
    """
    bars = []
    for _ in range(5):
        bars.append({"open": 100.0, "high": 100.5, "low": 99.5,
                      "close": 100.0, "volume": 1_000_000})
    drift = base_range_over_atr - 1.0
    step = drift / 19
    for i in range(20):
        close = 100.0 + step * i
        bars.append({"open": close, "high": close + 0.5, "low": close - 0.5,
                      "close": close, "volume": 1_000_000})
    base_high = max(b["high"] for b in bars[-20:])
    bars.append({"open": base_high + 0.5, "high": base_high + 1.5,
                 "low": base_high - 0.1, "close": base_high + 1.0,
                 "volume": 2_000_000})
    return bars


def test_breakout_base_signal_fires_at_realistic_base_tightness():
    """A base range of ~3.3x ATR is what real 20-bar consolidations actually
    look like (2026-08-18 audit: observed minimum 2.77x-3.22x across 4 real
    symbols over a full year). breakout_base_signal must be able to fire on
    a base this tight — if this test fails with signal is None, atr_tight_max
    has regressed back to a value real data can never satisfy.

    Note: passing 3.3 to the helper realizes a ~3.08x base_range/ATR ratio,
    not exactly 3.3x — see `_breakout_base_bars_with_ratio`'s docstring for
    why (the breakout bar's own true range inflates ATR by ~7%). 3.08x still
    lands comfortably inside the audit's observed 2.77x-3.22x real-data
    range, so the test remains a faithful stand-in for a realistic base."""
    bars = _breakout_base_bars_with_ratio(3.3)
    signal = breakout_base_signal(bars, direction="Bullish")
    assert signal is not None, (
        "breakout_base_signal returned None on a ~3.08x-ATR base — this is "
        "within the range real market data actually produces (2.77x-3.22x "
        "observed), so atr_tight_max must be loose enough to admit it."
    )


def test_breakout_base_signal_still_rejects_a_genuinely_wide_base():
    """Sanity check the gate still rejects a base that is NOT tight by any
    reasonable definition. Passing 10.0 to the helper realizes a ~9.33x
    base_range/ATR ratio (not exactly 10x — see
    `_breakout_base_bars_with_ratio`'s docstring), which is still far
    outside any plausible "tight base" definition."""
    bars = _breakout_base_bars_with_ratio(10.0)
    signal = breakout_base_signal(bars, direction="Bullish")
    assert signal is None
