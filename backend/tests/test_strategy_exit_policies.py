"""Exit-ladder helper and per-strategy exit-thesis tests."""
from __future__ import annotations

import pytest

from app.services.strategy_engine import _build_target_ladder


def test_ladder_puts_the_primary_first_and_sorts_extensions_bullish():
    out = _build_target_ladder(entry=100, stop=95, direction="Bullish",
                               primary=105, extensions=[120, 110], fallback_mult=2.0)
    assert out == [105.0, 110.0, 120.0]


def test_ladder_puts_the_primary_first_and_sorts_extensions_bearish():
    out = _build_target_ladder(entry=100, stop=105, direction="Bearish",
                               primary=95, extensions=[80, 90], fallback_mult=2.0)
    assert out == [95.0, 90.0, 80.0]


def test_ladder_never_reorders_a_nearer_extension_ahead_of_the_primary():
    """THE regression this design exists for: a generic 2R extension nearer than
    the strategy's own objective must be dropped, not promoted to target_price."""
    out = _build_target_ladder(entry=100, stop=99, direction="Bullish",
                               primary=110, extensions=[102, 115], fallback_mult=2.0)
    assert out[0] == 110.0
    assert 102.0 not in out
    assert out == [110.0, 115.0]


def test_ladder_never_reorders_a_nearer_extension_ahead_of_the_primary_bearish():
    out = _build_target_ladder(entry=100, stop=101, direction="Bearish",
                               primary=90, extensions=[98, 85], fallback_mult=2.0)
    assert out == [90.0, 85.0]


def test_ladder_drops_wrong_side_rungs():
    out = _build_target_ladder(entry=100, stop=95, direction="Bullish",
                               primary=99, extensions=[110], fallback_mult=2.0)
    assert out == [110.0]


def test_ladder_keeps_a_primary_inside_half_an_r_by_default():
    """No R-relative floor by default — a squeezed mid-band a few cents above
    entry is the strategy's own objective and is measured honestly."""
    out = _build_target_ladder(entry=100, stop=95, direction="Bullish",
                               primary=100.4, extensions=[112], fallback_mult=2.0)
    assert out == [100.4, 112.0]


def test_ladder_min_rung_r_drops_rungs_inside_the_floor_when_asked():
    # risk = 5, min_rung_r 0.5 -> floor at 102.5; 101 is inside it.
    out = _build_target_ladder(entry=100, stop=95, direction="Bullish",
                               primary=101, extensions=[112], fallback_mult=2.0,
                               min_rung_r=0.5)
    assert out == [112.0]


def test_ladder_falls_back_when_every_rung_is_dropped():
    out = _build_target_ladder(entry=100, stop=95, direction="Bullish",
                               primary=None, extensions=[90, float("nan"), 0],
                               fallback_mult=2.0)
    assert out == [110.0]     # entry + 2R


def test_ladder_fallback_respects_the_minimum_fallback_floor():
    out = _build_target_ladder(entry=100, stop=95, direction="Bullish",
                               primary=None, extensions=[], fallback_mult=0.0)
    assert out == [102.5]     # max(fallback_mult, 0.5R)


def test_ladder_handles_zero_atr_derived_rungs():
    # atr == 0 collapses every ATR rung onto entry; all are dropped.
    entry, atr = 100.0, 0.0
    out = _build_target_ladder(entry=entry, stop=95, direction="Bullish",
                               primary=entry + atr * 3.0,
                               extensions=[entry + atr * 4.5, entry + atr * 6.0],
                               fallback_mult=2.0)
    assert out == [110.0]


def test_ladder_dedupes_near_identical_rungs():
    out = _build_target_ladder(entry=100, stop=95, direction="Bullish",
                               primary=110.0, extensions=[110.05, 120.0],
                               fallback_mult=2.0)
    assert out == [110.0, 120.0]


def test_ladder_caps_at_three_rungs():
    out = _build_target_ladder(entry=100, stop=95, direction="Bullish",
                               primary=105, extensions=[110, 115, 120, 125],
                               fallback_mult=2.0)
    assert len(out) == 3


