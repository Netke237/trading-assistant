"""Test that consecutive BOS signals at the same level are deduplicated."""
import pytest
from app.services.market_structure import detect_bos_choch


def _candles(closes):
    """Build minimal candle dicts. high = close+0.5, low = close-0.5."""
    return [
        {
            'time': f'2024-01-{i + 1:02d}',
            'open': c, 'high': c + 0.5, 'low': c - 0.5,
            'close': c, 'volume': 1000,
        }
        for i, c in enumerate(closes)
    ]


# Candles designed to produce consecutive BOS at the same level:
# Rise to swing high at 110 (index 5), dip, then two consecutive candles
# (indices 12-13) both close above that same 110.5 swing high.
_DEDUP_CANDLES = _candles([
    100, 102, 104, 106, 108, 110,         # 0-5: rise to peak 110 (swing high ~110.5)
    109, 108, 107, 106, 105,              # 6-10: dip
    106, 108, 110, 112, 115,              # 11-15: rise, breaks 110.5 on candles 13 & 14
    114, 113, 112, 111, 110,              # 16-20: dip
    111, 113, 115, 117, 119,              # 21-25: break next swing high
    118, 117, 116, 115, 114,              # 26-30: dip near that level
    115, 116, 117, 118, 119,             # 31-35: rise near same level again
])


def test_no_duplicate_bos_within_price_range():
    """Two consecutive BOS signals at prices within 0.5% must not both appear."""
    signals = detect_bos_choch(_DEDUP_CANDLES)
    bos_bull = [
        s for s in signals
        if s.get('kind') == 'BOS' and s.get('direction') == 'bullish'
    ]

    for i in range(1, len(bos_bull)):
        prev, curr = bos_bull[i - 1], bos_bull[i]
        prev_price = prev.get('price', 0)
        curr_price = curr.get('price', 0)
        if prev_price > 0:
            price_diff_pct = abs(curr_price - prev_price) / prev_price * 100
            assert price_diff_pct >= 0.5, (
                f"Duplicate BOS: {prev_price:.2f} vs {curr_price:.2f} "
                f"({price_diff_pct:.3f}% apart, must be >= 0.5%)"
            )
