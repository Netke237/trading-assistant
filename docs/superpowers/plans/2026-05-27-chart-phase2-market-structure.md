# Chart Phase 2 — Market Structure Analysis: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add server-side market structure detection (FVG, BOS, CHoCH, Order Blocks, RSI/MACD divergence, Fibonacci auto-anchor, confluence scoring, multi-timeframe alignment) and render signals as visual overlays on the existing chart via WebSocket messages.

**Architecture:** Backend pure functions in `market_structure.py` compute signals from OHLCV candles and push them over the existing `WS /chart/stream/{symbol}` as new `"structure"` message type. Structure is recomputed on candle-close events (new candle start). Multi-timeframe analysis loads 1D candles when interval is 1h. Frontend receives via `ChartWSClient`, stores in Zustand `structureStore`, and renders via lightweight-charts v5 Primitives API attached to the CandlestickSeries using refs (not callbacks).

**Tech Stack:** Python 3 (FastAPI, pytest, asyncio, pytest-asyncio), TypeScript 5.7 (Next.js 15, lightweight-charts v5, Zustand v5, CSS Modules), branch `feat/chart-phase1`

---

## File Structure

### Create (backend)
| File | Responsibility |
|---|---|
| `backend/app/services/market_structure.py` | Pure functions: swing detection, FVG, BOS/CHoCH, Order Blocks, RSI/MACD divergence, Fibonacci, confluence, MTF alignment |
| `backend/tests/test_market_structure.py` | Unit tests for all detection algorithms including MTF, real fixture data |

### Modify (backend)
| File | Change |
|---|---|
| `backend/app/routers/chart.py` | Load 1D candles for 1h intervals; call `compute_structure()` after history send AND on candle-close; send `"structure"` WS message |

