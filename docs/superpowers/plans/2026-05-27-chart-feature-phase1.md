# Chart Feature Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a TradingView-style Chart page to Bamendjou with live Tradier WebSocket data, yfinance fallback, and common indicators computed in the browser.

**Architecture:** FastAPI exposes `GET /chart/history` (REST, cached) and `WS /chart/stream/{symbol}` (WebSocket relay from Tradier streaming). The frontend `ChartWSClient` connects to the WS, seeds lightweight-charts v5 from the history payload, then updates on each tick. Common indicators (SMA, EMA, RSI, MACD, BB, ATR, VWAP) are computed in the browser from the received OHLCV data.

**Tech Stack:** FastAPI + httpx (backend), Next.js 15 App Router + TypeScript (frontend), lightweight-charts v5 (charts), Zustand v5 (state), CSS Modules (styling).

**Spec:** `docs/superpowers/specs/2026-05-27-chart-feature-design.md`

---

## File Map

### New backend files
| File | Responsibility |
|---|---|
| `backend/app/data/chart_cache.py` | Intraday OHLCV cache with per-interval TTL + chart semaphore(2) |
| `backend/app/data/tradier_stream.py` | `TradierStreamClient` singleton — one persistent Tradier WS, per-symbol Queue fanout |
| `backend/app/routers/chart.py` | `GET /chart/history` + `WS /chart/stream/{symbol}` |
| `backend/tests/test_chart_cache.py` | Unit tests for cache TTL, hit/miss, concurrent access |
| `backend/tests/test_chart_router.py` | REST history + WS connect/message/disconnect integration tests |

### Modified backend files
| File | Change |
|---|---|
| `backend/app/main.py` | Register `chart` router |

### New frontend files
| File | Responsibility |
|---|---|
| `frontend/lib/indicators.ts` | Pure functions: calcSMA, calcEMA, calcRSI, calcMACD, calcBB, calcATR, calcVWAP |
| `frontend/lib/chartWS.ts` | `ChartWSClient` class — connect, reconnect backoff, message dispatch |
| `frontend/lib/chartStore.ts` | Zustand store: symbol, interval, chartType, activeIndicators, paneLayout |
| `frontend/components/organisms/ChartWorkspace/index.tsx` | Root layout: topbar + left sidebar + panes + right panel |
| `frontend/components/organisms/ChartWorkspace/ChartWorkspace.module.css` | Layout styles |
| `frontend/components/organisms/ChartTopBar/index.tsx` | Symbol picker, timeframe strip, chart type, indicators toggle, pop-out button |
| `frontend/components/organisms/ChartTopBar/ChartTopBar.module.css` | |
| `frontend/components/organisms/DrawingToolbar/index.tsx` | Left sidebar: cursor, trendline, fib, shapes, text, measure, zoom, magnet, lock, hide, delete |
| `frontend/components/organisms/DrawingToolbar/DrawingToolbar.module.css` | |
| `frontend/components/organisms/ChartPane/index.tsx` | Wraps one `IChartApi` instance; accepts series config array; handles resize |
| `frontend/components/organisms/ChartPane/ChartPane.module.css` | |
| `frontend/components/organisms/IndicatorPanel/index.tsx` | Slide-in panel: add/remove/configure indicators |
| `frontend/components/organisms/IndicatorPanel/IndicatorPanel.module.css` | |
| `frontend/components/organisms/ChartRightPanel/index.tsx` | Tabs: Watchlist + Data (OHLCV + indicator values at cursor) |
| `frontend/components/organisms/ChartRightPanel/ChartRightPanel.module.css` | |
| `frontend/app/(frame)/chart/page.tsx` | Chart page (inside frame layout) |
| `frontend/app/(frame)/chart/page.module.css` | |
| `frontend/app/chart/standalone/page.tsx` | Pop-out window (outside frame, no NavRail) |
| `frontend/app/chart/standalone/layout.tsx` | Minimal layout for standalone |

### Modified frontend files
| File | Change |
|---|---|
| `frontend/components/organisms/NavRail/index.tsx` (or equivalent nav file) | Add Chart item between Calendar and Alerts |
| `frontend/app/(frame)/screener/step-4-ranking/page.tsx` | Add chart icon per row → deep-link |
| `frontend/app/(frame)/screener/step-6-contracts/page.tsx` | Add chart icon per row → deep-link |
| `frontend/app/(frame)/watchlist/page.tsx` | Add chart icon per row → deep-link |

---

## Task 1: Intraday cache (`chart_cache.py`)

**Files:**
- Create: `backend/app/data/chart_cache.py`
- Create: `backend/tests/test_chart_cache.py`

- [ ] **Step 1.1: Write the failing tests**

```python
# backend/tests/test_chart_cache.py
from __future__ import annotations
import asyncio
import time
import pytest
from unittest.mock import patch, AsyncMock


@pytest.mark.asyncio
async def test_cache_miss_calls_fetch():
    """First call for a symbol fetches from source."""
    mock_rows = [{"time": "2024-01-02", "open": 100, "high": 105, "low": 99, "close": 103, "volume": 1000}]
    with patch("app.data.chart_cache.fetch_intraday_candles", return_value=mock_rows) as mock_fetch:
        from app.data.chart_cache import get_intraday, _INTRADAY_CACHE
        _INTRADAY_CACHE.clear()
        result = await get_intraday("AAPL", "15min", 55)
    assert result == mock_rows
    mock_fetch.assert_called_once_with("AAPL", "15min", 55)


@pytest.mark.asyncio
async def test_cache_hit_skips_fetch():
    """Second call within TTL returns cached data without fetching."""
    mock_rows = [{"time": "2024-01-02", "open": 100, "high": 105, "low": 99, "close": 103, "volume": 1000}]
    with patch("app.data.chart_cache.fetch_intraday_candles", return_value=mock_rows) as mock_fetch:
        from app.data.chart_cache import get_intraday, _INTRADAY_CACHE
        _INTRADAY_CACHE.clear()
        await get_intraday("AAPL", "15min", 55)
        result = await get_intraday("AAPL", "15min", 55)
    assert result == mock_rows
    assert mock_fetch.call_count == 1  # only fetched once


@pytest.mark.asyncio
async def test_cache_expiry_refetches():
    """Call after TTL expires fetches again."""
    mock_rows = [{"time": "2024-01-02", "open": 100, "high": 105, "low": 99, "close": 103, "volume": 1000}]
    with patch("app.data.chart_cache.fetch_intraday_candles", return_value=mock_rows) as mock_fetch:
        from app.data.chart_cache import get_intraday, _INTRADAY_CACHE
        _INTRADAY_CACHE.clear()
        # Manually insert expired entry
        import time as t
        _INTRADAY_CACHE["MSFT:15min:55"] = (mock_rows, t.monotonic() - 1)  # already expired
        await get_intraday("MSFT", "15min", 55)
    assert mock_fetch.call_count == 1


@pytest.mark.asyncio
async def test_semaphore_limits_concurrent_fetches():
    """Chart semaphore allows at most 2 concurrent fetches."""
    from app.data.chart_cache import _CHART_SEM
    assert _CHART_SEM._value == 2
```

- [ ] **Step 1.2: Run tests to verify they fail**

```bash
cd backend && pytest tests/test_chart_cache.py -v
```
Expected: `ModuleNotFoundError: No module named 'app.data.chart_cache'`

- [ ] **Step 1.3: Implement `chart_cache.py`**

```python
# backend/app/data/chart_cache.py
from __future__ import annotations

import asyncio
import time

from app.data.market import fetch_intraday_candles

_INTRADAY_CACHE: dict[str, tuple[list[dict], float]] = {}

_TTL_BY_INTERVAL: dict[str, float] = {
    "1min":  15 * 60,
    "5min":  15 * 60,
    "15min": 30 * 60,
    "1h":    30 * 60,
    "4h":     4 * 3600,
    "daily":  4 * 3600,
}

_CHART_SEM = asyncio.Semaphore(2)


def _key(symbol: str, interval: str, days: int) -> str:
    return f"{symbol}:{interval}:{days}"


async def get_intraday(symbol: str, interval: str = "15min", days: int = 55) -> list[dict]:
    """Return OHLCV bars, served from cache when fresh."""
    key = _key(symbol, interval, days)
    now = time.monotonic()

    cached = _INTRADAY_CACHE.get(key)
    if cached is not None and now < cached[1]:
        return cached[0]

    async with _CHART_SEM:
        cached = _INTRADAY_CACHE.get(key)
        if cached is not None and now < cached[1]:
            return cached[0]

        rows = await asyncio.to_thread(fetch_intraday_candles, symbol, interval, days)
        ttl = _TTL_BY_INTERVAL.get(interval, 30 * 60)
        _INTRADAY_CACHE[key] = (rows, now + ttl)
        return rows
```