def test_ladder_first_rung_always_satisfies_entry_side_gate():
    from app.services.strategy_backtest import _entry_side
    for direction, stop in (("Bullish", 95.0), ("Bearish", 105.0)):
        out = _build_target_ladder(entry=100.0, stop=stop, direction=direction,
                                   primary=None, extensions=[], fallback_mult=2.0)
        assert _entry_side(direction, entry=100.0, sl=stop, tp=out[0]) is not None


def test_ladder_drops_a_rung_that_rounds_onto_entry():
    out = _build_target_ladder(entry=100.0, stop=95.0, direction="Bullish",
                               primary=100.001, extensions=[], fallback_mult=2.0)
    assert out == [110.0]


def test_ladder_returns_empty_on_zero_risk():
    assert _build_target_ladder(entry=100, stop=100, direction="Bullish",
                                primary=110, extensions=[], fallback_mult=2.0) == []


# ── pullback_ema ──────────────────────────────────────────────────────────────

def test_pullback_ema_ladder_is_monotonic_and_starts_at_target_price():
    from tests.test_strategy_engine import _uptrend_pullback_bars
    from app.services.strategy_engine import pullback_ema_signal

    # _uptrend_pullback_bars() is deterministic synthetic data, not randomized
    # input — same reasoning as the ma_crossover test below: a `pytest.skip`
    # here would pass while proving nothing.
    sig = pullback_ema_signal(_uptrend_pullback_bars(), tolerance=0.04)
    assert sig is not None, "setup must fire on this deterministic fixture"
    assert sig.targets and sig.targets[0] == sig.target_price
    assert all(b > a for a, b in zip(sig.targets, sig.targets[1:]))
    assert all(t > sig.entry_price for t in sig.targets)


def _downtrend_pullback_bars(n=200):
    """Mirror of `_uptrend_pullback_bars`: steady downtrend, then a shallow
    bounce near the 50-EMA from below."""
    bars = []
    price = 300.0
    for _ in range(n):
        price -= 0.6
        bars.append({"open": price + 0.2, "high": price + 0.5,
                     "low": price - 0.5, "close": price, "volume": 500_000})
    from app.services.strategy_engine import _ema as _ema_fn
    closes = [b["close"] for b in bars]
    ema_val = _ema_fn(closes, 50)[-1]
    bounce_price = ema_val * 0.98  # 2% below EMA — inside 4% tolerance
    for j in range(-10, 0):
        bars[j]["close"] = bounce_price
        bars[j]["high"]  = bounce_price + 0.2
        bars[j]["low"]   = bounce_price - 0.2
        bars[j]["volume"] = 200_000
    return bars


def test_pullback_ema_ladder_is_monotonic_and_starts_at_target_price_bearish():
    """Bearish mirror — the Bullish-only pullback_ema thesis tests never
    exercised this branch, and breakout_base's real stop-anchor bug (fixed
    separately) lived in exactly this kind of untested Bearish half."""
    from app.services.strategy_engine import pullback_ema_signal

    sig = pullback_ema_signal(_downtrend_pullback_bars(), tolerance=0.04, direction="Bearish")
    assert sig is not None, "setup must fire on this deterministic fixture"
    assert sig.targets and sig.targets[0] == sig.target_price
    assert all(b < a for a, b in zip(sig.targets, sig.targets[1:]))
    assert all(t < sig.entry_price for t in sig.targets)


# ── breakout_base ─────────────────────────────────────────────────────────────

def _flat_base_then_breakout(base_high: float = 100.0, base_low: float = 96.0) -> list[dict]:
    """25 bars of a tight base, then a high-volume close above it."""
    bars = []
    mid = (base_high + base_low) / 2
    for _ in range(25):
        bars.append({"open": mid, "high": base_high, "low": base_low,
                     "close": mid, "volume": 1_000_000})
    bars.append({"open": base_high, "high": base_high + 2, "low": base_high - 0.5,
                 "close": base_high + 1, "volume": 5_000_000})
    return bars


