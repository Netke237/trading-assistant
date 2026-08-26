import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.strategy_engine import pullback_ema_signal, _ema


def _downtrend_pullback_bars():
    """130 bars trending DOWN, final bar bouncing up to just below the 50-EMA (resistance).

    Uses the 50-EMA because that is pullback_ema_signal's ema_period default.
    Pin the last bar's close to fast_val * 0.98 (2% below, well within 4% tolerance).
    Last 4 bars use low volume (30% of base) so the volume contraction gate passes.
    """
    bars = []
    price = 200.0
    base_vol = 1_000_000
    for i in range(130):
        price -= 0.6                      # steady downtrend
        o = price + 0.1; c = price
        bars.append({"open": o, "high": o + 0.5, "low": c - 0.5,
                     "close": c, "volume": base_vol, "time": i})
    # Compute the 50-EMA (default ema_period) on this trend to find resistance level
    closes = [b["close"] for b in bars]
    fast_ma = _ema(closes, 50)
    ema50 = fast_ma[-1]
    # Pin last 4 bars: low volume for contraction check
    for j in range(-4, 0):
        bars[j]["volume"] = int(base_vol * 0.3)
    # Last bar: bounce UP to ~2% below the falling 50-EMA (within 4% tolerance)
    bounce_close = round(ema50 * 0.98, 2)
    base_open = bars[-1]["open"]
    bars[-1] = {"open": base_open, "high": bounce_close + 0.5, "low": base_open - 0.2,
                "close": bounce_close, "volume": int(base_vol * 0.3), "time": 129}
    return bars


def test_pullback_ema_bearish_returns_short_shaped_signal():
    sig = pullback_ema_signal(_downtrend_pullback_bars(), direction="Bearish")
    assert sig is not None
    assert sig.direction == "Bearish"
    assert sig.stop_price > sig.entry_price > sig.target_price


def test_pullback_ema_bullish_unchanged_default():
    import inspect
    assert inspect.signature(pullback_ema_signal).parameters["direction"].default == "Bullish"


# ── breakout_base_signal bearish (C2) ────────────────────────────────────────

from app.services.strategy_engine import breakout_base_signal


def _breakdown_bars():
    bars = []
    price = 100.0
    for i in range(30):                   # tight base around 100
        bars.append({"open": price, "high": price + 0.4, "low": price - 0.4,
                     "close": price, "volume": 1_000_000, "time": i})
    # Breakdown bar: closes below base low on high volume, but not so far below
    # that it outruns the entire measured-move ladder (base_low - height*2 =
    # 98.0 here). A third independent audit round found a bigger breakdown
    # (this fixture originally closed at 96.5) makes breakout_base_signal
    # correctly return None now — the strategy's own thesis is already behind
    # entry, so it refuses to fabricate a fallback target rather than firing
    # with a target that has no connection to the measured move. This test is
    # about Bearish direction support, not that edge case, so it stays inside
    # the ladder's reach.
    bars.append({"open": 99.4, "high": 99.5, "low": 98.5, "close": 99.0,
                 "volume": 3_000_000, "time": 30})
    return bars


def test_breakout_base_bearish_breakdown():
    sig = breakout_base_signal(_breakdown_bars(), direction="Bearish")
    assert sig is not None and sig.direction == "Bearish"
    assert sig.stop_price > sig.entry_price > sig.target_price


# ── ma_crossover_signal bearish (C3) ─────────────────────────────────────────

from app.services.strategy_engine import ma_crossover_signal


def _death_cross_bars():
    bars = []
    price = 150.0
    for i in range(60):
        price += 0.8
        bars.append({"open": price, "high": price + 0.5, "low": price - 0.5,
                     "close": price, "volume": 1_000_000, "time": i})
    for i in range(60, 88):   # 28 down bars — death cross lands at lookback boundary (-10)
        price -= 1.5
        bars.append({"open": price, "high": price + 0.5, "low": price - 0.5,
                     "close": price, "volume": 1_000_000, "time": i})
    return bars


def test_ma_crossover_bearish_death_cross():
    sig = ma_crossover_signal(_death_cross_bars(), direction="Bearish")
    assert sig is not None and sig.direction == "Bearish"
    assert sig.stop_price > sig.entry_price > sig.target_price


# ── mean_reversion_rsi_signal bearish (C4) ───────────────────────────────────

from app.services.strategy_engine import mean_reversion_rsi_signal

def _overbought_downtrend_bars():
    bars = []
    price = 300.0
    for i in range(230):                  # long downtrend (price below 200-SMA)
        price -= 0.5
        bars.append({"open": price, "high": price + 0.4, "low": price - 0.4,
                     "close": price, "volume": 1_000_000, "time": i})
    # sharp 6-bar rally to push RSI > 70 and make it tick down on the last bar
    for j in range(6):
        price += 3.0
        bars.append({"open": price - 2.9, "high": price + 0.3, "low": price - 3.0,
                     "close": price, "volume": 1_000_000, "time": 230 + j})
    bars[-1]["close"] = bars[-1]["open"] - 0.5   # last bar ticks down (RSI falling)
    return bars

def test_mean_reversion_rsi_bearish_overbought():
    sig = mean_reversion_rsi_signal(_overbought_downtrend_bars(),
                                    direction="Bearish", rsi_overbought=70.0)
    assert sig is not None and sig.direction == "Bearish"
    assert sig.stop_price > sig.entry_price > sig.target_price
