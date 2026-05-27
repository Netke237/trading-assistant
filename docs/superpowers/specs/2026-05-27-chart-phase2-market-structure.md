# Chart Phase 2 — Market Structure Analysis: Context Document

**Date:** 2026-05-27  
**Status:** Ready for implementation planning  
**Depends on:** Phase 1 (fully implemented on branch `feat/chart-phase1`)  
**Branch to work from:** `feat/chart-phase1` (or merge to main first)

---

## Overview

Phase 2 adds server-side market structure detection — Fair Value Gap (FVG), Break of Structure (BOS), Change of Character (CHoCH), Order Blocks, RSI/MACD divergence, and Fibonacci auto-anchor — and renders these signals as visual overlays on the existing chart. A confluence score is computed when multiple signals cluster in the same price zone.

Signals are pushed over the **same WebSocket channel** already established in Phase 1 (`WS /chart/stream/{symbol}`), using new message types. No new transport layer is needed.

---

## Phase 1 Foundation — What Already Exists

An implementer must understand these before touching anything.

### Backend files (all in `backend/app/`)

| File | What it does |
|---|---|
| `data/chart_cache.py` | `get_intraday(symbol, interval, days) → list[dict]` — OHLCV cache with TTL |
| `data/tradier_stream.py` | `TradierStreamClient` singleton — Tradier WS → per-symbol `asyncio.Queue` |
| `routers/chart.py` | `GET /chart/history` + `WS /chart/stream/{symbol}` |

### WebSocket message protocol (Phase 1)

Sent from backend to frontend over `ws://localhost:8000/chart/stream/{symbol}?interval=15min`:

```python
# On connect — full history
{"type": "history", "candles": [{"time": "...", "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}, ...]}

# On each trade tick
{"type": "tick", "data": {"symbol": "AAPL", "price": 182.5, "volume": 300, "timestamp": "2024-01-02T10:00:00"}}

# Keepalive (every 30s of silence)
{"type": "ping"}

# On error
{"type": "error", "message": "symbol not found"}
```

### Frontend files (all in `frontend/`)

| File | What it does |
|---|---|
| `lib/chartWS.ts` | `ChartWSClient` — connects to WS, exponential-backoff reconnect, pub/sub message dispatch |
| `lib/chartStore.ts` | Zustand store — symbol, interval, chartType, activeIndicators, paneLayout |
| `lib/indicators.ts` | Pure functions: calcSMA, calcEMA, calcRSI, calcMACD, calcBB, calcATR, calcVWAP |
| `components/organisms/ChartPane/index.tsx` | Wraps one `IChartApi` — accepts `SeriesConfig[]`, handles resize |
| `components/organisms/ChartWorkspace/index.tsx` | Root orchestrator — WS subscription, series memoization, pane layout |

### Key TypeScript types (already defined)

```typescript
// lib/chartWS.ts
export type WSMessage =
  | { type: 'history'; candles: Candle[] }
  | { type: 'tick'; data: { symbol: string; price: number; volume: number; timestamp: string } }
  | { type: 'ping' }
  | { type: 'error'; message: string };

// lib/indicators.ts
export interface Candle { time: string; open: number; high: number; low: number; close: number; volume: number; }
export interface Point { time: string; value: number; }

// components/organisms/ChartPane/index.tsx
export interface SeriesConfig {
  id: string;
  type: 'Candlestick' | 'Line' | 'Histogram';
  data: Candle[] | Point[];
  color?: string;
  priceScaleId?: string;
}
```

### Styling conventions (from CLAUDE.md — mandatory)

- CSS Modules only — no Tailwind, no inline style objects except one-offs
- CSS token names: `var(--bg-base)`, `var(--bg-surface)`, `var(--bg-nav)`, `var(--border-subtle)`, `var(--text-primary)`, `var(--text-secondary)`, `var(--text-dim)`, `var(--pass)`, `var(--caution)`, `var(--reject)`
- Component convention: `ComponentName/index.tsx` + `ComponentName.module.css`
- Atoms → Molecules → Organisms hierarchy — no skipping levels

---

## Phase 2 Requirements

### 1. Signal detection (backend, computed per symbol+interval)

Compute the following from OHLCV candles. Detection runs:
- Once on WS connect (for existing history)
- Again on each candle-close event (tick that starts a new candle)

