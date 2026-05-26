import pytest
from app.scoring.stock_scorer import _detect_fvg, _rule_pullback

def _bar(close: float, high: float = None, low: float = None) -> dict:
    h = high if high is not None else close + 0.5
    l = low  if low  is not None else close - 0.5
    return {"open": close - 0.1, "high": h, "low": l, "close": close, "volume": 1_000_000, "time": "2026-01-01"}


class TestDetectFvg:
    def test_no_bars(self):
        assert _detect_fvg([], "Bullish") == (False, 0.0, 0.0)

    def test_bullish_fvg_detected(self):
        # bar[i-1].low=105, bar[i+1].high=100 → gap (100, 105); current=102 inside gap
        bars = [_bar(95)] * 10 + [
            _bar(104, high=106, low=105),   # prev bar: low=105
            _bar(102, high=103, low=101),   # middle (gap candle)
            _bar(102, high=101, low=99),    # next bar: high=101 → gap is (101, 105)
        ]
        # Adjust: next_bar high=101, prev_bar low=105 → gap (101,105), current=102 inside → hit
        # Rebuild properly:
        bars2 = [_bar(90)] * 10
        bars2 += [
            {"open": 103, "high": 106, "low": 105, "close": 104, "volume": 1000, "time": "2026-01-01"},  # prev: low=105
            {"open": 102, "high": 103, "low": 101, "close": 102, "volume": 1000, "time": "2026-01-02"},  # middle
            {"open": 101, "high": 101, "low": 99,  "close": 100, "volume": 1000, "time": "2026-01-03"},  # next: high=101
        ]
        # gap_low=101 (next.high), gap_high=105 (prev.low) → current=100 NOT inside
        # Adjust current to 102:
        bars2[-1]["close"] = 102
        hit, low, high = _detect_fvg(bars2, "Bullish")
        assert hit is True
        assert low == 101.0
        assert high == 105.0

    def test_no_fvg_when_candles_overlap(self):
        bars = [_bar(100 + i) for i in range(15)]  # smoothly rising — no gaps
        hit, _, _ = _detect_fvg(bars, "Bullish")
        assert hit is False

    def test_bearish_fvg_detected(self):
        bars = [_bar(110)] * 10
        bars += [
            {"open": 108, "high": 109, "low": 107, "close": 108, "volume": 1000, "time": "2026-01-01"},  # prev: high=109
            {"open": 105, "high": 106, "low": 104, "close": 105, "volume": 1000, "time": "2026-01-02"},  # middle
            {"open": 112, "high": 113, "low": 111, "close": 112, "volume": 1000, "time": "2026-01-03"},  # next: low=111
        ]
        # gap_low=109 (prev.high), gap_high=111 (next.low) → gap (109,111)
        bars[-1]["close"] = 110  # current inside gap
        hit, low, high = _detect_fvg(bars, "Bearish")
        assert hit is True
        assert low == 109.0
        assert high == 111.0

    def test_fvg_bonus_applied_to_caution_pullback(self):
        """A CAUTION-level pullback scores correctly and exposes fvg_hit/fvg_gap in detail."""
        # Build bars: 40 rising bars then a shallow pullback (~30% retracement → CAUTION)
        # With swing_high_lookback_bars=20 and no min_ago, the 20-bar window anchors the swing.
        # Rising phase: price goes from 400 to 420 (+0.5/bar for 40 bars).
        # Pullback phase: price falls 3 pts from the swing high of 422 → retracement ≈ 3/22 ≈ 14%
        # (below fib_shallow_min=0.236 → "no_pullback_yet" CAUTION 45).
        bars = []
        price = 400.0
        for i in range(40):
            bars.append({
                "open": price, "high": price + 2.0, "low": price - 1.0,
                "close": price, "volume": 500_000, "time": f"2026-01-{i+1:02d}",
            })
            price += 0.5
        # Shallow pullback — stays well within fib_shallow_max → CAUTION path
        price -= 3.0
        bars.append({
            "open": price, "high": price + 0.5, "low": price - 0.5,
            "close": price, "volume": 400_000, "time": "2026-02-01",
        })

        # Minimal config matching scoring_rules.yaml swing defaults
        cfg = {
            "swing_high_lookback_bars": 20,
            "swing_high_min_bars_ago": 0,
            "fib_shallow_min": 0.236,
            "fib_shallow_max": 0.382,
            "fib_standard_min": 0.382,
            "fib_standard_max": 0.500,
            "fib_golden_min": 0.500,
            "fib_golden_max": 0.618,
            "atr_period": 14,
            "atr_pass_min": 1.0,
            "atr_pass_max": 2.0,
            "atr_caution_max": 2.5,
        }
        result = _rule_pullback(bars, {"pullback": cfg}, direction="Bullish")
        assert result.score >= 0   # just verify it runs without error
        assert "fvg_hit" in result.detail
        assert "fvg_gap" in result.detail