def test_breakout_base_rung_one_is_the_measured_move_off_the_base_high():
    from app.services.strategy_engine import breakout_base_signal

    bars = _flat_base_then_breakout()
    sig = breakout_base_signal(bars, base_lookback=20, atr_tight_max=99.0, volume_mult=1.5)
    assert sig is not None, "fixture must fire — a skipping thesis test proves nothing"
    height = sig.detail["base_height"]
    anchor = sig.detail["measured_move_anchor"]
    assert height == pytest.approx(4.0, abs=0.01)
    assert sig.target_price == pytest.approx(round(anchor + height, 2), abs=0.01)
    assert sig.targets[0] == sig.target_price
    # The two outward extensions survive: anchor + 1.5H and anchor + 2H.
    assert sig.targets == [round(anchor + height, 2),
                           round(anchor + height * 1.5, 2),
                           round(anchor + height * 2.0, 2)]


def test_breakout_base_survives_a_zero_height_base():
    """A perfectly flat base (base_high == base_low) must not produce a target
    at the breakout level itself — _entry_side would reject it and the strategy
    would silently stop trading."""
    from app.services.strategy_engine import breakout_base_signal
    from app.services.strategy_backtest import _entry_side

    bars = _flat_base_then_breakout(base_high=100.0, base_low=100.0)
    sig = breakout_base_signal(bars, base_lookback=20, atr_tight_max=99.0, volume_mult=1.5)
    assert sig is not None, "fixture must fire — a skipping thesis test proves nothing"
    assert sig.detail["base_height"] == 0.0
    assert _entry_side("Bullish", entry=sig.entry_price,
                       sl=sig.stop_price, tp=sig.target_price) == "buy"


def test_breakout_base_refuses_to_fabricate_a_target_once_the_ladder_is_outrun():
    """A third independent audit round found that a large enough gap on the
    breakout bar can outrun even the FARTHEST measured-move extension —
    unlike every other strategy's entry-relative ATR/R extensions, this
    strategy's whole ladder is anchored to a fixed price level, so it can be
    'lapped'. When that happens, _build_target_ladder drops all three rungs
    and falls through to its generic degenerate-input fallback
    (entry + risk*rr_target_mult), which produced a plausible-looking,
    exactly-2.0x R:R target the strategy's own measured-move thesis never
    proposed, for an entry that had already run ~24x past its stated
    objective. The strategy must refuse to fire rather than invent a
    different thesis than the one it claims to trade."""
    from app.services.strategy_engine import breakout_base_signal

    bars = [{"open": 100.0, "high": 100.3, "low": 99.7, "close": 100.0, "volume": 1_000}
            for _ in range(24)]
    bars.append({"open": 100.0, "high": 115.5, "low": 99.9, "close": 115.0, "volume": 2_000})
    assert breakout_base_signal(bars, base_lookback=20, atr_tight_max=99.0, volume_mult=1.5) is None


def test_breakout_base_still_fires_on_a_moderate_gap_with_an_honest_low_rr():
    """Mirror of the above: a gap that only outruns the PRIMARY rung (not the
    farthest extension) must still fire — this is the honest-low-R:R case
    investigated and deliberately left alone (see breakout_base_signal's own
    comment), not the fabricated-fallback case above."""
    from app.services.strategy_engine import breakout_base_signal

    bars = [{"open": 100.0, "high": 100.05, "low": 99.95, "close": 100.0, "volume": 1_000}
            for _ in range(24)]
    bars.append({"open": 120.06, "high": 120.06, "low": 99.9, "close": 100.15, "volume": 2_000})
    sig = breakout_base_signal(bars, base_lookback=20, atr_tight_max=99.0, volume_mult=1.5)
    assert sig is not None, "a moderate gap must still fire, with an honest (low) R:R"
    risk = sig.entry_price - sig.stop_price
    reward = sig.target_price - sig.entry_price
    assert reward / risk < 1.0


