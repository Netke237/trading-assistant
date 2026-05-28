"""Tests for hidden divergence detection (price HL + indicator LL = hidden bullish, etc.)."""
import pytest
from app.services.market_structure import _detect_divergence


def _candles(closes):
    """Build minimal candle dicts. high = close+1, low = close-1."""
    return [
        {
            'time': f'2024-01-{i + 1:02d}',
            'open': c, 'high': c + 1, 'low': c - 1,
            'close': c, 'volume': 1000,
        }
        for i, c in enumerate(closes)
    ]


# ---------------------------------------------------------------------------
# Hidden bullish: price HL (higher low) + indicator LL (lower low)
# ---------------------------------------------------------------------------

# 33-bar sequence: falls to first low at price 94 (index 10, RSI 35),
# recovers, then falls to second low at price 97 (index 22, RSI 30).
# Price HL (97 > 94) + RSI LL (30 < 35) = hidden bullish divergence.
_HID_BULL_CLOSES = [
    110, 109, 108, 107, 106, 105, 104, 103, 102, 101,   # 0-9: fall
     95,  97,  99, 101, 103, 105, 104, 103, 102, 101,   # 10-19: first low 95, recover
    100,  99,  97,  99, 100, 101, 102, 103, 104, 105,   # 20-29: second low 97 (HL)
    106, 107, 108,                                        # 30-32: continue up
]
_HID_BULL_RSI = [
    60, 59, 58, 57, 56, 55, 54, 53, 52, 51,             # 0-9
    35, 36, 37, 38, 40, 45, 44, 43, 42, 41,             # 10-19: RSI trough 35
    39, 38, 30, 31, 32, 33, 34, 35, 36, 37,             # 20-29: RSI trough 30 (LL)
    38, 39, 40,                                           # 30-32
]


# ---------------------------------------------------------------------------
# Hidden bearish: price LH (lower high) + indicator HH (higher high)
# ---------------------------------------------------------------------------

# 33-bar sequence: rises to first high at price 111 (index 10, RSI 65),
# dips, then rises to second high at price 108 (index 25, RSI 70).
# Price LH (108 < 111) + RSI HH (70 > 65) = hidden bearish divergence.
_HID_BEAR_CLOSES = [
     90,  91,  92,  93,  94,  95,  96,  97,  98,  99,  # 0-9: rise
    110, 109, 108, 107, 106, 105, 104, 103, 102, 101,  # 10-19: first high 110, dip
    102, 103, 104, 105, 106, 107, 106, 105, 104, 103,  # 20-29: second high 107 (LH)
    102, 101, 100,                                       # 30-32: fall
]
_HID_BEAR_RSI = [
    40, 41, 42, 43, 44, 45, 46, 47, 48, 49,            # 0-9
    65, 64, 63, 62, 61, 60, 59, 58, 57, 56,            # 10-19: RSI peak 65, dip
    57, 58, 59, 60, 61, 70, 69, 68, 67, 66,            # 20-29: RSI peak 70 (HH)
    65, 64, 63,                                          # 30-32
]


# ---------------------------------------------------------------------------
# Regular bearish (regression guard): price HH + RSI LH
# ---------------------------------------------------------------------------

# 33-bar sequence: rises to first high 108 (index 7, RSI 60),
# dips, rises to second high 111 (index 18, RSI 55).
# Price HH (111 > 108) + RSI LH (55 < 60) = regular bearish divergence.
_REG_BEAR_CLOSES = [
    100, 101, 102, 103, 104, 105, 106, 107, 106, 105,  # 0-9: rise to 107
    104, 103, 104, 105, 106, 107, 108, 109, 110, 109,  # 10-19: dip then second peak 110
    108, 107, 106, 105, 104, 103, 102, 101, 100,  99,  # 20-29: fall
     98,  97,  96,                                       # 30-32: continue
]
_REG_BEAR_RSI = [
    50, 51, 52, 53, 54, 55, 57, 60, 59, 58,            # 0-9: RSI peaks at 60 (index 7)
    57, 56, 56, 57, 58, 57, 56, 55, 55, 54,            # 10-19: RSI lower peak ~55 (LH)
    53, 52, 51, 50, 49, 48, 47, 46, 45, 44,            # 20-29
    43, 42, 41,                                          # 30-32
]


# ---------------------------------------------------------------------------
# No divergence: price and indicator move together
# ---------------------------------------------------------------------------

_NO_DIV_CLOSES = [
    100, 101, 102, 103, 104, 105, 106, 107, 108, 109,  # 0-9
    110, 111, 112, 113, 114, 115, 116, 117, 118, 119,  # 10-19
    120, 121, 122, 123, 124, 125, 126, 127, 128, 129,  # 20-29
    130, 131, 132,                                       # 30-32
]
_NO_DIV_RSI = [
    50, 51, 52, 53, 54, 55, 56, 57, 58, 59,
    60, 61, 62, 63, 64, 65, 66, 67, 68, 69,
    70, 71, 72, 73, 74, 75, 76, 77, 78, 79,
    80, 81, 82,
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_hidden_bullish_divergence_detected():
    """Price HL (higher low) + RSI LL (lower low) → hidden bullish signal."""
    signals = _detect_divergence(_candles(_HID_BULL_CLOSES), _HID_BULL_RSI, 'RSI')
    hidden_bull = [s for s in signals if s['divergence_type'] == 'hidden' and s['direction'] == 'bullish']
    assert len(hidden_bull) >= 1, f"Expected hidden bullish divergence, got signals: {signals}"


def test_hidden_bearish_divergence_detected():
    """Price LH (lower high) + RSI HH (higher high) → hidden bearish signal."""
    signals = _detect_divergence(_candles(_HID_BEAR_CLOSES), _HID_BEAR_RSI, 'RSI')
    hidden_bear = [s for s in signals if s['divergence_type'] == 'hidden' and s['direction'] == 'bearish']
    assert len(hidden_bear) >= 1, f"Expected hidden bearish divergence, got signals: {signals}"


def test_regular_divergence_still_detected_alongside_hidden():
    """Adding hidden detection should not break existing regular detection."""
    signals = _detect_divergence(_candles(_REG_BEAR_CLOSES), _REG_BEAR_RSI, 'RSI')
    regular_bear = [s for s in signals if s['divergence_type'] == 'regular' and s['direction'] == 'bearish']
    assert len(regular_bear) >= 1, f"Expected regular bearish divergence, got signals: {signals}"


def test_no_divergence_when_price_and_indicator_agree():
    """If price and indicator move together monotonically, no divergence of any type."""
    signals = _detect_divergence(_candles(_NO_DIV_CLOSES), _NO_DIV_RSI, 'RSI')
    assert signals == [], f"Expected no divergence, got: {signals}"
