"""Tests that _detect_fvg returns the correct gap direction."""
from app.scoring.stock_scorer import _detect_fvg


def _make_bar(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c, "volume": 1_000_000}


def test_bullish_fvg_detected_when_upward_gap_present():
    """
    3-bar bullish FVG: prev_bar is lower, next_bar is higher — upward gap.
    prev_bar.high (101) < next_bar.low (103) → gap is (101, 103).
    Current price = 102 should be inside.
    """
    bars = [
        _make_bar(98, 101, 97, 100),   # prev_bar (oldest)
        _make_bar(100, 104, 99, 103),  # impulse candle (gap maker)
        _make_bar(103, 106, 103, 102), # next_bar (newest) — close = 102 (inside gap)
    ]
    hit, gap_low, gap_high = _detect_fvg(bars, "Bullish")
    assert hit is True, "Should detect bullish FVG"
    assert gap_low == 101.0
    assert gap_high == 103.0


def test_bullish_fvg_not_detected_when_downward_gap():
    """Downward gap should NOT register as a bullish FVG."""
    bars = [
        _make_bar(105, 108, 104, 107),  # prev_bar (older, higher)
        _make_bar(102, 104, 100, 101),  # impulse down
        _make_bar(97, 100, 97, 99),     # next_bar (newer, lower) — close = current_price
    ]
    hit, _, _ = _detect_fvg(bars, "Bullish")
    assert hit is False


def test_bearish_fvg_detected_when_downward_gap_present():
    """
    3-bar bearish FVG: prev_bar is higher, next_bar is lower — downward gap.
    prev_bar.low (104) > next_bar.high (103) → gap is (103, 104).
    Current price (close of newest bar) = 103 is at the lower edge of the gap.
    """
    bars = [
        _make_bar(106, 108, 104, 107),  # prev_bar (oldest)
        _make_bar(104, 105, 100, 101),  # impulse candle
        _make_bar(100, 103, 99, 103),   # next_bar (newest) — high=103, close=103 (consistent)
    ]
    hit, gap_low, gap_high = _detect_fvg(bars, "Bearish")
    assert hit is True, "Should detect bearish FVG"
    assert gap_low == 103.0
    assert gap_high == 104.0


def test_bearish_fvg_not_detected_when_upward_gap():
    """Upward gap should NOT register as a bearish FVG."""
    bars = [
        _make_bar(98, 101, 97, 100),
        _make_bar(101, 105, 100, 104),
        _make_bar(104, 107, 104, 106),
    ]
    hit, _, _ = _detect_fvg(bars, "Bearish")
    assert hit is False


def test_no_bars_returns_false():
    """len(bars) < 3 early-return guard — must return (False, 0.0, 0.0)."""
    hit, gap_low, gap_high = _detect_fvg([], "Bullish")
    assert hit is False
    assert gap_low == 0.0
    assert gap_high == 0.0


def test_overlapping_candles_no_gap():
    """
    Bars that overlap (no gap between prev_bar.high and next_bar.low) should
    return (False, 0.0, 0.0) for both Bullish and Bearish directions.
    """
    # Bullish: next_bar.low (100) <= prev_bar.high (102) — gap_high <= gap_low, no gap
    bars_bullish = [
        _make_bar(98, 102, 97, 101),   # prev_bar  — high = 102
        _make_bar(99, 105, 98, 104),   # impulse candle
        _make_bar(101, 104, 100, 101), # next_bar  — low  = 100
    ]
    hit, _, _ = _detect_fvg(bars_bullish, "Bullish")
    assert hit is False, "Overlapping bullish bars should not produce an FVG"

    # Bearish: next_bar.high (105) >= prev_bar.low (103) — gap_high <= gap_low, no gap
    bars_bearish = [
        _make_bar(106, 108, 103, 107),  # prev_bar  — low  = 103
        _make_bar(104, 105, 100, 101),  # impulse candle
        _make_bar(104, 105, 103, 104),  # next_bar  — high = 105
    ]
    hit, _, _ = _detect_fvg(bars_bearish, "Bearish")
    assert hit is False, "Overlapping bearish bars should not produce an FVG"