def test_breakout_base_atr_ignores_todays_own_wide_range_bar():
    """A second independent audit round found the base_high anchor fix (above)
    doesn't hold when the BREAKOUT BAR ITSELF has a wide range/wick relative to
    the tight base: `_atr(bars)` includes today's bar, so one huge-range candle
    can dominate a 14-period average and inflate the stop's `atr * 0.2` buffer
    with the very volatility event the strategy is trying to trade — collapsing
    R:R back below 1 (reproduced at 0.19x) even with the correct anchor.

    Fix: ATR is computed pre-breakout (`bars[:-1]`), matching how base_high/
    base_low already exclude today's bar. This fixture is that exact repro:
    a near-flat 24-bar base (range 0.10) followed by a bar with a 30-point
    high-low range that still closes only $0.06 above the base."""
    from app.services.strategy_engine import breakout_base_signal

    bars = [{"open": 100.0, "high": 100.05, "low": 99.95, "close": 100.0, "volume": 1_000}
            for _ in range(24)]
    bars.append({"open": 100.0, "high": 130.0, "low": 99.0, "close": 100.06, "volume": 2_000})
    sig = breakout_base_signal(bars, base_lookback=20, atr_tight_max=99.0, volume_mult=1.5)
    assert sig is not None, "fixture must fire — a skipping thesis test proves nothing"
    # Pre-breakout ATR must reflect the flat base (~0.1), not today's 30-point range.
    assert sig.atr < 1.0, f"ATR {sig.atr} is contaminated by today's own wide-range bar"
    risk = sig.entry_price - sig.stop_price
    reward = sig.target_price - sig.entry_price
    assert risk > 0
    assert reward / risk > 1.0, "measured-move target must be reachable at a real R:R"


def _flat_base_then_breakdown(base_high: float = 104.0, base_low: float = 100.0) -> list[dict]:
    """Mirror of `_flat_base_then_breakout`: 25 bars of a tight base, then a
    high-volume close below it."""
    bars = []
    mid = (base_high + base_low) / 2
    for _ in range(25):
        bars.append({"open": mid, "high": base_high, "low": base_low,
                     "close": mid, "volume": 1_000_000})
    bars.append({"open": base_low, "high": base_low + 0.5, "low": base_low - 2,
                 "close": base_low - 1, "volume": 5_000_000})
    return bars


def test_breakout_base_rung_one_is_the_measured_move_off_the_base_low_bearish():
    """Bearish mirror. This is the exact branch where an earlier audit found
    breakout_base anchoring the stop on the far side of the base (base_high)
    instead of the breakdown level (base_low), making R:R < 1 on every input —
    a Bullish-only test suite could not have caught that."""
    from app.services.strategy_engine import breakout_base_signal

    bars = _flat_base_then_breakdown()
    sig = breakout_base_signal(bars, base_lookback=20, atr_tight_max=99.0,
                               volume_mult=1.5, direction="Bearish")
    assert sig is not None, "fixture must fire — a skipping thesis test proves nothing"
    height = sig.detail["base_height"]
    anchor = sig.detail["measured_move_anchor"]
    assert height == pytest.approx(4.0, abs=0.01)
    assert sig.target_price == pytest.approx(round(anchor - height, 2), abs=0.01)
    assert sig.targets[0] == sig.target_price
    # Stop must be anchored at the breakdown level (base_low == anchor here),
    # not the far side of the base (base_high = anchor + height) — risk is the
    # overshoot plus a small ATR buffer, not the whole base's width.
    assert sig.stop_price < anchor + height
    assert sig.stop_price > sig.entry_price
    # The two outward extensions survive: anchor - 1.5H and anchor - 2H.
    assert sig.targets == [round(anchor - height, 2),
                           round(anchor - height * 1.5, 2),
                           round(anchor - height * 2.0, 2)]
    reward = sig.entry_price - sig.target_price
    risk = sig.stop_price - sig.entry_price
    assert reward / risk > 1.0, "measured-move target must be reachable at a real R:R"