- [ ] **Step 1.4: Run tests to verify they pass**

```bash
cd backend && pytest tests/test_chart_cache.py -v
```
Expected: 4 tests PASSED

- [ ] **Step 1.5: Commit**

```bash
git add backend/app/data/chart_cache.py backend/tests/test_chart_cache.py
git commit -m "feat(chart): add intraday OHLCV cache with per-interval TTL"
```

---

## Task 2: Tradier stream client (`tradier_stream.py`)

**Files:**
- Create: `backend/app/data/tradier_stream.py`
- Add tests to: `backend/tests/test_chart_router.py` (stream client section)

- [ ] **Step 2.1: Write failing tests**

```python
# backend/tests/test_tradier_stream.py
from __future__ import annotations
import asyncio
import pytest
from app.data.tradier_stream import TradierStreamClient


@pytest.mark.asyncio
async def test_subscribe_returns_queue():
    """subscribe() creates a Queue for that symbol."""
    client = TradierStreamClient()
    q = await client.subscribe("AAPL")
    assert q is not None
    client.unsubscribe("AAPL", q)


@pytest.mark.asyncio
async def test_unsubscribe_removes_symbol():
    """unsubscribe() removes the queue; symbol disappears when last subscriber leaves."""
    client = TradierStreamClient()
    q = await client.subscribe("AAPL")
    client.unsubscribe("AAPL", q)
    assert "AAPL" not in client._queues


@pytest.mark.asyncio
async def test_tick_fanout_to_multiple_subscribers():
    """Ticks pushed by _dispatch reach all queues for that symbol."""
    client = TradierStreamClient()
    q1 = await client.subscribe("MSFT")
    q2 = await client.subscribe("MSFT")

    tick = {"symbol": "MSFT", "price": 300.0, "volume": 100, "timestamp": "2024-01-02T10:00:00"}
    client._dispatch("MSFT", tick)

    assert await asyncio.wait_for(q1.get(), timeout=1.0) == tick
    assert await asyncio.wait_for(q2.get(), timeout=1.0) == tick

    client.unsubscribe("MSFT", q1)
    client.unsubscribe("MSFT", q2)
```

- [ ] **Step 2.2: Run tests to verify they fail**

```bash
cd backend && pytest tests/test_tradier_stream.py -v
```
Expected: `ModuleNotFoundError: No module named 'app.data.tradier_stream'`

- [ ] **Step 2.3: Implement `tradier_stream.py`**

```python
# backend/app/data/tradier_stream.py
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

TRADIER_BASE_URL = os.getenv("TRADIER_BASE_URL", "https://api.tradier.com")
TRADIER_TOKEN = os.getenv("TRADIER_API_TOKEN", "")


class TradierStreamClient:
    """One persistent Tradier streaming connection; fans out ticks to per-symbol Queues."""

    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue]] = {}
        self._task: Optional[asyncio.Task] = None

    # ── Public API ────────────────────────────────────────────────────────────

    async def subscribe(self, symbol: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._queues.setdefault(symbol, []).append(q)
        self._ensure_running()
        return q

    def unsubscribe(self, symbol: str, q: asyncio.Queue) -> None:
        bucket = self._queues.get(symbol, [])
        try:
            bucket.remove(q)
        except ValueError:
            pass
        if not bucket:
            self._queues.pop(symbol, None)

    def _dispatch(self, symbol: str, tick: dict) -> None:
        for q in self._queues.get(symbol, []):
            try:
                q.put_nowait(tick)
            except asyncio.QueueFull:
                pass

    # ── Internals ─────────────────────────────────────────────────────────────

    def _ensure_running(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def _create_session(self) -> Optional[str]:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{TRADIER_BASE_URL}/v1/markets/events/session",
                    headers={"Authorization": f"Bearer {TRADIER_TOKEN}", "Accept": "application/json"},
                    timeout=10,
                )
                resp.raise_for_status()
                return resp.json().get("stream", {}).get("url")
        except Exception as exc:
            logger.error("Tradier session create failed: %s", exc)
            return None

    async def _run(self) -> None:
        backoff = 1
        while True:
            if not self._queues:
                await asyncio.sleep(1)
                continue

            url = await self._create_session()
            if not url:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
                continue

            symbols = list(self._queues.keys())
            try:
                async with httpx.AsyncClient() as client:
                    async with client.stream(
                        "POST", url,
                        json={"symbols": symbols, "filter": ["trade"], "linebreak": True},
                        headers={"Authorization": f"Bearer {TRADIER_TOKEN}", "Accept": "application/json"},
                        timeout=None,
                    ) as resp:
                        backoff = 1
                        async for line in resp.aiter_lines():
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                msg = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            if msg.get("type") == "trade":
                                sym = msg.get("symbol", "")
                                self._dispatch(sym, {
                                    "symbol": sym,
                                    "price": float(msg.get("price", 0)),
                                    "volume": int(msg.get("size", 0)),
                                    "timestamp": msg.get("timestamp", ""),
                                })
            except Exception as exc:
                logger.warning("Tradier stream error: %s — retry in %ds", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)


_client = TradierStreamClient()


def get_stream_client() -> TradierStreamClient:
    return _client
```

- [ ] **Step 2.4: Run tests to verify they pass**

```bash
cd backend && pytest tests/test_tradier_stream.py -v
```
Expected: 3 tests PASSED

- [ ] **Step 2.5: Commit**

```bash
git add backend/app/data/tradier_stream.py backend/tests/test_tradier_stream.py
git commit -m "feat(chart): add TradierStreamClient with per-symbol queue fanout"
```

---

## Task 3: Chart router — REST + WebSocket (`chart.py`)

**Files:**
- Create: `backend/app/routers/chart.py`
- Create: `backend/tests/test_chart_router.py`

- [ ] **Step 3.1: Write failing tests**

```python
# backend/tests/test_chart_router.py
from __future__ import annotations
import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport
from app.main import app


MOCK_CANDLES = [
    {"time": "2024-01-02 09:30", "open": 100.0, "high": 105.0, "low": 99.0, "close": 103.0, "volume": 1000},
    {"time": "2024-01-02 09:45", "open": 103.0, "high": 106.0, "low": 102.0, "close": 105.0, "volume": 1200},
]


@pytest.mark.asyncio
async def test_history_returns_candles():
    """GET /chart/history returns OHLCV list."""
    with patch("app.routers.chart.get_intraday", return_value=MOCK_CANDLES):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/chart/history", params={"symbol": "AAPL", "interval": "15min", "days": 55})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["close"] == 103.0


@pytest.mark.asyncio
async def test_history_uppercases_symbol():
    """Symbol is uppercased regardless of input."""
    with patch("app.routers.chart.get_intraday", return_value=MOCK_CANDLES) as mock_get:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.get("/chart/history", params={"symbol": "aapl", "interval": "15min"})
    mock_get.assert_called_once_with("AAPL", "15min", 55)


@pytest.mark.asyncio
async def test_ws_sends_history_on_connect():
    """WebSocket sends history message immediately after connect."""
    with patch("app.routers.chart.get_intraday", return_value=MOCK_CANDLES):
        with patch("app.routers.chart.get_stream_client") as mock_sc:
            import asyncio
            q: asyncio.Queue = asyncio.Queue()
            mock_sc.return_value.subscribe = AsyncMock(return_value=q)
            mock_sc.return_value.unsubscribe = lambda *a: None

            from starlette.testclient import TestClient
            with TestClient(app) as client:
                with client.websocket_connect("/chart/stream/AAPL?interval=15min") as ws:
                    msg = ws.receive_json()
                    assert msg["type"] == "history"
                    assert len(msg["candles"]) == 2
```