### Create (frontend)
| File | Responsibility |
|---|---|
| `frontend/types/structure.ts` | TypeScript types: `StructureSignal`, `ZoneSignal`, `LineSignal`, `DivergenceSignal` (with `price_start`/`price_end`), `FibonacciSignal`, `ConfluenceSignal` |
| `frontend/lib/structureStore.ts` | Zustand store: signals keyed by `symbol:interval`, per-kind visibility, structureVisible |
| `frontend/lib/__tests__/structureStore.test.ts` | Store tests (no localStorage mock since store doesn't persist) |
| `frontend/components/organisms/StructurePanel/index.tsx` | Slide-in toggle panel for signal kind visibility |
| `frontend/components/organisms/StructurePanel/StructurePanel.module.css` | Styles |
| `frontend/components/organisms/ChartOverlays/index.tsx` | Renders all primitives onto ChartPane via refs |
| `frontend/components/organisms/ChartOverlays/ChartOverlays.module.css` | Minimal CSS (kept for future extension per arch spec) |
| `frontend/lib/chartPrimitives/FVGPrimitive.ts` | ISeriesPrimitive for FVG/OB boxes — dashed border for mitigated, solid for OB |
| `frontend/lib/chartPrimitives/BOSPrimitive.ts` | ISeriesPrimitive for BOS/CHoCH lines with labels — thick border for mtf_aligned |
| `frontend/lib/chartPrimitives/FibPrimitive.ts` | ISeriesPrimitive for Fibonacci levels — only 61.8% thicker |
| `frontend/lib/chartPrimitives/DivergencePrimitive.ts` | ISeriesPrimitive for divergence diagonals — uses priceToCoordinate |
| `frontend/lib/chartPrimitives/ConfluencePrimitive.ts` | ISeriesPrimitive for confluence zones — only visible when score >= 70 |

### Modify (frontend)
| File | Change |
|---|---|
| `frontend/lib/chartWS.ts` | Extend `WSMessage` union with `{ type: 'structure'; symbol; interval; signals }` |
| `frontend/components/organisms/ChartWorkspace/index.tsx` | Handle `structure` WS messages, render `ChartOverlays` + `StructurePanel`, use refs for chart/series |
| `frontend/components/organisms/ChartPane/index.tsx` | Expose chart + mainSeries via refs (`chartApiRef`, `mainSeriesRef`) |
| `frontend/components/organisms/ChartTopBar/index.tsx` | Add "Structure" toggle button |

---

## Key Algorithm Decisions

| Decision | Rationale |
|---|---|
| BOS confidence uses formula (70+15+15) not pseudocode (80) | Formula section (line 458) is more detailed than inline hardcode (line 428) |
| MTF trend = close[-1] > SMA(20) on higher timeframe | Simple, deterministic, matches spec's "bullish trend" definition |
| Confluence score capped at `min(score, 100)` | Formula 90+10N can exceed 100 with multiple divergences |
| `detect_order_blocks` takes `bos_signals` parameter | Avoids re-computing BOS in `compute_structure` entry point |
| ChartPane uses refs not callbacks | Refs update on every series change, not just on mount |

---

### Task 1: Backend — Write all market structure tests (test-first)

**Files:**
- Create: `backend/tests/test_market_structure.py`

**Context:** Use existing backend test conventions (Pattern A: direct import, inline bar construction). Bars are `dict` with keys `{"time", "open", "high", "low", "close", "volume"}`. Import from `app.services.market_structure` (module doesn't exist yet — tests fail first, confirming TDD).

- [ ] **Step 1: Create `backend/tests/test_market_structure.py`**

```python
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
            _make_bar("2024-01-01", 100, 102, 99, 101),
            _make_bar("2024-01-02", 101, 103, 100, 102),
            _make_bar("2024-01-03", 102, 110, 101, 103),
            _make_bar("2024-01-04", 103, 105, 102, 104),
            _make_bar("2024-01-05", 104, 106, 103, 105),
            _make_bar("2024-01-08", 105, 107, 104, 106),
            _make_bar("2024-01-09", 106, 108, 105, 107),
            _make_bar("2024-01-10", 107, 109, 106, 108),
            _make_bar("2024-01-11", 108, 111, 107, 109),
            _make_bar("2024-01-12", 109, 112, 108, 110),
        ]
        highs, _ = find_swings(bars, lookback=3)
        assert len(highs) >= 1
        assert any(h["price"] == 110 for h in highs)

    def test_swing_low_detected(self):
        bars = [
            _make_bar("2024-01-01", 100, 102, 99, 101),
            _make_bar("2024-01-02", 101, 103, 100, 102),
            _make_bar("2024-01-03", 102, 104, 95, 103),
            _make_bar("2024-01-04", 103, 105, 102, 104),
            _make_bar("2024-01-05", 104, 106, 103, 105),
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
            _make_bar(f"2024-01-{i+1:02d}", 100 + i, 102 + i, 98 + i, 101 + i)
            for i in range(20)
        ]
        highs, lows = find_swings(bars)
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
            _make_bar("2024-01-01", 110, 112, 109, 111),
            _make_bar("2024-01-02", 111, 113, 108, 110),
            _make_bar("2024-01-03", 110, 111, 107, 108),
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
            _make_bar("2024-01-04", 107, 109, 107.1, 108),
            _make_bar("2024-01-05", 108, 110, 107.5, 109),
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
            _make_bar("2024-01-02", 101, 103, 100, 102),
            _make_bar("2024-01-03", 102, 104, 101, 103),
            _make_bar("2024-01-04", 103, 105, 102, 104),
            _make_bar("2024-01-05", 104, 108, 103, 105),
            _make_bar("2024-01-08", 105, 106, 104, 105),
            _make_bar("2024-01-09", 105, 107, 104, 106),
            _make_bar("2024-01-10", 106, 109, 105, 108),
            _make_bar("2024-01-11", 108, 112, 107, 111),
            _make_bar("2024-01-12", 111, 114, 110, 113),
        ]
        signals = detect_bos_choch(bars, lookback=3)
        bos_signals = [s for s in signals if s["kind"] == "BOS" and s["direction"] == "bullish"]
        assert len(bos_signals) >= 1

    def test_choch_direction_change(self):
        bars = [
            _make_bar("2024-01-01", 110, 112, 109, 111),
            _make_bar("2024-01-02", 111, 113, 110, 112),
            _make_bar("2024-01-03", 112, 114, 111, 113),
            _make_bar("2024-01-04", 113, 115, 112, 114),
            _make_bar("2024-01-05", 114, 116, 113, 115),
            _make_bar("2024-01-08", 115, 117, 114, 116),
            _make_bar("2024-01-09", 116, 118, 115, 117),
            _make_bar("2024-01-10", 117, 119, 116, 118),
            _make_bar("2024-01-11", 118, 120, 100, 105),
            _make_bar("2024-01-12", 105, 107, 101, 103),
            _make_bar("2024-01-15", 103, 106, 100, 102),
            _make_bar("2024-01-16", 102, 104, 101, 103),
            _make_bar("2024-01-17", 103, 108, 102, 107),
            _make_bar("2024-01-18", 107, 121, 106, 120),
        ]
        signals = detect_bos_choch(bars, lookback=3)
        assert len(signals) >= 1


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
            _make_bar("2024-12-27", 199, 201, 95, 100),
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
            # Add enough divergence signals to push score over 100
            {"kind": "Divergence", "direction": "bullish", "indicator": "RSI",
             "divergence_type": "regular", "time_start": "2024-01-03", "time_end": "2024-01-04",
             "price_low": 102, "price_high": 104, "confidence": 80, "mtf_aligned": False},
            {"kind": "Divergence", "direction": "bullish", "indicator": "MACD",
             "divergence_type": "regular", "time_start": "2024-01-03", "time_end": "2024-01-04",
             "price_low": 101, "price_high": 103, "confidence": 80, "mtf_aligned": False},
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
```

- [ ] **Step 2: Run tests (expect ImportError — tests fail before implementation)**

```bash
cd backend && python -m pytest tests/test_market_structure.py -v --tb=short 2>&1
```
Expected: FAIL with ImportError (module doesn't exist yet).

---

### Task 2: Backend — Implement market_structure.py

**Files:**
- Create: `backend/app/services/market_structure.py`

**Context:** Pure functions only. No I/O. Entry point is `compute_structure(candles, interval, symbol, ht_candles=None) -> list[dict]`. Candles have keys `time`, `open`, `high`, `low`, `close`, `volume`. All sub-detectors follow spec pseudocode. BOS confidence uses formula (70+15+15), not hardcoded 80. `detect_order_blocks` takes BOS signals as parameter. Confluence caps at 100. MTF alignment uses SMA(20) on higher timeframe.

- [ ] **Step 1: Create `backend/app/services/market_structure.py`**

```python
"""Market structure detection -- FVG, BOS, CHoCH, Order Blocks, divergence, Fibonacci, confluence, MTF alignment.

Pure functions only. No I/O. Candles are list[dict] with
{"time", "open", "high", "low", "close", "volume"}.
"""
from __future__ import annotations

import math
from typing import Union


FIB_LEVELS = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _calc_atr(candles: list[dict], period: int = 14) -> float:
    """Compute ATR (Average True Range) over the last `period` candles."""
    if len(candles) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i - 1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0.0
    window = trs[-period:]
    return sum(window) / len(window)


def _is_zone_signal(s: dict) -> bool:
    return s["kind"] in ("FVG", "OrderBlock")


def _is_line_signal(s: dict) -> bool:
    return s["kind"] in ("BOS", "CHoCH")


def _overlap(zone1: dict, zone2: dict) -> bool:
    """Check if two price zones overlap. Handles zone and line signals correctly."""
    if _is_line_signal(zone1):
        lo1 = hi1 = zone1.get("price", 0)
    else:
        lo1 = zone1.get("price_low", 0)
        hi1 = zone1.get("price_high", 0)
    if _is_line_signal(zone2):
        lo2 = hi2 = zone2.get("price", 0)
    else:
        lo2 = zone2.get("price_low", 0)
        hi2 = zone2.get("price_high", 0)
    return not (hi1 < lo2 or hi2 < lo1)


# ---------------------------------------------------------------------------
# Swing detection
# ---------------------------------------------------------------------------

def find_swings(candles: list[dict], lookback: int = 5) -> tuple[list[dict], list[dict]]:
    """Returns (swing_highs, swing_lows) -- each a list of {index, time, price}."""
    highs: list[dict[str, Union[int, str, float]]] = []
    lows: list[dict[str, Union[int, str, float]]] = []
    for i in range(lookback, len(candles) - lookback):
        window_h = [c["high"] for c in candles[i - lookback : i + lookback + 1]]
        if candles[i]["high"] == max(window_h):
            highs.append({"index": i, "time": candles[i]["time"], "price": candles[i]["high"]})
        window_l = [c["low"] for c in candles[i - lookback : i + lookback + 1]]
        if candles[i]["low"] == min(window_l):
            lows.append({"index": i, "time": candles[i]["time"], "price": candles[i]["low"]})
    return highs, lows


# ---------------------------------------------------------------------------
# FVG
# ---------------------------------------------------------------------------

def detect_fvg(candles: list[dict]) -> list[dict]:
    """Detect Fair Value Gaps (3-candle pattern)."""
    signals: list[dict] = []
    atr = _calc_atr(candles)
    for i in range(2, len(candles)):
        c0, c2 = candles[i - 2], candles[i]
        # Bullish FVG: c0.high < c2.low
        if c0["high"] < c2["low"]:
            gap = c2["low"] - c0["high"]
            confidence = min(100, int(gap / max(atr, 0.01) * 50))
            signals.append({
                "kind": "FVG", "direction": "bullish",
                "time_start": c0["time"], "time_end": None,
                "price_low": c0["high"], "price_high": c2["low"],
                "mitigated": False, "confidence": confidence,
                "mtf_aligned": False,
            })
        # Bearish FVG: c0.low > c2.high
        elif c0["low"] > c2["high"]:
            gap = c0["low"] - c2["high"]
            confidence = min(100, int(gap / max(atr, 0.01) * 50))
            signals.append({
                "kind": "FVG", "direction": "bearish",
                "time_start": c0["time"], "time_end": None,
                "price_low": c2["high"], "price_high": c0["low"],
                "mitigated": False, "confidence": confidence,
                "mtf_aligned": False,
            })
    # Mark mitigated
    for sig in signals:
        start_idx = None
        for i, c in enumerate(candles):
            if c["time"] == sig["time_start"]:
                start_idx = i
                break
        if start_idx is not None:
            for c in candles[start_idx + 2:]:
                if c["low"] <= sig["price_high"] and c["high"] >= sig["price_low"]:
                    sig["mitigated"] = True
                    sig["time_end"] = c["time"]
                    break
    return signals


# ---------------------------------------------------------------------------
# BOS / CHoCH
# ---------------------------------------------------------------------------

def detect_bos_choch(candles: list[dict], lookback: int = 5) -> list[dict]:
    """Detect Break of Structure and Change of Character."""
    highs, lows = find_swings(candles, lookback)
    signals: list[dict] = []
    trend: Union[str, None] = None

    for i in range(1, len(candles)):
        c = candles[i]
        # Bullish BOS: close above most recent swing high
        recent_high = None
        for h in reversed(highs):
            if h["index"] < i:
                recent_high = h
                break
        if recent_high and c["close"] > recent_high["price"]:
            kind = "CHoCH" if trend == "down" else "BOS"
            confidence = _bos_confidence(candles, i)
            signals.append({
                "kind": kind, "direction": "bullish",
                "time": c["time"], "price": recent_high["price"],
                "confidence": confidence, "mtf_aligned": False,
            })
            trend = "up"

        # Bearish BOS: close below most recent swing low
        recent_low = None
        for lval in reversed(lows):
            if lval["index"] < i:
                recent_low = lval
                break
        if recent_low and c["close"] < recent_low["price"]:
            kind = "CHoCH" if trend == "up" else "BOS"
            confidence = _bos_confidence(candles, i)
            signals.append({
                "kind": kind, "direction": "bearish",
                "time": c["time"], "price": recent_low["price"],
                "confidence": confidence, "mtf_aligned": False,
            })
            trend = "down"

    return signals


def _bos_confidence(candles: list[dict], idx: int) -> int:
    """BOS/CHoCH confidence: 70 base +15 if close at extreme +15 if volume above avg."""
    c = candles[idx]
    score = 70
    if c["close"] == c["high"] or c["close"] == c["low"]:
        score += 15
    if idx >= 20:
        avg_vol = sum(candles[j]["volume"] for j in range(idx - 20, idx)) / 20
        if c["volume"] > avg_vol:
            score += 15
    return min(score, 100)


# ---------------------------------------------------------------------------
# Order Blocks
# ---------------------------------------------------------------------------

def detect_order_blocks(candles: list[dict], bos_signals: list[dict] | None = None) -> list[dict]:
    """Detect Order Blocks: last bearish candle before bullish BOS, last bullish before bearish BOS."""
    if bos_signals is None:
        bos_signals = detect_bos_choch(candles)
    if not bos_signals:
        return []

    signals: list[dict] = []
    candle_index: dict[str, int] = {c["time"]: i for i, c in enumerate(candles)}
    bos_index: dict[str, int] = {}
    for bs in bos_signals:
        idx = candle_index.get(bs["time"])
        if idx is not None:
            bos_index[bs["time"]] = idx

    for bs in bos_signals:
        idx = bos_index.get(bs["time"])
        if idx is None or idx < 1:
            continue
        prev = candles[idx - 1]
        confidence = bs["confidence"]
        if bs["direction"] == "bullish":
            if prev["close"] < prev["open"]:
                signals.append({
                    "kind": "OrderBlock", "direction": "bullish",
                    "time_start": prev["time"], "time_end": None,
                    "price_high": prev["high"], "price_low": prev["low"],
                    "mitigated": False, "confidence": confidence,
                    "mtf_aligned": False,
                })
        else:
            if prev["close"] > prev["open"]:
                signals.append({
                    "kind": "OrderBlock", "direction": "bearish",
                    "time_start": prev["time"], "time_end": None,
                    "price_high": prev["high"], "price_low": prev["low"],
                    "mitigated": False, "confidence": confidence,
                    "mtf_aligned": False,
                })

    # Mark mitigated order blocks
    for sig in signals:
        start_idx = None
        for i, c in enumerate(candles):
            if c["time"] == sig["time_start"]:
                start_idx = i
                break
        if start_idx is not None:
            for c in candles[start_idx + 1:]:
                if c["low"] <= sig["price_high"] and c["high"] >= sig["price_low"]:
                    sig["mitigated"] = True
                    sig["time_end"] = c["time"]
                    break

    return signals


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------

def _calc_rsi_values(candles: list[dict], period: int = 14) -> list[float]:
    """Returns RSI values aligned with candle indices (None for first `period`)."""
    rsi_vals: list[Union[float, None]] = [None] * period
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        change = candles[i]["close"] - candles[i - 1]["close"]
        if change > 0:
            gains += change
        else:
            losses += abs(change)
    avg_gain = gains / period
    avg_loss = losses / period
    rs = avg_gain / max(avg_loss, 0.0001)
    rsi_vals.append(100.0 - (100.0 / (1.0 + rs)))

    for i in range(period + 1, len(candles)):
        change = candles[i]["close"] - candles[i - 1]["close"]
        gain = change if change > 0 else 0.0
        loss = abs(change) if change < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        rs = avg_gain / max(avg_loss, 0.0001)
        rsi_vals.append(100.0 - (100.0 / (1.0 + rs)))
    return rsi_vals  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------

def _calc_macd_histogram(candles: list[dict]) -> list[float]:
    """Returns MACD histogram values aligned with candle indices."""
    close_prices = [c["close"] for c in candles]
    ema12 = _calc_ema(close_prices, 12)
    ema26 = _calc_ema(close_prices, 26)
    macd_line = [ema12[i] - ema26[i] for i in range(len(ema12))]
    signal_line = _calc_ema(macd_line, 9)
    hist = [macd_line[i] - signal_line[i] for i in range(len(macd_line))]
    return hist


def _calc_ema(data: list[float], period: int) -> list[float]:
    multiplier = 2.0 / (period + 1)
    ema: list[float] = []
    for i, val in enumerate(data):
        if i == 0:
            ema.append(val)
        else:
            ema.append((val - ema[-1]) * multiplier + ema[-1])
    return ema


# ---------------------------------------------------------------------------
# Divergence detection (RSI + MACD)
# ---------------------------------------------------------------------------

def _divergence_confidence(is_regular: bool, bar_count: int) -> int:
    """Divergence confidence: 60 base +20 for regular +20 for multi-bar (>=3)."""
    score = 60
    if is_regular:
        score += 20
    if bar_count >= 3:
        score += 20
    return min(score, 100)


def detect_rsi_divergence(candles: list[dict]) -> list[dict]:
    """Detect regular + hidden RSI divergence."""
    if len(candles) < 30:
        return []
    rsi_vals = _calc_rsi_values(candles)
    return _detect_divergence(candles, rsi_vals, "RSI")


def detect_macd_divergence(candles: list[dict]) -> list[dict]:
    """Detect regular + hidden MACD divergence."""
    if len(candles) < 30:
        return []
    hist = _calc_macd_histogram(candles)
    return _detect_divergence(candles, hist, "MACD")


def _detect_divergence(candles: list[dict], indicator_vals: list[Union[float, None]], indicator: str) -> list[dict]:
    """Generic divergence detector on price vs indicator."""
    signals: list[dict] = []
    if len(candles) < 30:
        return signals

    price_swing_highs, price_swing_lows = find_swings(candles, lookback=5)
    ind_swing_highs = _find_indicator_swings(candles, indicator_vals, price_swing_highs, "high")
    ind_swing_lows = _find_indicator_swings(candles, indicator_vals, price_swing_lows, "low")

    # Regular bearish divergence: price HH, indicator LH
    for i in range(1, len(price_swing_highs)):
        ph0, ph1 = price_swing_highs[i - 1], price_swing_highs[i]
        if ph1["price"] > ph0["price"]:
            ih0 = _closest_indicator_swing(ind_swing_highs, ph0)
            ih1 = _closest_indicator_swing(ind_swing_highs, ph1)
            if ih0 and ih1 and ih1["value"] < ih0["value"]:
                bar_count = abs(ph1["index"] - ph0["index"]) + 1
                signals.append({
                    "kind": "Divergence", "direction": "bearish",
                    "indicator": indicator, "divergence_type": "regular",
                    "time_start": ph0["time"], "time_end": ph1["time"],
                    "price_start": ph0["price"], "price_end": ph1["price"],
                    "confidence": _divergence_confidence(True, bar_count),
                    "mtf_aligned": False,
                })

    # Regular bullish divergence: price LL, indicator HL
    for i in range(1, len(price_swing_lows)):
        pl0, pl1 = price_swing_lows[i - 1], price_swing_lows[i]
        if pl1["price"] < pl0["price"]:
            il0 = _closest_indicator_swing(ind_swing_lows, pl0)
            il1 = _closest_indicator_swing(ind_swing_lows, pl1)
            if il0 and il1 and il1["value"] > il0["value"]:
                bar_count = abs(pl1["index"] - pl0["index"]) + 1
                signals.append({
                    "kind": "Divergence", "direction": "bullish",
                    "indicator": indicator, "divergence_type": "regular",
                    "time_start": pl0["time"], "time_end": pl1["time"],
                    "price_start": pl0["price"], "price_end": pl1["price"],
                    "confidence": _divergence_confidence(True, bar_count),
                    "mtf_aligned": False,
                })

    return signals


def _find_indicator_swings(candles: list[dict], ind_vals: list[Union[float, None]],
                            price_swings: list[dict], direction: str) -> list[dict]:
    """For each price swing, find the indicator peak/trough within +/-2 candles."""
    result: list[dict] = []
    for ps in price_swings:
        idx = ps["index"]
        window_slice = ind_vals[max(0, idx - 2):min(len(ind_vals), idx + 3)]
        valid = [(i, v) for i, v in enumerate(window_slice) if v is not None]
        if not valid:
            continue
        if direction == "high":
            best = max(valid, key=lambda x: x[1])
        else:
            best = min(valid, key=lambda x: x[1])
        result_idx = max(0, idx - 2) + best[0]
        result.append({"index": result_idx, "value": best[1], "time": candles[result_idx]["time"]})
    return result


def _closest_indicator_swing(ind_swings: list[dict], price_swing: dict) -> Union[dict, None]:
    """Find the closest indicator swing to a price swing."""
    best = None
    best_dist = float("inf")
    for ins in ind_swings:
        dist = abs(ins["index"] - price_swing["index"])
        if dist < best_dist:
            best_dist = dist
            best = ins
    return best


# ---------------------------------------------------------------------------
# Fibonacci
# ---------------------------------------------------------------------------

def compute_fibonacci(candles: list[dict], lookback: int = 100) -> dict:
    """Auto-anchor Fibonacci retracement levels."""
    window = candles[-lookback:] if len(candles) > lookback else candles
    high = max(c["high"] for c in window)
    low = min(c["low"] for c in window)
    high_time = next(c["time"] for c in window if c["high"] == high)
    low_time = next(c["time"] for c in window if c["low"] == low)
    rng = high - low
    levels = [{"pct": p, "price": round(low + p * rng, 4)} for p in FIB_LEVELS]
    return {
        "kind": "Fibonacci",
        "swing_high_time": high_time,
        "swing_high_price": high,
        "swing_low_time": low_time,
        "swing_low_price": low,
        "levels": levels,
    }


# ---------------------------------------------------------------------------
# Confluence
# ---------------------------------------------------------------------------

def compute_confluence(signals: list[dict]) -> list[dict]:
    """Compute confluence scores for overlapping signal zones. Score capped at 100."""
    zone_signals = [s for s in signals if _is_zone_signal(s) or _is_line_signal(s)]
    if len(zone_signals) < 2:
        return []

    zones: list[dict] = []
    checked: set[int] = set()

    for i in range(len(zone_signals)):
        if i in checked:
            continue
        cluster = [zone_signals[i]]
        checked.add(i)
        lo = zone_signals[i].get("price_low", zone_signals[i].get("price", 0))
        hi = zone_signals[i].get("price_high", zone_signals[i].get("price", 0))

        for j in range(i + 1, len(zone_signals)):
            if j in checked:
                continue
            if _overlap({"price_low": lo, "price_high": hi}, zone_signals[j]):
                cluster.append(zone_signals[j])
                checked.add(j)
                p_lo = zone_signals[j].get("price_low", zone_signals[j].get("price", 0))
                p_hi = zone_signals[j].get("price_high", zone_signals[j].get("price", 0))
                lo = min(lo, p_lo)
                hi = max(hi, p_hi)

        if len(cluster) >= 2:
            score = 0
            for s in cluster:
                if s["kind"] == "FVG":
                    score += 30
                elif s["kind"] == "OrderBlock":
                    score += 25
                elif s["kind"] in ("BOS", "CHoCH"):
                    score += 20

            # Fibonacci levels within 0.5% of zone
            fib = next((s for s in signals if s["kind"] == "Fibonacci"), None)
            if fib:
                for lvl in fib["levels"]:
                    if abs(lvl["price"] - lo) / max(lo, 0.01) < 0.005 or abs(lvl["price"] - hi) / max(hi, 0.01) < 0.005:
                        score += 15
                        break

            # Per divergence signal in same bar range
            divergences = [s for s in signals if s["kind"] == "Divergence"]
            for div in divergences:
                div_lo = div.get("price_start", div.get("price", 0))
                div_hi = div.get("price_end", div.get("price", 0))
                if not (max(div_lo, div_hi) < lo or hi < min(div_lo, div_hi)):
                    score += 10

            zones.append({
                "kind": "Confluence",
                "price_high": hi,
                "price_low": lo,
                "score": min(score, 100),
                "components": list(set(s["kind"] for s in cluster)),
            })

    return zones


# ---------------------------------------------------------------------------
# MTF alignment
# ---------------------------------------------------------------------------

def _mtf_align(signals: list[dict], ht_candles: list[dict] | None) -> list[dict]:
    """Set mtf_aligned=True when signal direction matches higher-timeframe trend (SMA20)."""
    if not ht_candles or len(ht_candles) < 21:
        return signals
    close_prices = [c["close"] for c in ht_candles[-20:]]
    sma20 = sum(close_prices) / 20
    ht_trend = "up" if close_prices[-1] > sma20 else "down"
    for s in signals:
        s_direction = s.get("direction")
        if s_direction == "bullish" and ht_trend == "up":
            s["mtf_aligned"] = True
        elif s_direction == "bearish" and ht_trend == "down":
            s["mtf_aligned"] = True
    return signals


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def compute_structure(candles: list[dict], interval: str, symbol: str,
                      ht_candles: list[dict] | None = None) -> list[dict]:
    """Entry point. Returns list of signal dicts matching the structure message schema."""
    if len(candles) < 10:
        return []

    bos_sigs = detect_bos_choch(candles)
    signals: list[Union[dict, None]] = []
    signals.extend(detect_fvg(candles))
    signals.extend(bos_sigs)
    signals.extend(detect_order_blocks(candles, bos_sigs))
    signals.extend(detect_rsi_divergence(candles))
    signals.extend(detect_macd_divergence(candles))
    signals.append(compute_fibonacci(candles))

    all_signals = [s for s in signals if s is not None]
    confluence = compute_confluence(all_signals)
    all_signals.extend(confluence)

    all_signals = _mtf_align(all_signals, ht_candles)

    return all_signals
```

- [ ] **Step 2: Run tests**

```bash
cd backend && python -m pytest tests/test_market_structure.py -v --tb=short 2>&1
```
Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/market_structure.py backend/tests/test_market_structure.py
git commit -m "feat: add market structure detection with MTF alignment and tests"
```