# ── ma_crossover ──────────────────────────────────────────────────────────────

def test_ma_crossover_primary_target_is_unchanged_at_three_atr():
    """Regression guard: this is the ONE strategy whose rung 1 must not move,
    because it has no thesis price target to move to."""
    from app.services.strategy_engine import ma_crossover_signal, _atr

    # A monotonically rising series never crosses — the fast MA is above the slow
    # MA from the first comparable bar, so ma_crossover_signal returns None and a
    # `pytest.skip` test would pass while proving nothing. Use the flat-then-step
    # shape that tests/test_strategy_params.py::_crossover_bars already relies on:
    # the cross happens on the first stepped bar, 5 bars from the end.
    bars = [{"open": 99.9, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1_000}
            for _ in range(100)]
    bars += [{"open": 199.9, "high": 200.5, "low": 199.5, "close": 200.0, "volume": 1_000}
             for _ in range(5)]
    sig = ma_crossover_signal(bars, fast=20, slow=50, lookback=10)
    assert sig is not None, "fixture must fire — a skipping thesis test proves nothing"

    atr = _atr(bars)
    expected = round(sig.entry_price + atr * 3.0, 2)
    assert sig.target_price == pytest.approx(expected, abs=0.02)
    assert sig.detail["exit_rule"] == "cross_back"
    assert sig.detail["cross_back_level"] > 0
    # 3 / 4.5 / 6 ATR all survive: this stop sits at the slow MA, so `risk` here
    # is many times ATR — precisely the case an R-relative floor would have broken.
    assert len(sig.targets) == 3
    assert sig.targets[1] == pytest.approx(round(sig.entry_price + atr * 4.5, 2), abs=0.02)
    assert sig.targets[2] == pytest.approx(round(sig.entry_price + atr * 6.0, 2), abs=0.02)


def test_ma_crossover_primary_target_is_unchanged_at_three_atr_bearish():
    """Bearish mirror (death cross) of the guard above."""
    from app.services.strategy_engine import ma_crossover_signal, _atr

    bars = [{"open": 200.1, "high": 200.5, "low": 199.5, "close": 200.0, "volume": 1_000}
            for _ in range(100)]
    bars += [{"open": 100.1, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1_000}
             for _ in range(5)]
    sig = ma_crossover_signal(bars, fast=20, slow=50, lookback=10, direction="Bearish")
    assert sig is not None, "fixture must fire — a skipping thesis test proves nothing"

    atr = _atr(bars)
    expected = round(sig.entry_price - atr * 3.0, 2)
    assert sig.target_price == pytest.approx(expected, abs=0.02)
    assert sig.detail["exit_rule"] == "cross_back"
    assert len(sig.targets) == 3
    assert sig.targets[1] == pytest.approx(round(sig.entry_price - atr * 4.5, 2), abs=0.02)
    assert sig.targets[2] == pytest.approx(round(sig.entry_price - atr * 6.0, 2), abs=0.02)


# ── mean_reversion_rsi ────────────────────────────────────────────────────────

