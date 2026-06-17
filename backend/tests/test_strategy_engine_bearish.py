import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.strategy_engine import pullback_ema_signal, _ema


def _downtrend_pullback_bars():
    """130 bars trending DOWN, final bar bouncing up to just below the 50-EMA (resistance).

    We compute the 50-EMA on the base trend first, then pin the last bar's close to
    fast_val * 0.96 so the bearish tolerance check (0–8% below fast MA) passes.
    """
    bars = []
    price = 200.0
    for i in range(130):
        price -= 0.6                      # steady downtrend
        o = price + 0.1; c = price
        bars.append({"open": o, "high": o + 0.5, "low": c - 0.5,
                     "close": c, "volume": 1_000_000, "time": i})
    # Compute the 50-EMA on this trend to find resistance level
    closes = [b["close"] for b in bars]
    fast_ma = _ema(closes, 50)
    ema50 = fast_ma[-1]
    # Pin the last bar: bounce UP to ~4% below the falling 50-EMA (within 8% tolerance)
    bounce_close = round(ema50 * 0.96, 2)
    base_open = bars[-1]["open"]
    bars[-1] = {"open": base_open, "high": bounce_close + 0.5, "low": base_open - 0.2,
                "close": bounce_close, "volume": 1_000_000, "time": 129}
    return bars


def test_pullback_ema_bearish_returns_short_shaped_signal():
    sig = pullback_ema_signal(_downtrend_pullback_bars(), direction="Bearish")
    assert sig is not None
    assert sig.direction == "Bearish"
    assert sig.stop_price > sig.entry_price > sig.target_price


def test_pullback_ema_bullish_unchanged_default():
    import inspect
    assert inspect.signature(pullback_ema_signal).parameters["direction"].default == "Bullish"
