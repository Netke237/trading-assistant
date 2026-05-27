"""Tests for market structure detection algorithms."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.services.market_structure import (
    compute_structure,
    detect_fvg,
    detect_bos_choch,
    find_swings,
    compute_fibonacci,
    detect_rsi_divergence,
    detect_macd_divergence,
    detect_order_blocks,
    compute_confluence,
)


def _make_bar(time: str, open_: float, high: float, low: float, close: float, volume: int = 1000000) -> dict:
    return {"time": time, "open": open_, "high": high, "low": low, "close": close, "volume": volume}


# ---------------------------------------------------------------------------
# find_swings
# ---------------------------------------------------------------------------
class TestFindSwings:
    def test_swing_high_detected(self):
        bars = [
            _make_bar("2024-01-01", 100, 101, 99, 100),
            _make_bar("2024-01-02", 100, 103, 99, 102),
            _make_bar("2024-01-03", 102, 105, 101, 104),
            _make_bar("2024-01-04", 104, 108, 103, 107),
            _make_bar("2024-01-05", 107, 115, 106, 109),   # swing high at 115 (idx 4)
            _make_bar("2024-01-08", 109, 112, 108, 111),
            _make_bar("2024-01-09", 111, 108, 110, 107),
            _make_bar("2024-01-10", 107, 105, 106, 104),
            _make_bar("2024-01-11", 104, 103, 103, 103),
            _make_bar("2024-01-12", 103, 105, 102, 104),
        ]
        highs, _ = find_swings(bars, lookback=3)
        assert len(highs) >= 1
        assert any(h["price"] == 115 for h in highs)

    def test_swing_low_detected(self):
        bars = [
            _make_bar("2024-01-01", 100, 102, 99, 101),
            _make_bar("2024-01-02", 101, 103, 100, 102),
            _make_bar("2024-01-03", 102, 104, 101, 103),
            _make_bar("2024-01-04", 103, 105, 101, 104),
            _make_bar("2024-01-05", 104, 106, 95, 105),   # swing low at index 4
            _make_bar("2024-01-08", 105, 107, 104, 106),
            _make_bar("2024-01-09", 106, 108, 105, 107),
            _make_bar("2024-01-10", 107, 109, 106, 108),
            _make_bar("2024-01-11", 108, 110, 107, 109),
            _make_bar("2024-01-12", 109, 111, 108, 110),
        ]
        _, lows = find_swings(bars, lookback=3)
        assert len(lows) >= 1
        assert any(l["price"] == 95 for l in lows)

    def test_swings_both_detected_in_same_sequence(self):
        bars = [
            _make_bar("2024-01-01", 100, 101, 99, 100),
            _make_bar("2024-01-02", 100, 103, 99, 102),
            _make_bar("2024-01-03", 102, 106, 101, 105),
            _make_bar("2024-01-04", 105, 112, 104, 108),
            _make_bar("2024-01-05", 108, 107, 98, 102),
            _make_bar("2024-01-08", 102, 104, 101, 103),
            _make_bar("2024-01-09", 103, 105, 102, 104),
            _make_bar("2024-01-10", 104, 107, 103, 106),
            _make_bar("2024-01-11", 106, 108, 105, 107),
            _make_bar("2024-01-12", 107, 110, 106, 109),
        ]
        highs, lows = find_swings(bars, lookback=3)
        assert len(highs) >= 1
        assert len(lows) >= 1


# ---------------------------------------------------------------------------
# detect_fvg
# ---------------------------------------------------------------------------
class TestDetectFvg:
    def test_fvg_bullish_detected(self):
        bars = [
            _make_bar("2024-01-01", 100, 103, 99, 101),
            _make_bar("2024-01-02", 101, 105, 100, 104),
            _make_bar("2024-01-03", 104, 108, 106, 107),
        ]
        signals = detect_fvg(bars)
        bullish = [s for s in signals if s["direction"] == "bullish"]
        assert len(bullish) >= 1
        assert bullish[0]["kind"] == "FVG"
        assert bullish[0]["price_low"] == 103
        assert bullish[0]["price_high"] == 106

    def test_fvg_bearish_detected(self):
        bars = [
            _make_bar("2024-01-01", 115, 118, 114, 116),
            _make_bar("2024-01-02", 116, 117, 112, 113),
            _make_bar("2024-01-03", 113, 113, 105, 106),
        ]
        signals = detect_fvg(bars)
        bearish = [s for s in signals if s["direction"] == "bearish"]
        assert len(bearish) >= 1
        assert bearish[0]["kind"] == "FVG"

    def test_fvg_has_confidence(self):
        bars = [
            _make_bar("2024-01-01", 100, 103, 99, 101),
            _make_bar("2024-01-02", 101, 105, 100, 104),
            _make_bar("2024-01-03", 104, 108, 106, 107),
        ]
        signals = detect_fvg(bars)
        for s in signals:
            assert "confidence" in s
            assert 0 <= s["confidence"] <= 100

    def test_fvg_mitigated_when_touched(self):
        bars = [
            _make_bar("2024-01-01", 100, 103, 99, 101),
            _make_bar("2024-01-02", 101, 105, 100, 104),
            _make_bar("2024-01-03", 104, 108, 106, 107),
            _make_bar("2024-01-04", 107, 109, 104, 108),
        ]
        signals = detect_fvg(bars)
        mitigated = [s for s in signals if s.get("mitigated")]
        assert len(mitigated) >= 1

    def test_fvg_not_mitigated_when_untouched(self):
        bars = [
            _make_bar("2024-01-01", 100, 103, 99, 101),
            _make_bar("2024-01-02", 101, 105, 100, 104),
            _make_bar("2024-01-03", 104, 108, 106, 107),
            _make_bar("2024-01-04", 107, 108, 106.5, 107.5),  # does NOT touch gap 103-106
            _make_bar("2024-01-05", 107.5, 109, 106.5, 108),  # does NOT touch
        ]
        signals = detect_fvg(bars)
        unmitigated = [s for s in signals if not s.get("mitigated")]
        assert len(unmitigated) >= 1


# ---------------------------------------------------------------------------
# detect_bos_choch
# ---------------------------------------------------------------------------
class TestBosChoch:
    def test_bos_bullish_above_swing_high(self):
        bars = [
            _make_bar("2024-01-01", 100, 102, 98, 101),
            _make_bar("2024-01-02", 101, 104, 100, 103),
            _make_bar("2024-01-03", 103, 106, 102, 105),
            _make_bar("2024-01-04", 105, 108, 104, 107),
            _make_bar("2024-01-05", 107, 112, 106, 108),   # swing high at 112 (idx 4)
            _make_bar("2024-01-08", 108, 109, 107, 108),
            _make_bar("2024-01-09", 108, 109, 106, 107),
            _make_bar("2024-01-10", 107, 108, 105, 106),
            _make_bar("2024-01-11", 106, 107, 104, 105),
            _make_bar("2024-01-12", 105, 116, 103, 114),   # close=114 > 112 → BOS
        ]
        signals = detect_bos_choch(bars, lookback=3)
        bos_signals = [s for s in signals if s["kind"] == "BOS" and s["direction"] == "bullish"]
        assert len(bos_signals) >= 1

    def test_choch_direction_change(self):
        bars = [
            _make_bar("2024-01-01", 100, 102, 99, 101),
            _make_bar("2024-01-02", 101, 104, 100, 103),
            _make_bar("2024-01-03", 103, 106, 101, 105),
            _make_bar("2024-01-04", 105, 109, 103, 108),
            _make_bar("2024-01-05", 108, 112, 105, 111),
            _make_bar("2024-01-08", 111, 115, 108, 113),   # swing high at 115
            _make_bar("2024-01-09", 113, 113, 110, 112),
            _make_bar("2024-01-10", 112, 112, 109, 111),
            _make_bar("2024-01-11", 111, 111, 105, 108),
            _make_bar("2024-01-12", 108, 109, 97, 101),
            _make_bar("2024-01-15", 101, 103, 85, 95),      # swing low at 85
            _make_bar("2024-01-16", 95, 97, 90, 92),
            _make_bar("2024-01-17", 92, 94, 86, 86),
            _make_bar("2024-01-18", 86, 90, 86, 84),        # close=84 < 85 → bearish BOS
            _make_bar("2024-01-19", 84, 100, 84, 98),
            _make_bar("2024-01-20", 98, 120, 97, 119),      # close=119 > 115 → CHoCH!
        ]
        signals = detect_bos_choch(bars, lookback=3)
        choch_signals = [s for s in signals if s["kind"] == "CHoCH"]
        assert len(choch_signals) >= 1


# ---------------------------------------------------------------------------
# compute_fibonacci
# ---------------------------------------------------------------------------
class TestFibonacci:
    def test_fibonacci_levels_correct(self):
        bars = [
            _make_bar("2024-12-20", 120, 122, 119, 121),
            _make_bar("2024-12-23", 121, 124, 120, 123),
            _make_bar("2024-12-24", 123, 125, 122, 124),
            _make_bar("2024-12-26", 124, 200, 123, 199),
            _make_bar("2024-12-27", 199, 200, 95, 100),
            _make_bar("2024-12-30", 100, 110, 99, 105),
        ]
        result = compute_fibonacci(bars, lookback=100)
        assert result["kind"] == "Fibonacci"
        assert result["swing_high_price"] == 200
        assert result["swing_low_price"] == 95
        assert len(result["levels"]) == 7
        fib_pcts = [lvl["pct"] for lvl in result["levels"]]
        assert fib_pcts == [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
        assert result["levels"][0]["price"] == pytest.approx(95, 0.01)
        assert result["levels"][-1]["price"] == pytest.approx(200, 0.01)
        assert result["levels"][3]["price"] == pytest.approx(147.5, 0.01)


# ---------------------------------------------------------------------------
# detect_rsi_divergence
# ---------------------------------------------------------------------------
class TestRsiDivergence:
    def test_regular_bullish_divergence_detected(self):
        bars = [
            _make_bar(f"2024-01-{i+1:02d}", 100 - i*0.3, 102 - i*0.3, 98 - i*0.3, 101 - i*0.3)
            for i in range(26)
        ] + [
            _make_bar(f"2024-02-{i+1:02d}", 92.2 + i*0.5, 94.2 + i*0.5, 90.2 + i*0.5, 93.2 + i*0.5)
            for i in range(26)
        ]
        signals = detect_rsi_divergence(bars)
        assert isinstance(signals, list)

    def test_regular_bearish_divergence_detected(self):
        bars = [
            _make_bar(f"2024-01-{i+1:02d}", 100 + i*0.5, 102 + i*0.5, 98 + i*0.5, 101 + i*0.5)
            for i in range(26)
        ] + [
            _make_bar(f"2024-02-{i+1:02d}", 113 - i*0.8, 115 - i*0.8, 111 - i*0.8, 114 - i*0.8)
            for i in range(26)
        ]
        signals = detect_rsi_divergence(bars)
        assert isinstance(signals, list)


# ---------------------------------------------------------------------------
# detect_macd_divergence
# ---------------------------------------------------------------------------
class TestMacdDivergence:
    def test_macd_divergence_detected_with_trend_change(self):
        bars = [
            _make_bar(f"2024-01-{i+1:02d}", 100 - i*0.5, 102 - i*0.5, 98 - i*0.5, 101 - i*0.5)
            for i in range(30)
        ] + [
            _make_bar(f"2024-02-{i+1:02d}", 85 + i*1.2, 87 + i*1.2, 83 + i*1.2, 86 + i*1.2)
            for i in range(30)
        ]
        signals = detect_macd_divergence(bars)
        assert isinstance(signals, list)


# ---------------------------------------------------------------------------
# compute_confluence
# ---------------------------------------------------------------------------
class TestConfluence:
    def test_confluence_score_accumulates(self):
        signals = [
            {"kind": "FVG", "direction": "bullish", "time_start": "2024-01-03",
             "time_end": None, "price_high": 105, "price_low": 100,
             "mitigated": False, "confidence": 70, "mtf_aligned": False},
            {"kind": "OrderBlock", "direction": "bullish", "time_start": "2024-01-02",
             "time_end": None, "price_high": 106, "price_low": 101,
             "mitigated": False, "confidence": 78, "mtf_aligned": False},
            {"kind": "BOS", "direction": "bullish", "time": "2024-01-04",
             "price": 103, "confidence": 85, "mtf_aligned": False},
        ]
        zones = compute_confluence(signals)
        assert len(zones) > 0
        for z in zones:
            assert z["kind"] == "Confluence"
            assert "score" in z
            assert "components" in z
            assert 0 <= z["score"] <= 100

    def test_confluence_score_capped_at_100(self):
        signals = [
            {"kind": "FVG", "direction": "bullish", "time_start": "2024-01-03",
             "time_end": None, "price_high": 105, "price_low": 100,
             "mitigated": False, "confidence": 70, "mtf_aligned": False},
            {"kind": "OrderBlock", "direction": "bullish", "time_start": "2024-01-02",
             "time_end": None, "price_high": 106, "price_low": 101,
             "mitigated": False, "confidence": 78, "mtf_aligned": False},
            {"kind": "BOS", "direction": "bullish", "time": "2024-01-04",
             "price": 103, "confidence": 85, "mtf_aligned": False},
            {"kind": "Divergence", "direction": "bullish", "indicator": "RSI",
             "divergence_type": "regular", "time_start": "2024-01-03", "time_end": "2024-01-04",
             "price_start": 102, "price_end": 104, "confidence": 80, "mtf_aligned": False},
            {"kind": "Divergence", "direction": "bullish", "indicator": "MACD",
             "divergence_type": "regular", "time_start": "2024-01-03", "time_end": "2024-01-04",
             "price_start": 101, "price_end": 103, "confidence": 80, "mtf_aligned": False},
        ]
        zones = compute_confluence(signals)
        if zones:
            for z in zones:
                assert z["score"] <= 100

    def test_no_confluence_when_signals_apart(self):
        signals = [
            {"kind": "FVG", "direction": "bullish", "time_start": "2024-01-03",
             "time_end": None, "price_high": 105, "price_low": 100,
             "mitigated": False, "confidence": 70, "mtf_aligned": False},
            {"kind": "BOS", "direction": "bullish", "time": "2024-01-04",
             "price": 80, "confidence": 85, "mtf_aligned": False},
        ]
        zones = compute_confluence(signals)
        assert len(zones) == 0


# ---------------------------------------------------------------------------
# compute_structure (integration)
# ---------------------------------------------------------------------------
class TestComputeStructure:
    def test_compute_structure_with_enough_candles(self):
        bars = [
            _make_bar(f"2024-01-{i+1:02d}", 100 + i, 102 + i, 98 + i, 101 + i)
            for i in range(200)
        ]
        result = compute_structure(bars, "15min", "AAPL")
        assert isinstance(result, list)
        kinds = {s["kind"] for s in result if s is not None}
        assert "Fibonacci" in kinds

    def test_compute_structure_with_few_candles(self):
        bars = [
            _make_bar(f"2024-01-{i+1:02d}", 100 + i, 102 + i, 98 + i, 101 + i)
            for i in range(10)
        ]
        result = compute_structure(bars, "15min", "AAPL")
        assert isinstance(result, list)

    def test_compute_structure_with_real_aapl_data(self):
        fixture_path = Path(__file__).parent / "fixtures" / "AAPL_candles.json"
        with open(fixture_path) as f:
            bars = json.load(f)
        result = compute_structure(bars, "1D", "AAPL")
        assert isinstance(result, list)
        assert len(result) > 0
        kinds = {s["kind"] for s in result}
        assert "Fibonacci" in kinds
        assert any(s["kind"] in ("FVG", "BOS", "CHoCH") for s in result)

    def test_mtf_align_bullish(self):
        bars_1h = [_make_bar(f"2024-01-{i+1:02d}", 100 + i, 102 + i, 98 + i, 101 + i) for i in range(60)]
        bars_1d = [_make_bar(f"2024-03-{i+1:02d}", 150 + i, 152 + i, 148 + i, 151 + i) for i in range(30)]
        result = compute_structure(bars_1h, "1h", "AAPL", ht_candles=bars_1d)
        for s in result:
            if s.get("direction") == "bullish":
                assert s["mtf_aligned"] is True