- [ ] **Step 3.2: Run tests to verify they fail**

```bash
cd backend && pytest tests/test_chart_router.py -v
```
Expected: FAIL — router not registered yet

- [ ] **Step 3.3: Implement `chart.py`**

```python
# backend/app/routers/chart.py
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.data.chart_cache import get_intraday
from app.data.tradier_stream import get_stream_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chart", tags=["chart"])


@router.get("/history")
async def history(
    symbol: str = Query(...),
    interval: str = Query("15min"),
    days: int = Query(55),
) -> list[dict]:
    return await get_intraday(symbol.upper(), interval, days)


@router.websocket("/stream/{symbol}")
async def stream(
    websocket: WebSocket,
    symbol: str,
    interval: str = Query("15min"),
) -> None:
    await websocket.accept()
    symbol = symbol.upper()
    sc = get_stream_client()
    queue: Optional[asyncio.Queue] = None

    try:
        candles = await get_intraday(symbol, interval)
        await websocket.send_json({"type": "history", "candles": candles})

        queue = await sc.subscribe(symbol)

        while True:
            try:
                tick = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_json({"type": "tick", "data": tick})
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("WS error for %s: %s", symbol, exc)
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        if queue is not None:
            sc.unsubscribe(symbol, queue)
        try:
            await websocket.close()
        except Exception:
            pass
```

- [ ] **Step 3.4: Run tests to verify they fail** (router not in main.py yet — expected)

```bash
cd backend && pytest tests/test_chart_router.py -v
```
Expected: FAIL — `/chart/history` returns 404 (router not registered)

---

## Task 4: Register chart router in `main.py`

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 4.1: Read current main.py to find where routers are registered**

```bash
grep -n "include_router" backend/app/main.py
```

- [ ] **Step 4.2: Add chart router import and registration**

In `backend/app/main.py`, add after the existing router imports:
```python
from app.routers.chart import router as chart_router
```

And after the existing `app.include_router(...)` lines:
```python
app.include_router(chart_router)
```

- [ ] **Step 4.3: Run chart router tests to verify they now pass**

```bash
cd backend && pytest tests/test_chart_router.py -v
```
Expected: 3 tests PASSED

- [ ] **Step 4.4: Run full backend test suite to verify no regressions**

```bash
cd backend && pytest -v --tb=short 2>&1 | tail -20
```
Expected: All previously passing tests still PASS

- [ ] **Step 4.5: Commit**

```bash
git add backend/app/routers/chart.py backend/app/main.py backend/tests/test_chart_router.py backend/tests/test_tradier_stream.py
git commit -m "feat(chart): add /chart/history REST + /chart/stream WebSocket endpoints"
```

---

## Task 5: Indicator library (`indicators.ts`)

**Files:**
- Create: `frontend/lib/indicators.ts`
- Create: `frontend/lib/__tests__/indicators.test.ts`

- [ ] **Step 5.1: Write failing tests**

```typescript
// frontend/lib/__tests__/indicators.test.ts
import { calcSMA, calcEMA, calcRSI, calcMACD, calcBB, calcATR, calcVWAP, Candle } from '../indicators';

const candles: Candle[] = Array.from({ length: 30 }, (_, i) => ({
  time: `2024-01-${String(i + 1).padStart(2, '0')}`,
  open: 100 + i,
  high: 102 + i,
  low: 99 + i,
  close: 101 + i,
  volume: 1000 + i * 10,
}));

describe('calcSMA', () => {
  it('returns correct number of points', () => {
    const result = calcSMA(candles, 5);
    expect(result.length).toBe(candles.length - 5 + 1);
  });
  it('first point equals average of first 5 closes', () => {
    const result = calcSMA(candles, 5);
    const expected = (101 + 102 + 103 + 104 + 105) / 5;
    expect(result[0].value).toBeCloseTo(expected, 4);
  });
  it('returns empty array when period > candles length', () => {
    expect(calcSMA(candles, 100)).toEqual([]);
  });
});

describe('calcEMA', () => {
  it('returns at least 1 point for period <= length', () => {
    expect(calcEMA(candles, 10).length).toBeGreaterThan(0);
  });
  it('returns empty array when not enough candles', () => {
    expect(calcEMA(candles.slice(0, 3), 5)).toEqual([]);
  });
});

describe('calcRSI', () => {
  it('values are between 0 and 100', () => {
    const result = calcRSI(candles, 14);
    result.forEach(p => {
      expect(p.value).toBeGreaterThanOrEqual(0);
      expect(p.value).toBeLessThanOrEqual(100);
    });
  });
});

describe('calcMACD', () => {
  it('returns macd, signal, and histogram arrays', () => {
    const result = calcMACD(candles);
    expect(Array.isArray(result.macd)).toBe(true);
    expect(Array.isArray(result.signal)).toBe(true);
    expect(Array.isArray(result.histogram)).toBe(true);
  });
});

describe('calcBB', () => {
  it('upper is always >= middle >= lower', () => {
    const result = calcBB(candles, 10, 2);
    result.upper.forEach((u, i) => {
      expect(u.value).toBeGreaterThanOrEqual(result.middle[i].value);
      expect(result.middle[i].value).toBeGreaterThanOrEqual(result.lower[i].value);
    });
  });
});

describe('calcATR', () => {
  it('all ATR values are positive', () => {
    const result = calcATR(candles, 14);
    result.forEach(p => expect(p.value).toBeGreaterThan(0));
  });
});

describe('calcVWAP', () => {
  it('returns same number of points as input', () => {
    expect(calcVWAP(candles).length).toBe(candles.length);
  });
});
```

- [ ] **Step 5.2: Run tests to verify they fail**

```bash
cd frontend && npm run test -- --testPathPattern=indicators
```
Expected: FAIL — `Cannot find module '../indicators'`

- [ ] **Step 5.3: Implement `indicators.ts`**