def test_mean_reversion_rsi_never_targets_the_trend_sma():
    """The 200-SMA is BELOW entry on a bullish fire (oversold in an uptrend);
    targeting it would be targeting a loss. Rung 1 must be the SHORT-term mean."""
    from app.services.strategy_engine import mean_reversion_rsi_signal

    # A long uptrend, then a six-bar dip that drives RSI under 30 while price
    # stays comfortably above the 200-SMA, with a small final up-tick so the
    # "RSI recovering" gate (rsi[-1] > rsi[-2]) passes while rsi[-1] is still
    # below 30.
    #
    # Every number here is load-bearing and was chosen by checking the signal
    # actually fires. An earlier draft used a 0.12/bar ramp with an 8-bar dip:
    # the close landed BELOW the 200-SMA, the uptrend gate rejected, and the test
    # silently skipped every run. A 0.5 final tick also pushes RSI back over 30.
    # If this ever starts skipping, fix the fixture — do not relax the test.
    closes = [50 + i * 0.35 for i in range(260)]
    for _ in range(6):
        closes.append(closes[-1] - 2.0)
    closes.append(closes[-1] + 0.2)
    bars = [{"open": c, "high": c + 0.4, "low": c - 0.4, "close": c, "volume": 1_000_000}
            for c in closes]

    sig = mean_reversion_rsi_signal(bars, rsi_period=14, rsi_oversold=30, trend_sma=200)
    assert sig is not None, "fixture must fire — a skipping thesis test proves nothing"

    trend_sma_val = sig.detail["sma_200"]
    assert sig.entry_price > trend_sma_val, "bullish gate: entry is above the trend SMA"
    assert sig.target_price > sig.entry_price
    assert sig.target_price > trend_sma_val
    assert sig.targets[0] == sig.target_price
    # Rung 1 is the SHORT-term mean, and the detail dict reports it.
    assert sig.target_price == pytest.approx(sig.detail["sma_20"], abs=0.02)


def test_mean_reversion_rsi_drops_atr_extensions_that_sit_inside_the_short_mean():
    """The ATR extensions are measured from entry, so when the short mean is
    further away than 3.75 ATR they are all inside it and are dropped rather than
    reordered ahead of the thesis rung."""
    from app.services.strategy_engine import mean_reversion_rsi_signal

    closes = [50 + i * 0.35 for i in range(260)]
    for _ in range(6):
        closes.append(closes[-1] - 2.0)
    closes.append(closes[-1] + 0.2)
    bars = [{"open": c, "high": c + 0.4, "low": c - 0.4, "close": c, "volume": 1_000_000}
            for c in closes]

    sig = mean_reversion_rsi_signal(bars, rsi_period=14, rsi_oversold=30, trend_sma=200)
    assert sig is not None
    assert sig.targets == sorted(sig.targets)
    assert all(t > sig.entry_price for t in sig.targets)
    # Whatever survives, the short mean leads — never an ATR multiple.
    assert sig.targets[0] == pytest.approx(sig.detail["sma_20"], abs=0.02)


def test_mean_reversion_rsi_never_targets_the_trend_sma_bearish():
    """Bearish mirror: overbought in a downtrend. The 200-SMA is ABOVE entry on
    a bearish fire; targeting it would be targeting a loss."""
    from app.services.strategy_engine import mean_reversion_rsi_signal

    closes = [400 - i * 0.35 for i in range(260)]
    for _ in range(6):
        closes.append(closes[-1] + 2.0)
    closes.append(closes[-1] - 0.2)
    bars = [{"open": c, "high": c + 0.4, "low": c - 0.4, "close": c, "volume": 1_000_000}
            for c in closes]

    sig = mean_reversion_rsi_signal(bars, rsi_period=14, rsi_oversold=30,
                                    rsi_overbought=70, trend_sma=200, direction="Bearish")
    assert sig is not None, "fixture must fire — a skipping thesis test proves nothing"

    trend_sma_val = sig.detail["sma_200"]
    assert sig.entry_price < trend_sma_val, "bearish gate: entry is below the trend SMA"
    assert sig.target_price < sig.entry_price
    assert sig.target_price < trend_sma_val
    assert sig.targets[0] == sig.target_price
    assert sig.target_price == pytest.approx(sig.detail["sma_20"], abs=0.02)


# ── mean_reversion_bb ─────────────────────────────────────────────────────────

def _bb_dip_and_reclaim() -> list[dict]:
    """Deterministic (no `random`): a steady uptrend well above its 200-SMA, then
    a two-bar dip whose first bar's low tags the lower band and whose second bar
    closes back inside the band but still under the midline — the three gates at
    mean_reversion_bb_signal's Bullish branch.

    The dip/bounce magnitudes and the 1.2 low-pad were chosen by checking the
    signal actually fires AND that the 2R extension lands outside the upper band,
    so rung 2 is genuinely the opposite band. Do not tweak them casually.
    """
    closes = [80 + i * 0.09 for i in range(240)]
    closes.append(closes[-1] - 2.5)
    closes.append(closes[-1] + 0.6)
    return [{"open": c, "high": c + 0.5, "low": c - 1.2, "close": c, "volume": 1_000_000}
            for c in closes]


