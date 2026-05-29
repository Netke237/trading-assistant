"""Tests for multi-timeframe FVG flagging (WS-D).

Covers:
  - detect_fvg always emits multi_tf: False
  - _mtf_align handles None / short ht_candles gracefully
  - _mtf_align sets multi_tf=True only when LTF and HTF FVG price ranges overlap,
    directions match, and the HTF FVG is unmitigated
"""
import pytest
from app.services.market_structure import detect_fvg, _mtf_align


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bullish_fvg_candles(c0_high: float = 100.0, c2_low: float = 110.0,
                          base_price: float = 105.0, count: int = 25) -> list[dict]:
    """Return a candle list that produces a bullish FVG (c0.high < c2.low).

    base_price controls the price level of all non-FVG candles.  Set it well
    above c2_low so that post-gap candles (low = base_price - 2) do NOT trade
    back into the gap, keeping the FVG unmitigated.
    """
    candles = []
    for i in range(count):
        candles.append({
            "time": i, "open": base_price - 1, "high": base_price + 1,
            "low": base_price - 2, "close": base_price, "volume": 1000,
        })
    # Inject FVG at positions 0, 1, 2
    candles[0]["high"] = c0_high
    candles[2]["low"] = c2_low
    candles[2]["open"] = c2_low + 1
    candles[2]["close"] = c2_low + 2
    candles[2]["high"] = c2_low + 3
    return candles


def _flat_candles(count: int = 25, base: float = 100.0) -> list[dict]:
    """Return candles with no FVG (all identical price, no gap)."""
    return [
        {"time": i, "open": base, "high": base + 1, "low": base - 1,
         "close": base, "volume": 1000}
        for i in range(count)
    ]


def _make_fvg_signal(direction: str = "bullish", price_low: float = 100.0,
                     price_high: float = 110.0, mitigated: bool = False) -> dict:
    """Build a minimal FVG signal dict (as if from detect_fvg)."""
    return {
        "kind": "FVG",
        "direction": direction,
        "time_start": 0,
        "time_end": None,
        "price_low": price_low,
        "price_high": price_high,
        "mitigated": mitigated,
        "confidence": 50,
        "mtf_aligned": False,
        "multi_tf": False,
    }


# ---------------------------------------------------------------------------
# Test 1: detect_fvg always emits multi_tf field set to False
# ---------------------------------------------------------------------------

def test_fvg_has_multi_tf_field():
    candles = _bullish_fvg_candles()
    signals = detect_fvg(candles)
    assert len(signals) >= 1, "Expected at least one FVG signal"
    for sig in signals:
        assert "multi_tf" in sig, f"Signal missing 'multi_tf' key: {sig}"
        assert sig["multi_tf"] is False, f"Expected multi_tf=False from detect_fvg, got {sig['multi_tf']}"


# ---------------------------------------------------------------------------
# Test 2: _mtf_align with ht_candles=None returns signals unchanged
# ---------------------------------------------------------------------------

def test_mtf_align_no_ht_candles():
    signals = [_make_fvg_signal()]
    result = _mtf_align(signals, None)
    assert result is signals or result == signals
    assert result[0]["multi_tf"] is False
    assert result[0]["mtf_aligned"] is False


# ---------------------------------------------------------------------------
# Test 3: _mtf_align with fewer than 21 ht_candles returns signals unchanged
# ---------------------------------------------------------------------------

def test_mtf_align_short_ht_candles():
    signals = [_make_fvg_signal()]
    short_candles = _flat_candles(count=5)
    result = _mtf_align(signals, short_candles)
    assert result[0]["multi_tf"] is False
    assert result[0]["mtf_aligned"] is False


# ---------------------------------------------------------------------------
# Test 4: multi_tf=True when LTF FVG price range overlaps HTF FVG (same direction, unmitigated)
# ---------------------------------------------------------------------------

def test_multi_tf_set_when_fvg_overlaps():
    # LTF FVG: bullish, range 100-110
    ltf_signal = _make_fvg_signal(direction="bullish", price_low=100.0, price_high=110.0)

    # HTF candles that produce an unmitigated bullish FVG overlapping 100-110:
    # c0.high=105, c2.low=115 → HTF FVG price_low=105, price_high=115
    # Overlap: max(100,105)=105 < min(110,115)=110  ✓
    # base_price=120 keeps post-gap candles (low=118) above the gap so it stays unmitigated.
    ht_candles = _bullish_fvg_candles(c0_high=105.0, c2_low=115.0, base_price=120.0, count=25)

    result = _mtf_align([ltf_signal], ht_candles)
    assert result[0]["multi_tf"] is True, (
        f"Expected multi_tf=True after overlap with HTF FVG, got {result[0]['multi_tf']}"
    )


# ---------------------------------------------------------------------------
# Test 5: multi_tf stays False when LTF FVG does NOT overlap HTF FVG
# ---------------------------------------------------------------------------

def test_multi_tf_not_set_when_no_overlap():
    # LTF FVG: bullish, range 100-110
    ltf_signal = _make_fvg_signal(direction="bullish", price_low=100.0, price_high=110.0)

    # HTF candles with bullish FVG at 120-130 (no overlap with 100-110).
    # base_price=140 keeps post-gap candles (low=138) above the 120-130 gap (unmitigated).
    ht_candles = _bullish_fvg_candles(c0_high=120.0, c2_low=130.0, base_price=140.0, count=25)

    result = _mtf_align([ltf_signal], ht_candles)
    assert result[0]["multi_tf"] is False, (
        f"Expected multi_tf=False when price ranges don't overlap, got {result[0]['multi_tf']}"
    )


# ---------------------------------------------------------------------------
# Test 6: multi_tf stays False when the overlapping HTF FVG is already mitigated
# ---------------------------------------------------------------------------

def test_multi_tf_not_set_when_htf_fvg_mitigated():
    # LTF FVG: bullish, range 100-110
    ltf_signal = _make_fvg_signal(direction="bullish", price_low=100.0, price_high=110.0)

    # Build HTF candles that produce an overlapping bullish FVG (105-115) BUT also
    # include a candle that mitigates it (price trades back into the gap).
    # detect_fvg marks mitigated=True when a later candle's low <= price_high and high >= price_low.
    # base_price=120 starts unmitigated; we then force candle[3] into the gap.
    ht_candles = _bullish_fvg_candles(c0_high=105.0, c2_low=115.0, base_price=120.0, count=25)
    # Replace candle at index 3 with one that dips into the 105-115 gap to trigger mitigation.
    ht_candles[3]["low"] = 106.0   # dips into gap (105-115)
    ht_candles[3]["high"] = 120.0
    ht_candles[3]["close"] = 118.0

    result = _mtf_align([ltf_signal], ht_candles)
    assert result[0]["multi_tf"] is False, (
        f"Expected multi_tf=False when HTF FVG is mitigated, got {result[0]['multi_tf']}"
    )