```typescript
// frontend/lib/indicators.ts

export interface Candle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Point {
  time: string;
  value: number;
}

export interface MACDResult {
  macd: Point[];
  signal: Point[];
  histogram: Point[];
}

export interface BBResult {
  upper: Point[];
  middle: Point[];
  lower: Point[];
}

export function calcSMA(candles: Candle[], period: number): Point[] {
  if (candles.length < period) return [];
  return candles.slice(period - 1).map((_, i) => ({
    time: candles[i + period - 1].time,
    value: candles.slice(i, i + period).reduce((s, c) => s + c.close, 0) / period,
  }));
}

export function calcEMA(candles: Candle[], period: number): Point[] {
  if (candles.length < period) return [];
  const k = 2 / (period + 1);
  const result: Point[] = [];
  let ema = candles.slice(0, period).reduce((s, c) => s + c.close, 0) / period;
  result.push({ time: candles[period - 1].time, value: ema });
  for (let i = period; i < candles.length; i++) {
    ema = candles[i].close * k + ema * (1 - k);
    result.push({ time: candles[i].time, value: ema });
  }
  return result;
}

export function calcRSI(candles: Candle[], period = 14): Point[] {
  if (candles.length < period + 1) return [];
  const result: Point[] = [];
  let avgGain = 0;
  let avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    const diff = candles[i].close - candles[i - 1].close;
    if (diff > 0) avgGain += diff;
    else avgLoss += Math.abs(diff);
  }
  avgGain /= period;
  avgLoss /= period;
  result.push({
    time: candles[period].time,
    value: avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss),
  });
  for (let i = period + 1; i < candles.length; i++) {
    const diff = candles[i].close - candles[i - 1].close;
    avgGain = (avgGain * (period - 1) + (diff > 0 ? diff : 0)) / period;
    avgLoss = (avgLoss * (period - 1) + (diff < 0 ? Math.abs(diff) : 0)) / period;
    result.push({
      time: candles[i].time,
      value: avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss),
    });
  }
  return result;
}

export function calcMACD(candles: Candle[], fast = 12, slow = 26, signalPeriod = 9): MACDResult {
  const fastEMA = calcEMA(candles, fast);
  const slowEMA = calcEMA(candles, slow);
  const slowMap = new Map(slowEMA.map(p => [p.time, p.value]));
  const fastMap = new Map(fastEMA.map(p => [p.time, p.value]));
  const macdLine: Point[] = slowEMA
    .map(p => ({ time: p.time, value: (fastMap.get(p.time) ?? p.value) - p.value }))
    .sort((a, b) => a.time.localeCompare(b.time));

  if (macdLine.length < signalPeriod) return { macd: macdLine, signal: [], histogram: [] };
  const k = 2 / (signalPeriod + 1);
  let sig = macdLine.slice(0, signalPeriod).reduce((s, p) => s + p.value, 0) / signalPeriod;
  const signalLine: Point[] = [{ time: macdLine[signalPeriod - 1].time, value: sig }];
  for (let i = signalPeriod; i < macdLine.length; i++) {
    sig = macdLine[i].value * k + sig * (1 - k);
    signalLine.push({ time: macdLine[i].time, value: sig });
  }
  const sigMap = new Map(signalLine.map(p => [p.time, p.value]));
  const histogram = macdLine
    .filter(p => sigMap.has(p.time))
    .map(p => ({ time: p.time, value: p.value - sigMap.get(p.time)! }));
  return { macd: macdLine, signal: signalLine, histogram };
}

export function calcBB(candles: Candle[], period = 20, stdDev = 2): BBResult {
  const middle = calcSMA(candles, period);
  const upper: Point[] = [];
  const lower: Point[] = [];
  middle.forEach((m, i) => {
    const slice = candles.slice(i, i + period).map(c => c.close);
    const std = Math.sqrt(slice.reduce((s, v) => s + (v - m.value) ** 2, 0) / period);
    upper.push({ time: m.time, value: m.value + stdDev * std });
    lower.push({ time: m.time, value: m.value - stdDev * std });
  });
  return { upper, middle, lower };
}

export function calcATR(candles: Candle[], period = 14): Point[] {
  if (candles.length < 2) return [];
  const tr = candles.slice(1).map((c, i) => ({
    time: c.time,
    tr: Math.max(c.high - c.low, Math.abs(c.high - candles[i].close), Math.abs(c.low - candles[i].close)),
  }));
  if (tr.length < period) return [];
  const result: Point[] = [];
  let atr = tr.slice(0, period).reduce((s, r) => s + r.tr, 0) / period;
  result.push({ time: tr[period - 1].time, value: atr });
  for (let i = period; i < tr.length; i++) {
    atr = (atr * (period - 1) + tr[i].tr) / period;
    result.push({ time: tr[i].time, value: atr });
  }
  return result;
}

export function calcVWAP(candles: Candle[]): Point[] {
  let cumPV = 0;
  let cumVol = 0;
  return candles.map(c => {
    const tp = (c.high + c.low + c.close) / 3;
    cumPV += tp * c.volume;
    cumVol += c.volume;
    return { time: c.time, value: cumVol > 0 ? cumPV / cumVol : tp };
  });
}
```

- [ ] **Step 5.4: Run tests to verify they pass**

```bash
cd frontend && npm run test -- --testPathPattern=indicators
```
Expected: 10 tests PASSED

- [ ] **Step 5.5: Typecheck**

```bash
cd frontend && npm run typecheck
```
Expected: no errors

- [ ] **Step 5.6: Commit**

```bash
git add frontend/lib/indicators.ts frontend/lib/__tests__/indicators.test.ts
git commit -m "feat(chart): add browser-side indicator calculations (SMA/EMA/RSI/MACD/BB/ATR/VWAP)"
```

---

## Task 6: WebSocket client (`chartWS.ts`) + chart store (`chartStore.ts`)

**Files:**
- Create: `frontend/lib/chartWS.ts`
- Create: `frontend/lib/chartStore.ts`

- [ ] **Step 6.1: Implement `chartWS.ts`**

```typescript
// frontend/lib/chartWS.ts
import type { Candle } from './indicators';

export type WSMessage =
  | { type: 'history'; candles: Candle[] }
  | { type: 'tick'; data: { symbol: string; price: number; volume: number; timestamp: string } }
  | { type: 'ping' }
  | { type: 'error'; message: string };

export type MessageHandler = (msg: WSMessage) => void;

const BASE_URL =
  typeof window !== 'undefined'
    ? `ws://${window.location.hostname}:8000`
    : 'ws://localhost:8000';

export class ChartWSClient {
  private ws: WebSocket | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private backoff = 1000;
  private destroyed = false;
  private handlers = new Set<MessageHandler>();

  constructor(
    public readonly symbol: string,
    public readonly interval: string = '15min',
    private readonly baseUrl: string = BASE_URL,
  ) {}

  connect(): void {
    if (this.destroyed) return;
    const url = `${this.baseUrl}/chart/stream/${encodeURIComponent(this.symbol)}?interval=${this.interval}`;
    this.ws = new WebSocket(url);

    this.ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data as string) as WSMessage;
        this.handlers.forEach(h => h(msg));
      } catch { /* ignore */ }
    };

    this.ws.onclose = () => {
      if (!this.destroyed) {
        this.timer = setTimeout(() => {
          this.backoff = Math.min(this.backoff * 2, 30_000);
          this.connect();
        }, this.backoff);
      }
    };

    this.ws.onerror = () => this.ws?.close();
  }

  onMessage(fn: MessageHandler): () => void {
    this.handlers.add(fn);
    return () => this.handlers.delete(fn);
  }

  destroy(): void {
    this.destroyed = true;
    if (this.timer) clearTimeout(this.timer);
    this.ws?.close();
    this.ws = null;
  }
}
```

- [ ] **Step 6.2: Implement `chartStore.ts`**

```typescript
// frontend/lib/chartStore.ts
'use client';
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type Interval = '1min' | '5min' | '15min' | '1h' | '4h' | '1D' | '1W';
export type ChartType = 'candle' | 'bar' | 'line';

export interface IndicatorConfig {
  id: string;           // e.g. 'ema-20'
  type: string;         // 'SMA' | 'EMA' | 'RSI' | 'MACD' | 'BB' | 'ATR' | 'VWAP'
  params: Record<string, number>;  // e.g. { period: 20 }
  pane: 'main' | 'sub'; // main = overlay on candles, sub = separate pane
  color: string;
}

export interface PaneLayout {
  mainHeightPct: number;   // 0-100, percentage of total chart height
  subPanes: { id: string; heightPct: number }[];
}

interface ChartState {
  symbol: string;
  interval: Interval;
  chartType: ChartType;
  activeIndicators: IndicatorConfig[];
  paneLayout: PaneLayout;
  setSymbol: (s: string) => void;
  setInterval: (i: Interval) => void;
  setChartType: (t: ChartType) => void;
  addIndicator: (cfg: IndicatorConfig) => void;
  removeIndicator: (id: string) => void;
  updateIndicator: (id: string, patch: Partial<IndicatorConfig>) => void;
  setPaneLayout: (layout: PaneLayout) => void;
}

const DEFAULT_INDICATORS: IndicatorConfig[] = [
  { id: 'ema-20',  type: 'EMA',  params: { period: 20 },  pane: 'main', color: '#4f8ef7' },
  { id: 'ema-50',  type: 'EMA',  params: { period: 50 },  pane: 'main', color: '#e0a030' },
  { id: 'vol',     type: 'VOL',  params: {},               pane: 'sub',  color: '#4a4a6a' },
  { id: 'rsi-14',  type: 'RSI',  params: { period: 14 },  pane: 'sub',  color: '#70b070' },
];

