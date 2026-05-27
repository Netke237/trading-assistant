# Chart Feature Design — Bamendjou

**Date:** 2026-05-27  
**Status:** Approved for implementation  
**Scope:** Phase 1 only (Chart Workspace + Data + Common Indicators)

---

## Context

Kenneth wants a TradingView SuperChart–equivalent built into Bamendjou using lightweight-charts v5 (already in stack). The feature covers visualization, market-structure analysis, and alert delivery — but explicitly excludes trading/order execution. Delivery is phased: this spec covers Phase 1 only.

---

## 4-Phase Delivery Map

| Phase | Scope | Status |
|---|---|---|
| **1** | Chart page, WebSocket data pipeline, common indicators, drawing tools, multi-pane | **This spec** |
| 2 | Market structure overlays: FVG, BOS, CHoCH, Order Blocks, divergence, Fibonacci, confluence score | Future spec |
| 3 | Alert engine: UI rule builder, compound rules, candle-close trigger, cooldown/dedup, in-app history | Future spec |
| 4 | Notifications: Gmail + Telegram (bot-to-chat and bot-to-group), backend sync for rules | Future spec |

---

## Phase 1 Requirements

### Navigation
- Add **Chart** nav item to the NavRail between Calendar and Alerts
- Route: `app/(frame)/chart/page.tsx`
- Pop-out button in chart top bar opens `/chart/standalone` in a new browser window (no NavRail/TopBar) — no separate port needed

### Chart workspace layout
- **Top bar:** Symbol picker · Timeframe strip (1m / 5m / 15m / 1h / 4h / 1D / 1W) · Chart type · Indicators button · Pop-out button
- **Left sidebar:** Drawing tools (trendline, fib retracement, shapes, text, measure, zoom, magnet, lock/hide/delete)
- **Main area:** Multi-pane lightweight-charts (candles + optional RSI pane + optional MACD pane, each resizable)
- **Right panel:** Watchlist tab + Data tab

### Deep-links
- Screener Step 4 ranking table: row action → opens `/chart?symbol=AAPL`
- Screener Step 6 contracts table: row action → same
- Watchlist page: symbol row action → same
- Chart page reads `?symbol=` query param on mount and preloads that symbol

### Common indicators (all computed in browser)
SMA, EMA, VWAP, RSI, MACD, Bollinger Bands, ATR, Volume

### Persistence
- Indicator settings, active timeframe, drawing objects → `localStorage` under `bamendjou:chart:*`
- Chart layout (pane sizes, active indicators) persisted per symbol

---

## Architecture — Approach B (WebSocket streaming)

### Decision rationale
WebSocket streaming was chosen over REST polling (A) and SSE (C) because the same WS channel used for live candles in Phase 1 naturally carries market-structure signal pushes in Phase 2 with no rebuild of the data layer.

### Data flow

```
Tradier wss://stream.tradier.com
        │  (ticks per subscribed symbol)
        ▼
FastAPI data/tradier_stream.py
  TradierStreamClient — one persistent connection
  Demuxes ticks by symbol → per-symbol asyncio.Queue
        │
        ▼
FastAPI routers/chart.py
  WS /chart/stream/{symbol}
  - On connect: load history via GET /chart/history, push as "history" message
  - Subscribe symbol in TradierStreamClient
  - Forward ticks from Queue → WS client as "tick" messages
  - On disconnect: unsubscribe if no other clients watching symbol
        │
        ▼
Frontend lib/chartWS.ts
  ChartWSClient
  - Connects to ws://localhost:8000/chart/stream/{symbol}
  - Reconnects with exponential backoff (max 30s)
  - "history" message → seeds lightweight-charts
  - "tick" message → builds/updates current candle, calls chart.update()
  - Switches symbol: close old WS, open new WS
        │
        ▼
lightweight-charts v5  (ChartPane component)
  - IChartApi with multiple pane instances
  - CandlestickSeries (main pane)
  - LineSeries per SMA/EMA/BB
  - HistogramSeries for Volume, MACD histogram
  - LineSeries for RSI, MACD signal
```

### yfinance fallback
- `GET /chart/history` tries Tradier `/v1/markets/timesales` first
- Falls back to yfinance if Tradier returns < 200 bars (same logic as existing `fetch_intraday_candles`)
- Tradier streaming unavailable → endpoint falls back to polling `/v1/markets/quotes` every 5s

---

## Backend — New Files

### `backend/app/data/tradier_stream.py`
- `TradierStreamClient` — singleton that manages one persistent Tradier WS connection
- Subscribes/unsubscribes symbols dynamically
- Per-symbol `asyncio.Queue` of tick dicts `{symbol, price, volume, timestamp}`
- Auto-reconnects on disconnect