| Signal | Description |
|---|---|
| **FVG** (Fair Value Gap) | Three-candle pattern: gap between candle[i-2].high and candle[i].low (bullish) or candle[i-2].low and candle[i].high (bearish). Unmitigated = not yet touched by price. |
| **BOS** (Break of Structure) | Price closes above previous swing high (bullish BOS) or below previous swing low (bearish BOS). Swing = local max/min over N lookback candles. |
| **CHoCH** (Change of Character) | First BOS in the opposite direction of the current trend. Marks a potential trend reversal. |
| **Order Block (OB)** | Last bearish candle before a bullish BOS (bullish OB). Last bullish candle before a bearish BOS (bearish OB). Rendered as a price zone box. |
| **RSI Divergence** | Regular bullish: price LL, RSI HL. Regular bearish: price HH, RSI LH. Hidden bullish: price HL, RSI LL. Hidden bearish: price LH, RSI HH. |
| **MACD Divergence** | Same four types as RSI, using MACD histogram peaks/troughs. |
| **Fibonacci Auto-Anchor** | Identify the most recent significant swing high and low (largest range within last 100 candles). Place levels at 0%, 23.6%, 38.2%, 50%, 61.8%, 78.6%, 100% of that range. |
| **Confluence Score** | 0–100. Per price zone: score += 30 if FVG overlaps, += 25 if OB overlaps, += 20 if BOS/CHoCH at same level, += 15 if Fib level within 0.5% of zone, += 10 per divergence signal in same bar range. |

### 2. Multi-timeframe analysis

- When `interval` is `1h`, also compute signals on `1D` candles for that symbol
- A bullish signal on 1h with a bullish trend on 1D gets `mtf_aligned: true` in its payload
- Frontend renders `mtf_aligned` signals with a thicker border/brighter color

### 3. WebSocket message extensions

New message types to add to the existing WS stream:

```python
# Sent after history message on connect, and after each candle-close
{
  "type": "structure",
  "symbol": "AAPL",
  "interval": "15min",
  "signals": [
    {
      "kind": "FVG",
      "direction": "bullish",           # "bullish" | "bearish"
      "time_start": "2024-01-02",       # candle time where signal begins
      "time_end": "2024-01-05",         # candle time where signal ends (or null if open)
      "price_high": 182.50,             # top of the signal zone
      "price_low": 181.00,              # bottom of the signal zone
      "mitigated": False,               # FVG/OB only
      "confidence": 72,                 # 0-100
      "mtf_aligned": True,              # multi-timeframe agreement
    },
    {
      "kind": "BOS",
      "direction": "bullish",
      "time": "2024-01-03",             # candle where BOS occurred
      "price": 183.00,                  # break level
      "confidence": 85,
      "mtf_aligned": False,
    },
    {
      "kind": "CHoCH",
      "direction": "bearish",
      "time": "2024-01-04",
      "price": 179.00,
      "confidence": 60,
      "mtf_aligned": False,
    },
    {
      "kind": "OrderBlock",
      "direction": "bullish",
      "time_start": "2024-01-01",
      "time_end": null,                 # null = still active
      "price_high": 181.50,
      "price_low": 180.00,
      "mitigated": False,
      "confidence": 78,
      "mtf_aligned": True,
    },
    {
      "kind": "Divergence",
      "direction": "bullish",
      "indicator": "RSI",               # "RSI" | "MACD"
      "divergence_type": "regular",     # "regular" | "hidden"
      "time_start": "2024-01-01",
      "time_end": "2024-01-03",
      "confidence": 65,
      "mtf_aligned": False,
    },
    {
      "kind": "Fibonacci",
      "swing_high_time": "2024-01-05",
      "swing_high_price": 185.00,
      "swing_low_time": "2023-12-28",
      "swing_low_price": 175.00,
      "levels": [
        {"pct": 0.0,   "price": 175.00},
        {"pct": 0.236, "price": 177.36},
        {"pct": 0.382, "price": 178.82},
        {"pct": 0.5,   "price": 180.00},
        {"pct": 0.618, "price": 181.18},
        {"pct": 0.786, "price": 182.86},
        {"pct": 1.0,   "price": 185.00},
      ]
    },
    {
      "kind": "Confluence",
      "price_high": 181.50,
      "price_low": 180.50,
      "score": 87,
      "components": ["FVG", "OrderBlock", "Fibonacci"],
    }
  ]
}
```

### 4. Frontend overlays on ChartPane

Rendered using lightweight-charts v5 **Primitives** API (not standard series — use `ISeriesApi.attachPrimitive()`):