def test_mean_reversion_bb_targets_the_real_mid_band_then_the_opposite_band():
    """Rung 1 must equal the mid-band the signal itself reports in detail, and
    rung 2 the opposite band — not an R multiple that happens to be nearby."""
    from app.services.strategy_engine import mean_reversion_bb_signal

    sig = mean_reversion_bb_signal(_bb_dip_and_reclaim(), bb_period=20, bb_std=2.0, trend_sma=200)
    assert sig is not None, "fixture must fire — a skipping thesis test proves nothing"

    mid = sig.detail["bb_mid"]
    upper = sig.detail["bb_upper"]
    # Rung 1 IS the mid-band the signal itself reports — not an R multiple that
    # happens to be nearby, and not the opposite band.
    assert sig.target_price == pytest.approx(mid, abs=0.02)
    assert sig.targets[0] == sig.target_price
    assert sig.targets[1] == pytest.approx(upper, abs=0.02)
    assert all(t > sig.entry_price for t in sig.targets)
    assert sig.targets == sorted(sig.targets)


def test_mean_reversion_bb_targets_the_real_mid_band_then_the_opposite_band_bearish():
    """Bearish mirror: rung 1 the mid-band, rung 2 the lower band."""
    from app.services.strategy_engine import mean_reversion_bb_signal

    closes = [400 - i * 0.09 for i in range(240)]
    closes.append(closes[-1] + 2.5)
    closes.append(closes[-1] - 0.6)
    bars = [{"open": c, "high": c + 1.2, "low": c - 0.5, "close": c, "volume": 1_000_000}
            for c in closes]

    sig = mean_reversion_bb_signal(bars, bb_period=20, bb_std=2.0, trend_sma=200, direction="Bearish")
    assert sig is not None, "fixture must fire — a skipping thesis test proves nothing"

    mid = sig.detail["bb_mid"]
    lower = sig.detail["bb_lower"]
    assert sig.target_price == pytest.approx(mid, abs=0.02)
    assert sig.targets[0] == sig.target_price
    assert sig.targets[1] == pytest.approx(lower, abs=0.02)
    assert all(t < sig.entry_price for t in sig.targets)
    assert sig.targets == sorted(sig.targets, reverse=True)


# ── the two VWAP variants ─────────────────────────────────────────────────────

def test_mean_reversion_vwap_intraday_rung_one_is_vwap_itself():
    from app.services.strategy_engine import mean_reversion_vwap_signal

    # 40 flat bars establishing VWAP near 100, then a drop to ~97 with the final
    # bar ticking back up toward it.
    bars = [{"open": 100, "high": 100.3, "low": 99.7, "close": 100, "volume": 10_000}
            for _ in range(40)]
    bars.append({"open": 97.5, "high": 97.6, "low": 96.9, "close": 97.0, "volume": 10_000})
    bars.append({"open": 97.0, "high": 97.9, "low": 97.0, "close": 97.8, "volume": 10_000})
    sig = mean_reversion_vwap_signal(bars, vwap_dev_pct=1.5, reversal_pct=0.3, interval="15m")
    assert sig is not None, "fixture must fire — a skipping thesis test proves nothing"

    vwap = sig.detail["vwap"]
    # Rung 1 IS VWAP. This assertion is the regression guard for the pooled-sort
    # bug: here `entry + 2R` (~1 ATR) is nearer than VWAP (>=1.5% away), so a
    # nearest-first pool would put the R multiple first and this would fail.
    assert sig.target_price == pytest.approx(vwap, abs=0.02)
    assert sig.targets[0] == sig.target_price
    assert all(t > sig.entry_price for t in sig.targets)
    assert sig.targets == sorted(sig.targets)