### `backend/app/data/chart_cache.py`
- In-process intraday OHLCV cache (separate from `_candles_cache` in `market.py`)
- TTL by interval: 1m/5m → 15 min, 15m/1h → 30 min, 4h/1D → 4 hr
- `async def get_intraday(symbol, interval, days)` — checks cache, fetches if stale

### `backend/app/routers/chart.py`
```
GET  /chart/history?symbol=AAPL&interval=15min&days=55
     → returns [{time, open, high, low, close, volume}]

WS   /chart/stream/{symbol}?interval=15min
     → streams {type:"history", candles:[...]} on connect
     → streams {type:"tick", data:{time, price, volume}} on new trade
     → streams {type:"error", message:...} on failure
```

### Performance guards (required — based on scan bottleneck analysis)
1. `fetch_intraday_candles` called via `asyncio.to_thread()` inside chart router — prevents blocking Uvicorn event loop (existing function uses blocking `httpx.get()`)
2. Chart-specific semaphore = 2 — caps concurrent chart history fetches so they cannot crowd out the scan's `Semaphore(3)` on the same Tradier account
3. Intraday cache in `chart_cache.py` — every symbol-switch and timeframe-change hits cached data, not Tradier/yfinance

---

## Frontend — New Files

### Routes
- `frontend/app/(frame)/chart/page.tsx` — chart page within frame layout
- `frontend/app/chart/standalone/page.tsx` — standalone pop-out (outside frame layout)

### Components (atoms → organisms pattern, CSS Modules)
| Component | Purpose |
|---|---|
| `ChartWorkspace/` | Root layout: toolbar + left sidebar + panes + right panel |
| `ChartTopBar/` | Symbol picker, timeframe strip, chart type, indicators toggle, pop-out button |
| `DrawingToolbar/` | Left sidebar: cursor, trendline, fib, shapes, text, measure, zoom, magnet, lock, hide, delete |
| `ChartPane/` | Wraps one `IChartApi` pane; accepts series config array |
| `IndicatorPanel/` | Slide-in panel: list active indicators, add/remove, configure parameters |
| `ChartRightPanel/` | Tabs: Watchlist (reuses `WatchStar`), Data (OHLCV + indicator values at cursor) |

### Store
`frontend/lib/chartStore.ts` (Zustand, persisted):
```ts
{
  symbol: string           // active symbol
  interval: string         // '1min' | '5min' | '15min' | '1h' | '4h' | '1D' | '1W'
  chartType: string        // 'candle' | 'bar' | 'line'
  activeIndicators: IndicatorConfig[]
  paneLayout: PaneLayout   // pane height ratios
}
```

### Lib
- `frontend/lib/chartWS.ts` — WebSocket client class, reconnect logic, message dispatch
- `frontend/lib/indicators.ts` — pure functions: `calcSMA`, `calcEMA`, `calcRSI`, `calcMACD`, `calcBB`, `calcATR`, `calcVWAP`

### Deep-link wiring
- `frontend/app/(frame)/screener/step-4-ranking/page.tsx` — add chart icon button per row → `router.push('/chart?symbol='+symbol)`
- `frontend/app/(frame)/screener/step-6-contracts/page.tsx` — same
- `frontend/app/(frame)/watchlist/page.tsx` — same

---

## Error Handling
- WS disconnect → `chartWS.ts` reconnects with backoff (1s, 2s, 4s … max 30s); chart shows stale-data banner
- Tradier stream down → backend falls back to 5s REST polling; frontend unaware (same WS protocol)
- yfinance rate-limit → `chart_cache.py` returns stale cached data with `stale: true` flag; frontend shows warning badge
- Symbol not found → WS sends `{type:"error", message:"symbol not found"}`; frontend shows error state

---

## Testing
- `backend/tests/test_chart_router.py` — REST history endpoint with mock Tradier response; WS connect/disconnect
- `backend/tests/test_chart_cache.py` — TTL expiry, cache hit/miss, concurrent access
- `backend/tests/test_tradier_stream.py` — subscribe/unsubscribe, reconnect logic (mock WS server)
- Frontend: existing Jest + `npm run typecheck` must pass; no new test files required for Phase 1

---

## Out of Scope (Phase 1)
- Market structure overlays (FVG, BOS, CHoCH, Order Blocks, divergence, Fibonacci) — Phase 2
- Alert engine and notification delivery — Phases 3 & 4
- Backend sync for chart layouts/settings — Phase 4
- Options contract charts (underlying stocks/ETFs only in Phase 1)
- Replay mode