| Signal | Rendering |
|---|---|
| FVG | Semi-transparent box from `price_low` to `price_high`, spanning `time_start` to `time_end` (or right edge). Green = bullish, red = bearish. Mitigated = dashed border, reduced opacity. |
| BOS | Horizontal line at `price` from `time` extending right. Label "BOS" at right edge. |
| CHoCH | Same as BOS but labeled "CHoCH" with a different color (orange). |
| Order Block | Box (same as FVG) but with a solid border. MTF-aligned = thicker border. |
| Divergence | Diagonal line connecting the two swing points on the price pane, plus an annotation. |
| Fibonacci | Horizontal lines at each level with % label. 61.8% line thicker. |
| Confluence | Highlighted box at the confluence zone with score badge. |

### 5. Visibility controls

Add a "Structure" toggle in `ChartTopBar` (next to "Indicators" button) that shows/hides all overlays. Per-signal-kind visibility is controlled from a new `StructurePanel` (same slide-in style as `IndicatorPanel`).

---

## Architecture

### Backend computation pipeline

```
WS /chart/stream/{symbol}
  On connect:
    1. get_intraday(symbol, interval) → candles
    2. send {"type": "history", "candles": candles}
    3. compute_structure(candles, interval, symbol) → signals
    4. send {"type": "structure", ...signals}
    5. subscribe(symbol) → queue

  On tick (new trade):
    6. tick → update current candle
    7. if new_candle_started:
         candles = get_intraday(symbol, interval)  # from cache, now includes closed candle
         signals = compute_structure(candles, interval, symbol)
         send {"type": "structure", ...signals}
    8. send {"type": "tick", ...}
```

### New backend file

`backend/app/services/market_structure.py` — pure functions only, no I/O:

```python
def compute_structure(candles: list[dict], interval: str, symbol: str) -> list[dict]:
    """Entry point. Returns list of signal dicts matching the structure message schema."""
    signals = []
    signals.extend(detect_fvg(candles))
    signals.extend(detect_bos_choch(candles))
    signals.extend(detect_order_blocks(candles))
    signals.extend(detect_rsi_divergence(candles))
    signals.extend(detect_macd_divergence(candles))
    signals.append(compute_fibonacci(candles))
    signals.extend(compute_confluence(signals))
    return [s for s in signals if s is not None]
```

### New frontend files

```
frontend/
  lib/
    structureStore.ts          # Zustand store for signal state per symbol+interval
  components/
    organisms/
      StructurePanel/
        index.tsx              # Slide-in: toggle FVG/BOS/OB/divergence/Fib visibility
        StructurePanel.module.css
      ChartOverlays/
        index.tsx              # Renders all primitives onto ChartPane ref
        ChartOverlays.module.css
        primitives/
          FVGPrimitive.ts      # ISeriesApi primitive for FVG/OB boxes
          BOSPrimitive.ts      # ISeriesApi primitive for BOS/CHoCH lines
          FibPrimitive.ts      # ISeriesApi primitive for Fibonacci levels
          DivergencePrimitive.ts
          ConfluencePrimitive.ts
```

### Modified files

| File | Change |
|---|---|
| `frontend/lib/chartWS.ts` | Extend `WSMessage` union with `{ type: 'structure'; symbol: string; interval: string; signals: StructureSignal[] }` |
| `frontend/components/organisms/ChartWorkspace/index.tsx` | Handle `structure` WS messages → dispatch to `structureStore` |
| `frontend/components/organisms/ChartTopBar/index.tsx` | Add "Structure" toggle button |
| `backend/app/routers/chart.py` | Call `compute_structure` after history send and on candle-close |

---

## New TypeScript Types

Add to a new file `frontend/types/structure.ts`:

```typescript
export type SignalKind = 'FVG' | 'BOS' | 'CHoCH' | 'OrderBlock' | 'Divergence' | 'Fibonacci' | 'Confluence';
export type Direction = 'bullish' | 'bearish';

export interface ZoneSignal {
  kind: 'FVG' | 'OrderBlock';
  direction: Direction;
  time_start: string;
  time_end: string | null;
  price_high: number;
  price_low: number;
  mitigated: boolean;
  confidence: number;
  mtf_aligned: boolean;
}

export interface LineSignal {
  kind: 'BOS' | 'CHoCH';
  direction: Direction;
  time: string;
  price: number;
  confidence: number;
  mtf_aligned: boolean;
}

export interface DivergenceSignal {
  kind: 'Divergence';
  direction: Direction;
  indicator: 'RSI' | 'MACD';
  divergence_type: 'regular' | 'hidden';
  time_start: string;
  time_end: string;
  confidence: number;
  mtf_aligned: boolean;
}

export interface FibonacciSignal {
  kind: 'Fibonacci';
  swing_high_time: string;
  swing_high_price: number;
  swing_low_time: string;
  swing_low_price: number;
  levels: { pct: number; price: number }[];
}

export interface ConfluenceSignal {
  kind: 'Confluence';
  price_high: number;
  price_low: number;
  score: number;
  components: SignalKind[];
}

export type StructureSignal = ZoneSignal | LineSignal | DivergenceSignal | FibonacciSignal | ConfluenceSignal;
```

### `structureStore.ts` shape

```typescript
interface StructureState {
  signals: Record<string, StructureSignal[]>;  // key: `${symbol}:${interval}`
  visibility: Record<SignalKind, boolean>;      // per-kind toggle
  setSignals: (key: string, signals: StructureSignal[]) => void;
  toggleKind: (kind: SignalKind) => void;
}
```

---

## Algorithm Details

### Swing point detection (used by BOS, CHoCH, divergence)
```python
def find_swings(candles, lookback=5):
    """Returns (swing_highs, swing_lows) as lists of {index, time, price}."""
    highs, lows = [], []
    for i in range(lookback, len(candles) - lookback):
        window_h = [c['high'] for c in candles[i-lookback:i+lookback+1]]
        if candles[i]['high'] == max(window_h):
            highs.append({'index': i, 'time': candles[i]['time'], 'price': candles[i]['high']})
        window_l = [c['low'] for c in candles[i-lookback:i+lookback+1]]
        if candles[i]['low'] == min(window_l):
            lows.append({'index': i, 'time': candles[i]['time'], 'price': candles[i]['low']})
    return highs, lows
```

### FVG detection
```python
def detect_fvg(candles):
    signals = []
    for i in range(2, len(candles)):
        c0, c2 = candles[i-2], candles[i]
        # Bullish FVG: gap between c0.high and c2.low
        if c0['high'] < c2['low']:
            signals.append({'kind': 'FVG', 'direction': 'bullish',
                            'time_start': c0['time'], 'time_end': None,
                            'price_low': c0['high'], 'price_high': c2['low'],
                            'mitigated': False, 'confidence': _fvg_confidence(c0, c2, candles)})
        # Bearish FVG: gap between c2.high and c0.low
        elif c0['low'] > c2['high']:
            signals.append({'kind': 'FVG', 'direction': 'bearish',
                            'time_start': c0['time'], 'time_end': None,
                            'price_low': c2['high'], 'price_high': c0['low'],
                            'mitigated': False, 'confidence': _fvg_confidence(c0, c2, candles)})
    # Mark mitigated: any subsequent candle touched the gap zone
    for sig in signals:
        after_idx = next((i for i, c in enumerate(candles) if c['time'] == sig['time_start']), None)
        if after_idx is not None:
            for c in candles[after_idx+2:]:
                if c['low'] <= sig['price_high'] and c['high'] >= sig['price_low']:
                    sig['mitigated'] = True
                    sig['time_end'] = c['time']
                    break
    return signals
```

### BOS / CHoCH detection
```python
def detect_bos_choch(candles, lookback=5):
    highs, lows = find_swings(candles, lookback)
    signals = []
    trend = None  # 'up' | 'down' | None
    for i in range(1, len(candles)):
        c = candles[i]
        # Check bullish BOS: close above most recent swing high
        recent_high = next((h for h in reversed(highs) if h['index'] < i), None)
        if recent_high and c['close'] > recent_high['price']:
            kind = 'CHoCH' if trend == 'down' else 'BOS'
            signals.append({'kind': kind, 'direction': 'bullish',
                            'time': c['time'], 'price': recent_high['price'], 'confidence': 80})
            trend = 'up'
        # Check bearish BOS: close below most recent swing low
        recent_low = next((l for l in reversed(lows) if l['index'] < i), None)
        if recent_low and c['close'] < recent_low['price']:
            kind = 'CHoCH' if trend == 'up' else 'BOS'
            signals.append({'kind': kind, 'direction': 'bearish',
                            'time': c['time'], 'price': recent_low['price'], 'confidence': 80})
            trend = 'down'
    return signals
```