def test_mean_reversion_vwap_intraday_rung_one_is_vwap_itself_bearish():
    from app.services.strategy_engine import mean_reversion_vwap_signal

    # 40 flat bars establishing VWAP near 100, then a rally to ~103 with the
    # final bar ticking back down toward it.
    bars = [{"open": 100, "high": 100.3, "low": 99.7, "close": 100, "volume": 10_000}
            for _ in range(40)]
    bars.append({"open": 102.5, "high": 103.1, "low": 102.4, "close": 103.0, "volume": 10_000})
    bars.append({"open": 103.0, "high": 103.0, "low": 102.1, "close": 102.2, "volume": 10_000})
    sig = mean_reversion_vwap_signal(bars, vwap_dev_pct=1.5, reversal_pct=0.3,
                                     interval="15m", direction="Bearish")
    assert sig is not None, "fixture must fire — a skipping thesis test proves nothing"

    vwap = sig.detail["vwap"]
    assert sig.target_price == pytest.approx(vwap, abs=0.02)
    assert sig.targets[0] == sig.target_price
    assert all(t < sig.entry_price for t in sig.targets)
    assert sig.targets == sorted(sig.targets, reverse=True)


def test_mean_reversion_vwap_daily_never_targets_vwap_itself():
    """Its gate is `close > vwap`, so VWAP is BEHIND entry — a VWAP target would
    be a target already achieved (and would be rejected by _entry_side)."""
    from app.services.strategy_engine import mean_reversion_vwap_daily_signal
    from app.services.strategy_backtest import _entry_side

    bars = [{"open": 100, "high": 101, "low": 99, "close": 100, "volume": 10_000}
            for _ in range(22)]
    bars.append({"open": 98, "high": 98.5, "low": 97, "close": 97.5, "volume": 10_000})
    bars.append({"open": 97.5, "high": 101.5, "low": 97.5, "close": 101.0, "volume": 10_000})
    sig = mean_reversion_vwap_daily_signal(bars, vwap_lookback=20, vwap_deviation_pct=0.02)
    assert sig is not None, "fixture must fire — a skipping thesis test proves nothing"

    vwap = sig.detail["rolling_vwap"]
    assert sig.target_price > sig.entry_price > vwap
    # Rung 1 is the MIRROR of the entry deviation, not VWAP itself.
    dev_frac = sig.detail["deviation_pct"] / 100.0
    assert sig.target_price == pytest.approx(round(vwap * (1 + dev_frac), 2), abs=0.02)
    assert _entry_side("Bullish", entry=sig.entry_price,
                       sl=sig.stop_price, tp=sig.target_price) == "buy"


def test_mean_reversion_vwap_daily_never_targets_vwap_itself_bearish():
    """Bearish mirror: gate is `close < vwap`, so VWAP is BEHIND entry (above
    it) — a VWAP target would be a target already achieved."""
    from app.services.strategy_engine import mean_reversion_vwap_daily_signal
    from app.services.strategy_backtest import _entry_side

    bars = [{"open": 100, "high": 101, "low": 99, "close": 100, "volume": 10_000}
            for _ in range(22)]
    bars.append({"open": 102, "high": 103, "low": 101.5, "close": 102.5, "volume": 10_000})
    bars.append({"open": 102.5, "high": 102.5, "low": 98.5, "close": 99.0, "volume": 10_000})
    sig = mean_reversion_vwap_daily_signal(bars, vwap_lookback=20,
                                           vwap_deviation_pct=0.02, direction="Bearish")
    assert sig is not None, "fixture must fire — a skipping thesis test proves nothing"

    vwap = sig.detail["rolling_vwap"]
    assert sig.target_price < sig.entry_price < vwap
    dev_frac = sig.detail["deviation_pct"] / 100.0
    assert sig.target_price == pytest.approx(round(vwap * (1 - dev_frac), 2), abs=0.02)
    assert _entry_side("Bearish", entry=sig.entry_price,
                       sl=sig.stop_price, tp=sig.target_price) == "sell"