export const useChartStore = create<ChartState>()(
  persist(
    (set) => ({
      symbol: 'AAPL',
      interval: '1D',
      chartType: 'candle',
      activeIndicators: DEFAULT_INDICATORS,
      paneLayout: { mainHeightPct: 60, subPanes: [{ id: 'vol', heightPct: 15 }, { id: 'rsi-14', heightPct: 25 }] },

      setSymbol: (symbol) => set({ symbol }),
      setInterval: (interval) => set({ interval }),
      setChartType: (chartType) => set({ chartType }),
      addIndicator: (cfg) => set(s => ({ activeIndicators: [...s.activeIndicators, cfg] })),
      removeIndicator: (id) => set(s => ({ activeIndicators: s.activeIndicators.filter(i => i.id !== id) })),
      updateIndicator: (id, patch) =>
        set(s => ({ activeIndicators: s.activeIndicators.map(i => (i.id === id ? { ...i, ...patch } : i)) })),
      setPaneLayout: (paneLayout) => set({ paneLayout }),
    }),
    {
      name: 'bamendjou:chart',
      version: 1,
    },
  ),
);
```

- [ ] **Step 6.3: Typecheck**

```bash
cd frontend && npm run typecheck
```
Expected: no errors

- [ ] **Step 6.4: Commit**

```bash
git add frontend/lib/chartWS.ts frontend/lib/chartStore.ts
git commit -m "feat(chart): add ChartWSClient and chartStore"
```

---

## Task 7: `ChartPane` component

**Files:**
- Create: `frontend/components/organisms/ChartPane/index.tsx`
- Create: `frontend/components/organisms/ChartPane/ChartPane.module.css`

- [ ] **Step 7.1: Implement `ChartPane`**

This component wraps a single lightweight-charts `IChartApi` instance. It handles resize via `ResizeObserver` and exposes the chart API via a ref.

```tsx
// frontend/components/organisms/ChartPane/index.tsx
'use client';
import { useEffect, useRef, useCallback } from 'react';
import {
  createChart,
  IChartApi,
  ISeriesApi,
  CandlestickData,
  LineData,
  HistogramData,
  ColorType,
  CrosshairMode,
} from 'lightweight-charts';
import type { Candle, Point } from '@/lib/indicators';
import styles from './ChartPane.module.css';

export interface SeriesConfig {
  id: string;
  type: 'Candlestick' | 'Line' | 'Histogram' | 'Bar';
  data: Candle[] | Point[];
  color?: string;
  priceScaleId?: string;
}

interface Props {
  series: SeriesConfig[];
  onCrosshairMove?: (time: string | null, values: Record<string, number>) => void;
  height?: number;
}

export default function ChartPane({ series, onCrosshairMove, height = 300 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<Map<string, ISeriesApi<'Candlestick' | 'Line' | 'Histogram' | 'Bar'>>>(new Map());

  const initChart = useCallback(() => {
    if (!containerRef.current) return;
    chartRef.current = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#0b0b14' },
        textColor: '#888',
      },
      grid: {
        vertLines: { color: '#1e1e35' },
        horzLines: { color: '#1e1e35' },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#1e1e35' },
      timeScale: { borderColor: '#1e1e35', timeVisible: true },
      width: containerRef.current.clientWidth,
      height,
    });

    if (onCrosshairMove) {
      chartRef.current.subscribeCrosshairMove((param) => {
        if (!param.time) { onCrosshairMove(null, {}); return; }
        const values: Record<string, number> = {};
        seriesRef.current.forEach((s, id) => {
          const v = param.seriesData.get(s);
          if (v) values[id] = 'close' in v ? (v as CandlestickData).close : (v as LineData).value;
        });
        onCrosshairMove(String(param.time), values);
      });
    }
  }, [height, onCrosshairMove]);

  useEffect(() => {
    initChart();
    const observer = new ResizeObserver(() => {
      if (chartRef.current && containerRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    });
    if (containerRef.current) observer.observe(containerRef.current);
    return () => {
      observer.disconnect();
      chartRef.current?.remove();
      chartRef.current = null;
    };
  }, [initChart]);

  useEffect(() => {
    if (!chartRef.current) return;
    const chart = chartRef.current;

    // Remove series not in current config
    seriesRef.current.forEach((s, id) => {
      if (!series.find(c => c.id === id)) {
        chart.removeSeries(s);
        seriesRef.current.delete(id);
      }
    });

    // Add or update series
    series.forEach((cfg) => {
      let s = seriesRef.current.get(cfg.id);
      if (!s) {
        if (cfg.type === 'Candlestick') {
          s = chart.addCandlestickSeries({ upColor: '#4caf50', downColor: '#e05050', borderVisible: false, wickUpColor: '#4caf50', wickDownColor: '#e05050' });
        } else if (cfg.type === 'Histogram') {
          s = chart.addHistogramSeries({ color: cfg.color ?? '#4a4a6a', priceScaleId: cfg.priceScaleId ?? 'right' });
        } else {
          s = chart.addLineSeries({ color: cfg.color ?? '#4f8ef7', lineWidth: 1, priceScaleId: cfg.priceScaleId ?? 'right' });
        }
        seriesRef.current.set(cfg.id, s);
      }
      if (cfg.type === 'Candlestick') {
        (s as ISeriesApi<'Candlestick'>).setData(
          (cfg.data as Candle[]).map(c => ({ time: c.time as any, open: c.open, high: c.high, low: c.low, close: c.close }))
        );
      } else {
        (s as ISeriesApi<'Line' | 'Histogram'>).setData(
          (cfg.data as Point[]).map(p => ({ time: p.time as any, value: p.value }))
        );
      }
    });
  }, [series]);

  return <div ref={containerRef} className={styles.pane} style={{ height }} />;
}
```

```css
/* frontend/components/organisms/ChartPane/ChartPane.module.css */
.pane {
  width: 100%;
  flex-shrink: 0;
}
```

- [ ] **Step 7.2: Typecheck**

```bash
cd frontend && npm run typecheck
```
Expected: no errors

- [ ] **Step 7.3: Commit**

```bash
git add frontend/components/organisms/ChartPane/
git commit -m "feat(chart): add ChartPane component wrapping lightweight-charts v5"
```

---

## Task 8: `DrawingToolbar`, `ChartTopBar`, `ChartRightPanel`

**Files:**
- Create: `frontend/components/organisms/DrawingToolbar/index.tsx` + `.module.css`
- Create: `frontend/components/organisms/ChartTopBar/index.tsx` + `.module.css`
- Create: `frontend/components/organisms/ChartRightPanel/index.tsx` + `.module.css`

- [ ] **Step 8.1: Implement `DrawingToolbar`**

```tsx
// frontend/components/organisms/DrawingToolbar/index.tsx
'use client';
import styles from './DrawingToolbar.module.css';

export type DrawingTool = 'cursor' | 'trendline' | 'fib' | 'rect' | 'text' | 'measure' | 'zoom';

interface Props {
  active: DrawingTool;
  onChange: (t: DrawingTool) => void;
}

const TOOLS: { id: DrawingTool; label: string; icon: string }[] = [
  { id: 'cursor',    label: 'Cursor',      icon: '✛' },
  { id: 'trendline', label: 'Trendline',   icon: '╱' },
  { id: 'fib',       label: 'Fibonacci',   icon: 'Φ' },
  { id: 'rect',      label: 'Rectangle',   icon: '□' },
  { id: 'text',      label: 'Text',        icon: 'T' },
  { id: 'measure',   label: 'Measure',     icon: '↔' },
  { id: 'zoom',      label: 'Zoom',        icon: '⊕' },
];

export default function DrawingToolbar({ active, onChange }: Props) {
  return (
    <div className={styles.toolbar}>
      {TOOLS.map(t => (
        <button
          key={t.id}
          className={`${styles.tool} ${active === t.id ? styles.active : ''}`}
          title={t.label}
          onClick={() => onChange(t.id)}
        >
          {t.icon}
        </button>
      ))}
    </div>
  );
}
```

```css
/* frontend/components/organisms/DrawingToolbar/DrawingToolbar.module.css */
.toolbar {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 6px 0;
  width: 36px;
  background: var(--bg-nav);
  border-right: 1px solid var(--border-subtle);
  flex-shrink: 0;
}

.tool {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 14px;
  transition: background 0.1s;
}

.tool:hover {
  background: var(--bg-surface);
  color: var(--text-primary);
}

.tool.active {
  background: var(--bg-surface);
  color: var(--color-pass);
}
```

- [ ] **Step 8.2: Implement `ChartTopBar`**

```tsx
// frontend/components/organisms/ChartTopBar/index.tsx
'use client';
import { useRouter } from 'next/navigation';
import { useChartStore, Interval, ChartType } from '@/lib/chartStore';
import styles from './ChartTopBar.module.css';

const INTERVALS: Interval[] = ['1min', '5min', '15min', '1h', '4h', '1D', '1W'];

interface Props {
  onToggleIndicators: () => void;
}

