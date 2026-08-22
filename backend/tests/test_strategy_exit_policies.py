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

    sig = pullback_ema_signal(_uptrend_pullback_bars(), tolerance=0.04)
    if sig is None:
        pytest.skip("setup did not fire on synthetic data")
    assert sig.targets and sig.targets[0] == sig.target_price
    assert all(b > a for a, b in zip(sig.targets, sig.targets[1:]))
    assert all(t > sig.entry_price for t in sig.targets)


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