### Fibonacci auto-anchor
```python
FIB_LEVELS = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]

def compute_fibonacci(candles, lookback=100):
    window = candles[-lookback:]
    high = max(c['high'] for c in window)
    low = min(c['low'] for c in window)
    high_time = next(c['time'] for c in window if c['high'] == high)
    low_time = next(c['time'] for c in window if c['low'] == low)
    rng = high - low
    levels = [{'pct': p, 'price': round(low + p * rng, 4)} for p in FIB_LEVELS]
    return {'kind': 'Fibonacci', 'swing_high_time': high_time, 'swing_high_price': high,
            'swing_low_time': low_time, 'swing_low_price': low, 'levels': levels}
```

### Confidence scoring
- FVG: `min(100, int(gap_size / atr * 50))` where `gap_size = price_high - price_low` and ATR is 14-period
- BOS/CHoCH: 70 base + 15 if close fully above/below (not wick), +15 if volume above 20-bar avg
- OB: same as BOS
- Divergence: 60 base + 20 if regular (stronger signal), +20 if multi-bar

---

## Lightweight-Charts v5 Primitives Integration

Phase 1 used standard Series (CandlestickSeries, LineSeries, HistogramSeries). Phase 2 uses **Primitives** for custom overlays.

lightweight-charts v5 primitive pattern:
```typescript
import { IChartApi, ISeriesApi } from 'lightweight-charts';

// A primitive is a class implementing ISeriesPrimitive
class FVGPrimitive implements ISeriesPrimitive {
  private readonly _signal: ZoneSignal;
  
  constructor(signal: ZoneSignal) { this._signal = signal; }

  // Return a renderer for each rendering pass
  paneViews(): ISeriesPrimitivePaneView[] {
    return [new FVGPaneView(this._signal)];
  }
}

class FVGPaneView implements ISeriesPrimitivePaneView {
  renderer(): ISeriesPrimitivePaneRenderer {
    return new FVGRenderer(this._signal);
  }
}

class FVGRenderer implements ISeriesPrimitivePaneRenderer {
  draw(target: CanvasRenderingTarget2D): void {
    // Use target.useMediaCoordinateSpace for pixel coordinates
    // Convert price → y via series.priceToCoordinate(price)
    // Convert time → x via chart.timeScale().timeToCoordinate(time)
  }
}

// Attach to the main series (CandlestickSeries):
mainSeries.attachPrimitive(new FVGPrimitive(signal));
```

**Key API for coordinate conversion:**
- `series.priceToCoordinate(price: number): number | null` — price → y pixel
- `chart.timeScale().timeToCoordinate(time: Time): number | null` — time → x pixel

---

## Tests Required

**Backend:**
- `backend/tests/test_market_structure.py` — unit tests per algorithm:
  - `test_fvg_bullish_detected` — 3-candle pattern creates bullish FVG
  - `test_fvg_mitigated_when_touched` — subsequent candle touching gap marks it mitigated
  - `test_bos_bullish_above_swing_high` — close above swing high creates bullish BOS
  - `test_choch_direction_change` — first BOS after opposite trend = CHoCH
  - `test_fibonacci_levels_correct` — 7 levels at correct prices
  - `test_confluence_score_accumulates` — overlapping signals increase score

**Frontend:**
- TypeScript typecheck must pass: `cd frontend && npm run typecheck`
- Manual verification: start backend + frontend, open `/chart`, toggle Structure panel, confirm overlays render

---

## Out of Scope (Phase 2)

- Alert triggering on structure signals — Phase 3
- Notification delivery — Phase 4
- Drawing tool integration with detected structures
- User-configurable swing lookback period (hardcoded defaults for now)
- Options contract charts (underlying stocks only)

---

## Acceptance Criteria

1. Backend `compute_structure(candles, interval, symbol)` returns valid signal list for 200 AAPL candles
2. `WS /chart/stream/AAPL` sends `structure` message immediately after `history` message on connect
3. FVG boxes visible on chart at correct price zones
4. BOS/CHoCH horizontal lines visible with labels
5. Order Block boxes visible, mitigated ones have reduced opacity
6. Fibonacci levels render as horizontal lines with % labels
7. "Structure" toggle in ChartTopBar hides/shows all overlays
8. StructurePanel lets user toggle each signal kind individually
9. Confluence zone highlighted when score ≥ 70
10. All backend tests pass; `npm run typecheck` clean