export default function ChartTopBar({ onToggleIndicators }: Props) {
  const { symbol, interval, chartType, setSymbol, setInterval, setChartType } = useChartStore();
  const router = useRouter();

  const handleSymbolKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      setSymbol(e.currentTarget.value.toUpperCase().trim());
    }
  };

  const handlePopOut = () => {
    window.open(`/chart/standalone?symbol=${symbol}&interval=${interval}`, '_blank', 'width=1400,height=900');
  };

  return (
    <div className={styles.bar}>
      <input
        className={styles.symbolInput}
        defaultValue={symbol}
        onKeyDown={handleSymbolKeyDown}
        onBlur={(e) => setSymbol(e.target.value.toUpperCase().trim())}
        aria-label="Symbol"
      />

      <div className={styles.intervals}>
        {INTERVALS.map(i => (
          <button
            key={i}
            className={`${styles.tf} ${interval === i ? styles.tfActive : ''}`}
            onClick={() => setInterval(i)}
          >
            {i}
          </button>
        ))}
      </div>

      <select
        className={styles.chartType}
        value={chartType}
        onChange={(e) => setChartType(e.target.value as ChartType)}
        aria-label="Chart type"
      >
        <option value="candle">Candles</option>
        <option value="bar">Bars</option>
        <option value="line">Line</option>
      </select>

      <button className={styles.btn} onClick={onToggleIndicators}>Indicators</button>

      <div className={styles.spacer} />

      <button className={styles.popOut} onClick={handlePopOut} title="Open in new window">
        ⧉ Pop out
      </button>
    </div>
  );
}
```

```css
/* frontend/components/organisms/ChartTopBar/ChartTopBar.module.css */
.bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 10px;
  height: 36px;
  background: var(--bg-nav);
  border-bottom: 1px solid var(--border-subtle);
  flex-shrink: 0;
}

.symbolInput {
  width: 72px;
  padding: 3px 8px;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 500;
}

.intervals { display: flex; gap: 2px; }

.tf {
  padding: 2px 6px;
  font-size: 11px;
  background: transparent;
  border: none;
  border-radius: 3px;
  color: var(--text-secondary);
  cursor: pointer;
}

.tf:hover { background: var(--bg-surface); color: var(--text-primary); }

.tfActive {
  background: color-mix(in srgb, var(--pass) 15%, var(--bg-surface));
  color: var(--color-pass);
}

.chartType {
  padding: 3px 6px;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
}

.btn {
  padding: 3px 8px;
  font-size: 11px;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  color: var(--text-secondary);
  cursor: pointer;
}

.btn:hover { color: var(--text-primary); }

.spacer { flex: 1; }

.popOut {
  padding: 3px 8px;
  font-size: 11px;
  background: transparent;
  border: 1px solid color-mix(in srgb, var(--pass) 40%, transparent);
  border-radius: 4px;
  color: var(--color-pass);
  cursor: pointer;
}
```

- [ ] **Step 8.3: Implement `ChartRightPanel`**

```tsx
// frontend/components/organisms/ChartRightPanel/index.tsx
'use client';
import { useState } from 'react';
import { useWatchlistStore } from '@/lib/watchlistStore';
import WatchStar from '@/components/atoms/WatchStar';
import { Text } from '@/components/primitives/Text';
import styles from './ChartRightPanel.module.css';

type Tab = 'watchlist' | 'data';

interface DataValues {
  time: string | null;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  volume?: number;
  indicators: Record<string, number>;
}

interface Props {
  crosshairData: DataValues;
}

export default function ChartRightPanel({ crosshairData }: Props) {
  const [tab, setTab] = useState<Tab>('watchlist');
  const { symbols } = useWatchlistStore();

  return (
    <div className={styles.panel}>
      <div className={styles.tabs}>
        {(['watchlist', 'data'] as Tab[]).map(t => (
          <button
            key={t}
            className={`${styles.tab} ${tab === t ? styles.tabActive : ''}`}
            onClick={() => setTab(t)}
          >
            {t === 'watchlist' ? 'Watchlist' : 'Data'}
          </button>
        ))}
      </div>

      {tab === 'watchlist' && (
        <div className={styles.list}>
          {symbols.length === 0 && (
            <Text size={11} tone="dim" className={styles.empty}>No symbols watched</Text>
          )}
          {symbols.map(sym => (
            <div key={sym} className={styles.row}>
              <WatchStar symbol={sym} />
              <Text size={12} tone="primary">{sym}</Text>
            </div>
          ))}
        </div>
      )}

      {tab === 'data' && (
        <div className={styles.dataPanel}>
          {crosshairData.time ? (
            <>
              <Text size={10} tone="dim">{crosshairData.time}</Text>
              {crosshairData.open !== undefined && (
                <div className={styles.ohlcv}>
                  <span>O <b>{crosshairData.open?.toFixed(2)}</b></span>
                  <span>H <b>{crosshairData.high?.toFixed(2)}</b></span>
                  <span>L <b>{crosshairData.low?.toFixed(2)}</b></span>
                  <span>C <b>{crosshairData.close?.toFixed(2)}</b></span>
                </div>
              )}
              {Object.entries(crosshairData.indicators).map(([id, val]) => (
                <div key={id} className={styles.indicatorVal}>
                  <Text size={10} tone="secondary">{id}</Text>
                  <Text size={10} tone="primary">{val.toFixed(4)}</Text>
                </div>
              ))}
            </>
          ) : (
            <Text size={11} tone="dim">Hover over chart</Text>
          )}
        </div>
      )}
    </div>
  );
}
```

```css
/* frontend/components/organisms/ChartRightPanel/ChartRightPanel.module.css */
.panel {
  width: 180px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg-nav);
  border-left: 1px solid var(--border-subtle);
}

.tabs {
  display: flex;
  border-bottom: 1px solid var(--border-subtle);
}

.tab {
  flex: 1;
  padding: 6px 0;
  font-size: 10px;
  background: transparent;
  border: none;
  color: var(--text-dim);
  cursor: pointer;
}

.tabActive {
  color: var(--color-pass);
  border-bottom: 2px solid var(--color-pass);
}

.list { flex: 1; overflow-y: auto; padding: 4px 0; }

.row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border-bottom: 1px solid var(--border-subtle);
}

.empty { padding: 8px; }

.dataPanel { padding: 8px; display: flex; flex-direction: column; gap: 4px; }

.ohlcv { display: flex; flex-wrap: wrap; gap: 6px; font-size: 10px; color: var(--text-secondary); }

.indicatorVal { display: flex; justify-content: space-between; }
```

- [ ] **Step 8.4: Typecheck**

```bash
cd frontend && npm run typecheck
```
Expected: no errors

- [ ] **Step 8.5: Commit**

```bash
git add frontend/components/organisms/DrawingToolbar/ frontend/components/organisms/ChartTopBar/ frontend/components/organisms/ChartRightPanel/
git commit -m "feat(chart): add DrawingToolbar, ChartTopBar, ChartRightPanel components"
```

---

## Task 9: `IndicatorPanel` + `ChartWorkspace`

**Files:**
- Create: `frontend/components/organisms/IndicatorPanel/index.tsx` + `.module.css`
- Create: `frontend/components/organisms/ChartWorkspace/index.tsx` + `.module.css`

- [ ] **Step 9.1: Implement `IndicatorPanel`**

```tsx
// frontend/components/organisms/IndicatorPanel/index.tsx
'use client';
import { useState } from 'react';
import { useChartStore, IndicatorConfig } from '@/lib/chartStore';
import { Text } from '@/components/primitives/Text';
import styles from './IndicatorPanel.module.css';

const AVAILABLE = [
  { type: 'SMA',  label: 'SMA',            pane: 'main' as const, defaultParams: { period: 20 }, color: '#a0a0ff' },
  { type: 'EMA',  label: 'EMA',            pane: 'main' as const, defaultParams: { period: 20 }, color: '#4f8ef7' },
  { type: 'BB',   label: 'Bollinger Bands',pane: 'main' as const, defaultParams: { period: 20, stdDev: 2 }, color: '#c07070' },
  { type: 'VWAP', label: 'VWAP',           pane: 'main' as const, defaultParams: {}, color: '#70c0c0' },
  { type: 'RSI',  label: 'RSI',            pane: 'sub'  as const, defaultParams: { period: 14 }, color: '#70b070' },
  { type: 'MACD', label: 'MACD',           pane: 'sub'  as const, defaultParams: { fast: 12, slow: 26, signal: 9 }, color: '#c080c0' },
  { type: 'ATR',  label: 'ATR',            pane: 'sub'  as const, defaultParams: { period: 14 }, color: '#c0a040' },
  { type: 'VOL',  label: 'Volume',         pane: 'sub'  as const, defaultParams: {}, color: '#4a4a6a' },
];

interface Props { onClose: () => void; }

export default function IndicatorPanel({ onClose }: Props) {
  const { activeIndicators, addIndicator, removeIndicator } = useChartStore();
  const [search, setSearch] = useState('');

  const filtered = AVAILABLE.filter(a =>
    a.label.toLowerCase().includes(search.toLowerCase())
  );

  const isActive = (type: string) => activeIndicators.some(i => i.type === type);

  const toggle = (def: typeof AVAILABLE[0]) => {
    if (isActive(def.type)) {
      const existing = activeIndicators.find(i => i.type === def.type);
      if (existing) removeIndicator(existing.id);
    } else {
      const cfg: IndicatorConfig = {
        id: `${def.type.toLowerCase()}-${Date.now()}`,
        type: def.type,
        params: def.defaultParams,
        pane: def.pane,
        color: def.color,
      };
      addIndicator(cfg);
    }
  };

  return (
    <div className={styles.panel}>
      <div className={styles.header}>
        <Text size={13} tone="primary" weight={500}>Indicators</Text>
        <button className={styles.close} onClick={onClose}>✕</button>
      </div>
      <input
        className={styles.search}
        placeholder="Search…"
        value={search}
        onChange={e => setSearch(e.target.value)}
      />
      <div className={styles.list}>
        {filtered.map(def => (
          <button
            key={def.type}
            className={`${styles.item} ${isActive(def.type) ? styles.active : ''}`}
            onClick={() => toggle(def)}
          >
            <span className={styles.dot} style={{ background: def.color }} />
            <Text size={12} tone={isActive(def.type) ? 'primary' : 'secondary'}>{def.label}</Text>
            <span className={styles.check}>{isActive(def.type) ? '✓' : '+'}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
```

```css
/* frontend/components/organisms/IndicatorPanel/IndicatorPanel.module.css */
.panel {
  position: absolute;
  top: 36px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 100;
  width: 280px;
  background: var(--bg-nav);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.4);
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px 6px;
}

.close {
  background: transparent;
  border: none;
  color: var(--text-dim);
  cursor: pointer;
  font-size: 12px;
}

.search {
  width: calc(100% - 24px);
  margin: 0 12px 6px;
  padding: 5px 8px;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 11px;
}

.list { max-height: 320px; overflow-y: auto; padding-bottom: 4px; }

.item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 12px;
  background: transparent;
  border: none;
  cursor: pointer;
  text-align: left;
}

.item:hover { background: var(--bg-surface); }
.item.active { background: color-mix(in srgb, var(--pass) 8%, transparent); }

.dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }

.check { margin-left: auto; font-size: 11px; color: var(--color-pass); }
```

- [ ] **Step 9.2: Implement `ChartWorkspace` — the root layout component**

```tsx
// frontend/components/organisms/ChartWorkspace/index.tsx
'use client';
import { useEffect, useRef, useState, useCallback } from 'react';
import { useSearchParams } from 'next/navigation';
import { useChartStore } from '@/lib/chartStore';
import { ChartWSClient, WSMessage } from '@/lib/chartWS';
import type { Candle } from '@/lib/indicators';
import {
  calcEMA, calcSMA, calcRSI, calcMACD, calcBB, calcATR, calcVWAP,
} from '@/lib/indicators';
import type { SeriesConfig } from '@/components/organisms/ChartPane';
import ChartPane from '@/components/organisms/ChartPane';
import ChartTopBar from '@/components/organisms/ChartTopBar';
import DrawingToolbar from '@/components/organisms/DrawingToolbar';
import IndicatorPanel from '@/components/organisms/IndicatorPanel';
import ChartRightPanel from '@/components/organisms/ChartRightPanel';
import type { DrawingTool } from '@/components/organisms/DrawingToolbar';
import styles from './ChartWorkspace.module.css';

function buildSeries(candles: Candle[], indicators: ReturnType<typeof useChartStore>['activeIndicators']): SeriesConfig[] {
  const series: SeriesConfig[] = [
    { id: 'candles', type: 'Candlestick', data: candles },
  ];
  for (const ind of indicators) {
    if (ind.pane !== 'main') continue;
    if (ind.type === 'EMA') series.push({ id: ind.id, type: 'Line', data: calcEMA(candles, ind.params.period ?? 20), color: ind.color });
    if (ind.type === 'SMA') series.push({ id: ind.id, type: 'Line', data: calcSMA(candles, ind.params.period ?? 20), color: ind.color });
    if (ind.type === 'VWAP') series.push({ id: ind.id, type: 'Line', data: calcVWAP(candles), color: ind.color });
    if (ind.type === 'BB') {
      const bb = calcBB(candles, ind.params.period ?? 20, ind.params.stdDev ?? 2);
      series.push({ id: `${ind.id}-upper`, type: 'Line', data: bb.upper, color: ind.color });
      series.push({ id: `${ind.id}-mid`,   type: 'Line', data: bb.middle, color: ind.color });
      series.push({ id: `${ind.id}-lower`, type: 'Line', data: bb.lower, color: ind.color });
    }
  }
  return series;
}

function buildSubSeries(candles: Candle[], ind: ReturnType<typeof useChartStore>['activeIndicators'][0]): SeriesConfig[] {
  if (ind.type === 'VOL')  return [{ id: 'vol',  type: 'Histogram', data: candles.map(c => ({ time: c.time, value: c.volume })), color: ind.color }];
  if (ind.type === 'RSI')  return [{ id: 'rsi',  type: 'Line', data: calcRSI(candles, ind.params.period ?? 14), color: ind.color }];
  if (ind.type === 'ATR')  return [{ id: 'atr',  type: 'Line', data: calcATR(candles, ind.params.period ?? 14), color: ind.color }];
  if (ind.type === 'MACD') {
    const m = calcMACD(candles, ind.params.fast ?? 12, ind.params.slow ?? 26, ind.params.signal ?? 9);
    return [
      { id: 'macd-line', type: 'Line', data: m.macd, color: ind.color },
      { id: 'macd-sig',  type: 'Line', data: m.signal, color: '#e0a030' },
      { id: 'macd-hist', type: 'Histogram', data: m.histogram, color: '#4a4a6a' },
    ];
  }
  return [];
}

export default function ChartWorkspace() {
  const params = useSearchParams();
  const { symbol, interval, activeIndicators, setSymbol, setInterval } = useChartStore();
  const [candles, setCandles] = useState<Candle[]>([]);
  const [drawingTool, setDrawingTool] = useState<DrawingTool>('cursor');
  const [showIndicators, setShowIndicators] = useState(false);
  const [crosshair, setCrosshair] = useState({ time: null as string | null, indicators: {} as Record<string, number> });
  const wsRef = useRef<ChartWSClient | null>(null);

  // Handle deep-link query param
  useEffect(() => {
    const sym = params?.get('symbol');
    const iv = params?.get('interval');
    if (sym) setSymbol(sym.toUpperCase());
    if (iv) setInterval(iv as any);
  }, [params, setSymbol, setInterval]);

  // Connect/reconnect WS when symbol or interval changes
  useEffect(() => {
    wsRef.current?.destroy();
    const client = new ChartWSClient(symbol, interval === '1D' ? 'daily' : interval === '1W' ? 'weekly' : interval);
    const remove = client.onMessage((msg: WSMessage) => {
      if (msg.type === 'history') setCandles(msg.candles);
      if (msg.type === 'tick') {
        setCandles(prev => {
          if (!prev.length) return prev;
          const last = prev[prev.length - 1];
          if (last.time === msg.data.timestamp) {
            const updated = { ...last, close: msg.data.price, high: Math.max(last.high, msg.data.price), low: Math.min(last.low, msg.data.price), volume: last.volume + msg.data.volume };
            return [...prev.slice(0, -1), updated];
          }
          return [...prev, { time: msg.data.timestamp, open: msg.data.price, high: msg.data.price, low: msg.data.price, close: msg.data.price, volume: msg.data.volume }];
        });
      }
    });
    client.connect();
    wsRef.current = client;
    return () => { remove(); client.destroy(); };
  }, [symbol, interval]);

  const mainSeries = buildSeries(candles, activeIndicators);
  const subIndicators = activeIndicators.filter(i => i.pane === 'sub');

  return (
    <div className={styles.workspace}>
      <ChartTopBar onToggleIndicators={() => setShowIndicators(v => !v)} />
      {showIndicators && (
        <IndicatorPanel onClose={() => setShowIndicators(false)} />
      )}
      <div className={styles.body}>
        <DrawingToolbar active={drawingTool} onChange={setDrawingTool} />
        <div className={styles.charts}>
          <ChartPane
            series={mainSeries}
            height={320}
            onCrosshairMove={(time, values) => setCrosshair({ time, indicators: values })}
          />
          {subIndicators.map(ind => (
            <ChartPane
              key={ind.id}
              series={buildSubSeries(candles, ind)}
              height={100}
            />
          ))}
        </div>
        <ChartRightPanel crosshairData={{ time: crosshair.time, indicators: crosshair.indicators }} />
      </div>
    </div>
  );
}
```

```css
/* frontend/components/organisms/ChartWorkspace/ChartWorkspace.module.css */
.workspace {
  display: flex;
  flex-direction: column;
  height: 100%;
  position: relative;
  background: var(--bg-base);
  overflow: hidden;
}

.body {
  flex: 1;
  display: flex;
  overflow: hidden;
  min-height: 0;
}

.charts {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}
```

- [ ] **Step 9.3: Typecheck**

```bash
cd frontend && npm run typecheck
```
Expected: no errors

- [ ] **Step 9.4: Commit**

```bash
git add frontend/components/organisms/IndicatorPanel/ frontend/components/organisms/ChartWorkspace/
git commit -m "feat(chart): add IndicatorPanel and ChartWorkspace root layout"
```

---

## Task 10: Chart routes + NavRail item

**Files:**
- Create: `frontend/app/(frame)/chart/page.tsx` + `page.module.css`
- Create: `frontend/app/chart/standalone/layout.tsx`
- Create: `frontend/app/chart/standalone/page.tsx`
- Modify: NavRail component (find exact path with `grep -r "Calendar" frontend/components --include="*.tsx" -l`)

- [ ] **Step 10.1: Find the NavRail file**

```bash
grep -r "Calendar" frontend/components --include="*.tsx" -l
grep -r "NavRail\|navrail\|nav-rail" frontend/app --include="*.tsx" -l
```

- [ ] **Step 10.2: Create chart page (in-frame)**

```tsx
// frontend/app/(frame)/chart/page.tsx
import ChartWorkspace from '@/components/organisms/ChartWorkspace';
import styles from './page.module.css';

export default function ChartPage() {
  return (
    <main className={styles.page}>
      <ChartWorkspace />
    </main>
  );
}
```

```css
/* frontend/app/(frame)/chart/page.module.css */
.page {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
```

- [ ] **Step 10.3: Create standalone layout (no NavRail)**

```tsx
// frontend/app/chart/standalone/layout.tsx
import type { ReactNode } from 'react';
import '../../../app/globals.css';

export default function StandaloneLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body style={{ margin: 0, background: '#0b0b14', height: '100vh', overflow: 'hidden' }}>
        {children}
      </body>
    </html>
  );
}
```

```tsx
// frontend/app/chart/standalone/page.tsx
import ChartWorkspace from '@/components/organisms/ChartWorkspace';

export default function StandalonePage() {
  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
      <ChartWorkspace />
    </div>
  );
}
```

- [ ] **Step 10.4: Add Chart item to NavRail**

Open the NavRail file found in Step 10.1. Find the Calendar nav item and add a Chart item immediately after it. Follow the exact pattern of existing nav items (icon + label + href). The icon to use: `📈` or an SVG equivalent matching the existing icon style.

Add the route entry:
```tsx
{ href: '/chart', label: 'Chart', icon: <ChartIcon /> }  // insert after Calendar, before Alerts
```

Use whatever icon component pattern already exists in the NavRail for other items. Do not invent a new pattern.

- [ ] **Step 10.5: Typecheck**

```bash
cd frontend && npm run typecheck
```
Expected: no errors

- [ ] **Step 10.6: Commit**

```bash
git add frontend/app/\(frame\)/chart/ frontend/app/chart/ 
git commit -m "feat(chart): add /chart route, /chart/standalone pop-out, and NavRail item"
```

---

## Task 11: Deep-link wiring

**Files:**
- Modify: `frontend/app/(frame)/screener/step-4-ranking/page.tsx`
- Modify: `frontend/app/(frame)/screener/step-6-contracts/page.tsx` (or equivalent path — check with `ls frontend/app/(frame)/screener/`)
- Modify: `frontend/app/(frame)/watchlist/page.tsx`

- [ ] **Step 11.1: Verify file paths**

```bash
ls "frontend/app/(frame)/screener/"
ls "frontend/app/(frame)/watchlist/"
```

- [ ] **Step 11.2: Add chart deep-link to Step 4 ranking table**

In the ranking table rows, add a chart icon button. Find the row render (look for `map(` over candidates or `watchlist`). Add after the existing row actions:

```tsx
import { useRouter } from 'next/navigation';

// Inside the row render:
const router = useRouter();

// Add this button to each row's actions:
<button
  className={styles.chartLink}
  title="Open in Chart"
  onClick={() => router.push(`/chart?symbol=${row.symbol}`)}
>
  📈
</button>
```

Add to the CSS module:
```css
.chartLink {
  background: transparent;
  border: none;
  cursor: pointer;
  font-size: 13px;
  opacity: 0.5;
  padding: 2px 4px;
}
.chartLink:hover { opacity: 1; }
```

- [ ] **Step 11.3: Add chart deep-link to Step 6 contracts table**

Same pattern as Step 11.2 — find the contract row render and add the chart link button, routing to `/chart?symbol=${contract.symbol}`.

- [ ] **Step 11.4: Add chart deep-link to Watchlist page**

Find where watchlist rows are rendered in `frontend/app/(frame)/watchlist/page.tsx`. Add the same chart link button routing to `/chart?symbol=${row.symbol}`.

- [ ] **Step 11.5: Typecheck**

```bash
cd frontend && npm run typecheck
```
Expected: no errors

- [ ] **Step 11.6: Commit**

```bash
git add "frontend/app/(frame)/screener/" "frontend/app/(frame)/watchlist/page.tsx"
git commit -m "feat(chart): add chart deep-links from Step 4, Step 6, and Watchlist"
```

---

## Task 12: Final verification

- [ ] **Step 12.1: Run full backend test suite**

```bash
cd backend && pytest -v --tb=short 2>&1 | tail -30
```
Expected: all tests PASS (including existing tests — no regressions)

- [ ] **Step 12.2: Run frontend typecheck**

```bash
cd frontend && npm run typecheck
```
Expected: 0 errors

- [ ] **Step 12.3: Run frontend tests**

```bash
cd frontend && npm run test
```
Expected: all tests PASS

- [ ] **Step 12.4: Start both servers and verify manually**

```bash
# Terminal 1 — backend
cd backend && uvicorn app.main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend && npm run dev
```

Verify:
1. Navigate to `http://localhost:3001/chart` — chart page loads
2. NavRail shows Chart between Calendar and Alerts
3. Chart loads AAPL candles (history message received)
4. Switch timeframe from 1D to 1h — chart reloads
5. Add RSI indicator — RSI pane appears below candles
6. Click "⧉ Pop out" — opens `http://localhost:3001/chart/standalone?symbol=AAPL` in new window
7. Go to Screener Step 4 — chart icon visible on rows, click opens `/chart?symbol=AAPL`
8. Go to Watchlist — chart icon visible, click opens chart

- [ ] **Step 12.5: Final commit**

```bash
git add .
git commit -m "feat(chart): Phase 1 complete — chart workspace with WebSocket data, indicators, and deep-links"
```
