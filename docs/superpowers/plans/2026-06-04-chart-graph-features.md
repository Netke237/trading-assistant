# Chart Graph Features, Drawing & Click Actions — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add TradingView-style chart overlays (MA suite, EMA/SMA cross, Anchored VWAP, Key Levels, Higher-TF Levels, Signal Markers, Multi-Timeframe Dashboard, Volume Profile), interactive drawing tools, and left-click alert/paper-buy actions to the existing `/chart` workspace — every feature toggleable with editable defaults, all alerts routed through the existing backend notification pipeline.

**Architecture:** Extend the existing `ChartWorkspace` (`/chart`) — no new chart engine. New overlays compute client-side from already-streamed candles and register through the existing `chartStore.activeIndicators` + `IndicatorPanel` on/off+params system. Volume Profile and user drawings render as lightweight-charts **primitives** (same `ISeriesPrimitive` pattern as the existing `FibPrimitive`). Left-click actions are driven by the existing `DrawingToolbar` mode model via `chart.subscribeClick`. Alerts reuse `AlertRuleBuilder` → `chartAlertStore` → backend `/alerts/rules` (already sends Telegram/Gmail). Drawings persist to a new `/chart/drawings` backend CRUD.

**Tech Stack:** Next.js 15 / React 19, TypeScript strict, Zustand v5, lightweight-charts v5.1, CSS Modules, Jest (frontend); FastAPI + Pydantic v2 + SQLAlchemy v2 + Alembic + pytest (backend).

---

## Conventions (read once)

- **Run frontend tests:** `cd frontend && npm run test -- --testPathPattern=<name>`
- **Typecheck (must be clean before every commit):** `cd frontend && npm run typecheck`
- **Run backend tests:** `cd backend && pytest tests/<file> -v`
- **Existing patterns to copy:**
  - Primitive: `frontend/lib/chartPrimitives/FibPrimitive.ts` (canvas draw via `IPrimitivePaneView`/`IPrimitivePaneRenderer`, `priceToCoordinate`).
  - Pure indicator helpers + `Candle`/`Point` types: `frontend/lib/indicators.ts`.
  - Store with backend sync + persist/migrate: `frontend/lib/chartAlertStore.ts`.
  - Indicator registry/toggle UI: `frontend/components/organisms/IndicatorPanel/index.tsx` (`AVAILABLE` array).
  - Overlay attach/detach lifecycle: `frontend/components/organisms/ChartOverlays/index.tsx`.
  - Workspace wiring: `frontend/components/organisms/ChartWorkspace/index.tsx`.
- **lightweight-charts v5 markers:** use `createSeriesMarkers(series, markers)` from `lightweight-charts` (the v5 plugin API), NOT the removed `series.setMarkers`.
- **Commit cadence:** one commit per task (after its tests pass + typecheck clean). Branch off `main` first: `git checkout -b feat/chart-graph-features`.

---

## File Structure

**Frontend — new:**
- `frontend/lib/chart/overlays.ts` — pure compute for new overlays (anchored VWAP, key levels, crossover signals, signal markers, volume profile bins).
- `frontend/lib/chart/mtf.ts` — pure compute for the multi-timeframe dashboard rows.
- `frontend/lib/chartPrimitives/VolumeProfilePrimitive.ts` — VP histogram + POC primitive.
- `frontend/lib/chartPrimitives/TrendLinePrimitive.ts`, `HorizontalLinePrimitive.ts`, `RectanglePrimitive.ts` — drawing primitives.
- `frontend/lib/drawingStore.ts` — Zustand store for user drawings (+ backend sync, persist).
- `frontend/lib/paperTrade.ts` — build a paper underlying-stock `PortfolioPosition`.
- `frontend/types/overlays.ts` — overlay/drawing types.
- `frontend/components/organisms/MtfDashboard/index.tsx` (+ `.module.css`) — the MTF table overlay.
- `frontend/components/molecules/ChartClickPopover/index.tsx` (+ `.module.css`) — confirm popover for buy/alert.

**Frontend — modified:**
- `frontend/lib/chartStore.ts` — extend `IndicatorConfig.type`, add overlay defaults.
- `frontend/components/organisms/IndicatorPanel/index.tsx` — add new overlays to `AVAILABLE`.
- `frontend/components/organisms/DrawingToolbar/index.tsx` — add `hline`, `alert`, `buy` tools.
- `frontend/components/organisms/ChartWorkspace/index.tsx` — render overlays, wire click handling.
- `frontend/components/organisms/AlertRuleBuilder/index.tsx` — accept a `prefill` prop.

**Backend — new:**
- `backend/app/routers/chart_drawings.py` — `/chart/drawings` CRUD (mirror `backend/app/routers/chart_alerts.py`).
- `backend/app/models/drawing.py` — `Drawing` table, using the shared `Base` from `backend/app/models/base.py` and mirroring `backend/app/models/alert.py` (NOT the standalone-base `ohlcv_daily.py`).
- Alembic migration in `backend/migrations/versions/` (Alembic root is `backend/migrations/`, configured by `backend/migrations/env.py`).
- `backend/tests/test_chart_drawings.py`.

**Backend — modified:**
- `backend/app/main.py` — add `from app.routers.chart_drawings import router as chart_drawings_router` (near line 35) and `app.include_router(chart_drawings_router)` (near line 114, after `historical_data_router`).

**Note — existing infrastructure to reuse (discovered post-merge of the Tiingo historical-store work):**
- `backend/app/routers/` already exposes a `candles_router` (REST candles) — use it for the deferred true-HTF-fetch and full multi-TF-dashboard follow-ups instead of inventing an endpoint.
- A `broker_router` + `auto_trade_router` exist, but click-to-buy stays **paper underlying** per the approved design; do not wire real orders here.

---

## PHASE 0 — Foundations (types, store, click-mode plumbing)

### Task 0.1: Overlay & drawing types

**Files:**
- Create: `frontend/types/overlays.ts`

- [ ] **Step 1: Create the types file**

```ts
// frontend/types/overlays.ts
// Shared types for the new chart overlays and user drawings.

import type { Interval } from '@/lib/chartStore';

/** New overlay kinds added on top of the existing indicator types. */
export type OverlayType =
  | 'MASUITE'    // up to 4 configurable MAs
  | 'XSIGNAL'    // EMA/SMA crossover markers
  | 'AVWAP'      // anchored VWAP
  | 'KEYLEVELS'  // PDH/PDL/PWH/PWL
  | 'HTFLEVELS'  // higher-timeframe H/L/C
  | 'SIGNALS'    // buy/sell markers (EMA cross + RSI)
  | 'MTF'        // multi-timeframe dashboard table
  | 'VPROFILE';  // volume profile + POC

export interface MarkerPoint {
  time: string | number;
  position: 'aboveBar' | 'belowBar';
  color: string;
  shape: 'arrowUp' | 'arrowDown';
  text: string;
}

export interface KeyLevels {
  pdh: number | null; pdl: number | null;
  pwh: number | null; pwl: number | null;
}

export interface VolumeProfileBin { price: number; volume: number; }
export interface VolumeProfile {
  bins: VolumeProfileBin[];
  poc: number | null;   // point of control price
  vah: number | null;   // value-area high
  val: number | null;   // value-area low
}

export interface MtfRow {
  tf: Interval;
  trendUp: boolean;
  rsi: number;
  changePct: number;
}

export type DrawingKind = 'trendline' | 'hline' | 'rect';
export interface DrawingPoint { time: number; price: number; }
export interface Drawing {
  id: string;
  symbol: string;
  interval: Interval;
  kind: DrawingKind;
  points: DrawingPoint[];   // hline: 1 pt; trendline/rect: 2 pts
  color: string;
  width: number;
  createdAt: string;
}
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean (no references yet).

- [ ] **Step 3: Commit**

```bash
git add frontend/types/overlays.ts
git commit -m "feat(chart): add overlay & drawing types"
```

---

### Task 0.2: Extend chartStore with overlay configs

**Files:**
- Modify: `frontend/lib/chartStore.ts`

`IndicatorConfig.type` is already a free `string`, so no union change is needed — but we add overlay default registries the panel and workspace consume. Add `params` conventions for the new overlays.

- [ ] **Step 1: Add overlay default registry export to `chartStore.ts`**

Append after `DEFAULT_PANE_LAYOUT` (around line 50):

```ts
// Default param sets for the new chart overlays. The IndicatorPanel reads these
// to build toggle entries; ChartWorkspace reads ind.params to render. Every value
// is a user-overwritable default.
export const OVERLAY_DEFAULTS: Record<string, { pane: 'main' | 'sub'; params: Record<string, number>; color: string; label: string }> = {
  MASUITE:   { pane: 'main', label: 'MA Suite (4)',     color: '#4f8ef7', params: { ma1: 9, ma2: 21, ma3: 50, ma4: 200 } },
  XSIGNAL:   { pane: 'main', label: 'EMA/SMA Cross',    color: '#e0a030', params: { emaLen: 9, smaLen: 20 } },
  AVWAP:     { pane: 'main', label: 'Anchored VWAP',    color: '#b070e0', params: { anchorMs: 1735689600000 } }, // 2025-01-01
  KEYLEVELS: { pane: 'main', label: 'Key Levels',       color: '#808080', params: { day: 1, week: 1 } },
  HTFLEVELS: { pane: 'main', label: 'Higher-TF Levels', color: '#30a060', params: { tfMin: 240 } },
  SIGNALS:   { pane: 'main', label: 'Signal Markers',   color: '#26a69a', params: { fast: 9, slow: 21, rsi: 14 } },
  MTF:       { pane: 'main', label: 'MTF Dashboard',    color: '#888888', params: { rsi: 14 } },
  VPROFILE:  { pane: 'main', label: 'Volume Profile',   color: '#5a6acf', params: { lookback: 200, rows: 24 } },
};
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/chartStore.ts
git commit -m "feat(chart): add OVERLAY_DEFAULTS registry to chartStore"
```

---

### Task 0.3: Add tools to DrawingToolbar (hline, alert, buy)

**Files:**
- Modify: `frontend/components/organisms/DrawingToolbar/index.tsx`

- [ ] **Step 1: Extend the `DrawingTool` union and `TOOLS` list**

Replace the `DrawingTool` type (line 4) and `TOOLS` array (lines 11-19):

```ts
export type DrawingTool =
  | 'cursor' | 'trendline' | 'hline' | 'rect'
  | 'alert'  | 'buy'
  | 'fib' | 'text' | 'measure' | 'zoom';
```

```ts
const TOOLS: { id: DrawingTool; label: string; icon: string }[] = [
  { id: 'cursor',    label: 'Cursor',          icon: '✛' },
  { id: 'trendline', label: 'Trendline',       icon: '╱' },
  { id: 'hline',     label: 'Horizontal line', icon: '─' },
  { id: 'rect',      label: 'Rectangle',       icon: '□' },
  { id: 'alert',     label: 'Set alert',       icon: '🔔' },
  { id: 'buy',       label: 'Paper buy',       icon: '＄' },
  { id: 'fib',       label: 'Fibonacci',       icon: 'Φ' },
];
```

(Removed `text/measure/zoom` from the visible set — deferred per spec; the type keeps them so nothing else breaks.)

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/components/organisms/DrawingToolbar/index.tsx
git commit -m "feat(chart): add hline/alert/buy tools to DrawingToolbar"
```

---

## PHASE 1 — Overlays (pure compute first, then render)

### Task 1.1: Anchored VWAP (pure)

**Files:**
- Create: `frontend/lib/chart/overlays.ts`
- Test: `frontend/lib/chart/overlays.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/lib/chart/overlays.test.ts
import { calcAnchoredVWAP } from './overlays';
import type { Candle } from '@/lib/indicators';

const c = (time: number, price: number, vol: number): Candle =>
  ({ time, open: price, high: price, low: price, close: price, volume: vol });

describe('calcAnchoredVWAP', () => {
  it('returns na before the anchor and cumulative VWAP after', () => {
    const candles = [c(100, 10, 0), c(200, 20, 10), c(300, 30, 10)];
    const out = calcAnchoredVWAP(candles, 200);
    expect(out[0].value).toBeNull();          // before anchor
    expect(out[1].value).toBeCloseTo(20);     // first anchored bar
    expect(out[2].value).toBeCloseTo(25);     // (20*10 + 30*10) / 20
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npm run test -- --testPathPattern=overlays`
Expected: FAIL ("calcAnchoredVWAP is not a function").

- [ ] **Step 3: Implement**

```ts
// frontend/lib/chart/overlays.ts
import type { Candle, Point } from '@/lib/indicators';
import type { KeyLevels, MarkerPoint, VolumeProfile } from '@/types/overlays';

const hlc3 = (c: Candle) => (c.high + c.low + c.close) / 3;

/** Cumulative VWAP measured from the first candle whose time >= anchorMs. */
export function calcAnchoredVWAP(candles: Candle[], anchorMs: number): Point[] {
  let cumPV = 0, cumV = 0;
  return candles.map((c): Point => {
    const t = typeof c.time === 'number' ? c.time * (c.time < 1e12 ? 1000 : 1) : Date.parse(String(c.time));
    if (t < anchorMs) return { time: c.time, value: null as unknown as number };
    cumPV += hlc3(c) * c.volume;
    cumV  += c.volume;
    return { time: c.time, value: cumV > 0 ? cumPV / cumV : (null as unknown as number) };
  });
}
```

> Note: `Point.value` is `number`; existing helpers already emit `null` for warm-up. Keep the same `null as unknown as number` convention used in `lib/indicators.ts`.

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npm run test -- --testPathPattern=overlays`
Expected: PASS.

- [ ] **Step 5: Typecheck + commit**

```bash
cd frontend && npm run typecheck
git add frontend/lib/chart/overlays.ts frontend/lib/chart/overlays.test.ts
git commit -m "feat(chart): anchored VWAP pure calc"
```

---

### Task 1.2: Key Levels (pure)

**Files:**
- Modify: `frontend/lib/chart/overlays.ts`
- Test: `frontend/lib/chart/overlays.test.ts`

- [ ] **Step 1: Add failing test**

```ts
import { calcKeyLevels } from './overlays';

describe('calcKeyLevels', () => {
  it('returns the previous completed day high/low', () => {
    // two days of daily bars (string time = daily per chart.ts convention)
    const candles = [
      { time: '2025-01-01', open: 1, high: 12, low: 8,  close: 10, volume: 1 },
      { time: '2025-01-02', open: 10, high: 15, low: 9, close: 14, volume: 1 },
    ];
    const lv = calcKeyLevels(candles, '1D');
    expect(lv.pdh).toBe(12);   // prev day high
    expect(lv.pdl).toBe(8);    // prev day low
  });
});
```

- [ ] **Step 2: Run — FAIL.**

Run: `cd frontend && npm run test -- --testPathPattern=overlays`

- [ ] **Step 3: Implement (append to overlays.ts)**

```ts
import type { Interval } from '@/lib/chartStore';

function bucketKey(time: string | number, unit: 'day' | 'week'): string {
  const d = typeof time === 'number'
    ? new Date(time < 1e12 ? time * 1000 : time)
    : new Date(`${time}T00:00:00Z`);
  if (unit === 'day') return d.toISOString().slice(0, 10);
  const onejan = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  const week = Math.ceil((((d.getTime() - onejan.getTime()) / 86400000) + onejan.getUTCDay() + 1) / 7);
  return `${d.getUTCFullYear()}-W${week}`;
}

function prevBucketHL(candles: Candle[], unit: 'day' | 'week'): [number | null, number | null] {
  if (candles.length === 0) return [null, null];
  const lastKey = bucketKey(candles[candles.length - 1].time, unit);
  let hi: number | null = null, lo: number | null = null;
  for (const c of candles) {
    const k = bucketKey(c.time, unit);
    if (k === lastKey) continue;       // skip the in-progress bucket
    // track the most recent *completed* bucket
    if (lo === null) { hi = c.high; lo = c.low; }
  }
  // re-scan to get full extent of the most recent completed bucket
  const completed = candles.filter((c) => bucketKey(c.time, unit) !== lastKey);
  if (completed.length === 0) return [null, null];
  const prevKey = bucketKey(completed[completed.length - 1].time, unit);
  const inPrev = completed.filter((c) => bucketKey(c.time, unit) === prevKey);
  hi = Math.max(...inPrev.map((c) => c.high));
  lo = Math.min(...inPrev.map((c) => c.low));
  return [hi, lo];
}

export function calcKeyLevels(candles: Candle[], _interval: Interval): KeyLevels {
  const [pdh, pdl] = prevBucketHL(candles, 'day');
  const [pwh, pwl] = prevBucketHL(candles, 'week');
  return { pdh, pdl, pwh, pwl };
}
```

- [ ] **Step 4: Run — PASS.** `cd frontend && npm run test -- --testPathPattern=overlays`
- [ ] **Step 5: Typecheck + commit**

```bash
cd frontend && npm run typecheck
git add frontend/lib/chart/overlays.ts frontend/lib/chart/overlays.test.ts
git commit -m "feat(chart): key levels (PDH/PDL/PWH/PWL) pure calc"
```

---

### Task 1.3: Crossover + Signal markers (pure)

**Files:**
- Modify: `frontend/lib/chart/overlays.ts`
- Test: `frontend/lib/chart/overlays.test.ts`

- [ ] **Step 1: Add failing test**

```ts
import { calcCrossSignals, calcSignalMarkers } from './overlays';

const series = (closes: number[]): Candle[] =>
  closes.map((p, i) => ({ time: i + 1, open: p, high: p, low: p, close: p, volume: 1 }));

describe('cross signals', () => {
  it('emits an arrowUp marker when EMA crosses above SMA', () => {
    const candles = series([1,1,1,1,1,1,1,1,1,10,11,12,13,14,15]);
    const m = calcCrossSignals(candles, 3, 5);
    expect(m.some((x) => x.shape === 'arrowUp')).toBe(true);
  });
  it('signal markers return arrays of MarkerPoint', () => {
    const candles = series(Array.from({ length: 40 }, (_, i) => i));
    const m = calcSignalMarkers(candles, 9, 21, 14);
    expect(Array.isArray(m)).toBe(true);
  });
});
```

- [ ] **Step 2: Run — FAIL.**

- [ ] **Step 3: Implement (append; reuse existing EMA/SMA/RSI from lib/indicators)**

```ts
import { calcEMA, calcSMA, calcRSI } from '@/lib/indicators';

function crossMarkers(
  candles: Candle[], a: Point[], b: Point[], upColor: string, dnColor: string,
): MarkerPoint[] {
  const out: MarkerPoint[] = [];
  for (let i = 1; i < candles.length; i++) {
    const a0 = a[i - 1]?.value, a1 = a[i]?.value, b0 = b[i - 1]?.value, b1 = b[i]?.value;
    if (a0 == null || a1 == null || b0 == null || b1 == null) continue;
    if (a0 <= b0 && a1 > b1) out.push({ time: candles[i].time, position: 'belowBar', color: upColor, shape: 'arrowUp', text: 'X↑' });
    if (a0 >= b0 && a1 < b1) out.push({ time: candles[i].time, position: 'aboveBar', color: dnColor, shape: 'arrowDown', text: 'X↓' });
  }
  return out;
}

/** EMA(emaLen) crossing SMA(smaLen). */
export function calcCrossSignals(candles: Candle[], emaLen: number, smaLen: number): MarkerPoint[] {
  return crossMarkers(candles, calcEMA(candles, emaLen), calcSMA(candles, smaLen), '#26a69a', '#ef5350');
}

/** Fast EMA × slow EMA with RSI>50 / <50 confirmation (the spec's signal markers). */
export function calcSignalMarkers(candles: Candle[], fast: number, slow: number, rsiLen: number): MarkerPoint[] {
  const ef = calcEMA(candles, fast), es = calcEMA(candles, slow), rsi = calcRSI(candles, rsiLen);
  const out: MarkerPoint[] = [];
  for (let i = 1; i < candles.length; i++) {
    const f0 = ef[i-1]?.value, f1 = ef[i]?.value, s0 = es[i-1]?.value, s1 = es[i]?.value, r = rsi[i]?.value;
    if ([f0,f1,s0,s1,r].some((v) => v == null)) continue;
    if (f0! <= s0! && f1! > s1! && r! > 50) out.push({ time: candles[i].time, position: 'belowBar', color: '#26a69a', shape: 'arrowUp', text: 'BUY' });
    if (f0! >= s0! && f1! < s1! && r! < 50) out.push({ time: candles[i].time, position: 'aboveBar', color: '#ef5350', shape: 'arrowDown', text: 'SELL' });
  }
  return out;
}
```

- [ ] **Step 4: Run — PASS.**
- [ ] **Step 5: Typecheck + commit**

```bash
cd frontend && npm run typecheck
git add frontend/lib/chart/overlays.ts frontend/lib/chart/overlays.test.ts
git commit -m "feat(chart): crossover + signal markers pure calc"
```

---

### Task 1.4: Volume Profile (pure)

**Files:**
- Modify: `frontend/lib/chart/overlays.ts`
- Test: `frontend/lib/chart/overlays.test.ts`

- [ ] **Step 1: Add failing test**

```ts
import { calcVolumeProfile } from './overlays';

describe('calcVolumeProfile', () => {
  it('bins volume by price and reports a POC', () => {
    const candles = [
      { time: 1, open: 10, high: 10, low: 10, close: 10, volume: 100 },
      { time: 2, open: 20, high: 20, low: 20, close: 20, volume: 10 },
    ];
    const vp = calcVolumeProfile(candles, 2, 4);
    expect(vp.bins.length).toBe(4);
    expect(vp.poc).toBeCloseTo(10, 0);   // heaviest volume at price ~10
  });
});
```

- [ ] **Step 2: Run — FAIL.**

- [ ] **Step 3: Implement (append)**

```ts
export function calcVolumeProfile(candles: Candle[], lookback: number, rows: number): VolumeProfile {
  const slice = candles.slice(-lookback);
  if (slice.length === 0 || rows < 1) return { bins: [], poc: null, vah: null, val: null };
  const hi = Math.max(...slice.map((c) => c.high));
  const lo = Math.min(...slice.map((c) => c.low));
  const rng = hi - lo;
  if (rng <= 0) return { bins: [], poc: null, vah: null, val: null };
  const binSz = rng / rows;
  const vols = new Array(rows).fill(0);
  for (const c of slice) {
    const idx = Math.min(rows - 1, Math.max(0, Math.floor((hlc3(c) - lo) / binSz)));
    vols[idx] += c.volume;
  }
  const bins = vols.map((v, i) => ({ price: lo + (i + 0.5) * binSz, volume: v }));
  const total = vols.reduce((a, b) => a + b, 0);
  const pocIdx = vols.indexOf(Math.max(...vols));
  // value area = 70% of volume expanding out from POC
  let loI = pocIdx, hiI = pocIdx, acc = vols[pocIdx];
  while (acc < total * 0.7 && (loI > 0 || hiI < rows - 1)) {
    const down = loI > 0 ? vols[loI - 1] : -1;
    const up = hiI < rows - 1 ? vols[hiI + 1] : -1;
    if (up >= down) { hiI++; acc += Math.max(0, up); } else { loI--; acc += Math.max(0, down); }
  }
  return {
    bins,
    poc: bins[pocIdx].price,
    vah: bins[hiI].price,
    val: bins[loI].price,
  };
}
```

- [ ] **Step 4: Run — PASS.**
- [ ] **Step 5: Typecheck + commit**

```bash
cd frontend && npm run typecheck
git add frontend/lib/chart/overlays.ts frontend/lib/chart/overlays.test.ts
git commit -m "feat(chart): volume profile + POC/value-area pure calc"
```

---

### Task 1.5: MTF dashboard rows (pure)

**Files:**
- Create: `frontend/lib/chart/mtf.ts`
- Test: `frontend/lib/chart/mtf.test.ts`

- [ ] **Step 1: Failing test**

```ts
// frontend/lib/chart/mtf.test.ts
import { buildMtfRow } from './mtf';

const up = Array.from({ length: 60 }, (_, i) => ({ time: i + 1, open: i, high: i + 1, low: i - 1, close: i + 0.5, volume: 1 }));

describe('buildMtfRow', () => {
  it('reports trendUp true for a rising series', () => {
    const row = buildMtfRow('1h', up, 14);
    expect(row.trendUp).toBe(true);
    expect(row.tf).toBe('1h');
    expect(typeof row.rsi).toBe('number');
  });
});
```

- [ ] **Step 2: Run — FAIL.**

- [ ] **Step 3: Implement**

```ts
// frontend/lib/chart/mtf.ts
import { calcEMA, calcRSI, type Candle } from '@/lib/indicators';
import type { Interval } from '@/lib/chartStore';
import type { MtfRow } from '@/types/overlays';

const last = <T,>(arr: T[]): T | undefined => arr[arr.length - 1];

/** One dashboard row for a timeframe given that timeframe's candles. */
export function buildMtfRow(tf: Interval, candles: Candle[], rsiLen: number): MtfRow {
  const ema21 = calcEMA(candles, 21);
  const ema50 = calcEMA(candles, 50);
  const rsi = calcRSI(candles, rsiLen);
  const e21 = last(ema21)?.value ?? 0;
  const e50 = last(ema50)?.value ?? 0;
  const c = last(candles);
  const changePct = c ? ((c.close - c.open) / c.open) * 100 : 0;
  return { tf, trendUp: e21 > e50, rsi: last(rsi)?.value ?? 0, changePct };
}
```

- [ ] **Step 4: Run — PASS.**
- [ ] **Step 5: Typecheck + commit**

```bash
cd frontend && npm run typecheck
git add frontend/lib/chart/mtf.ts frontend/lib/chart/mtf.test.ts
git commit -m "feat(chart): MTF dashboard row builder"
```

---

### Task 1.6: Volume Profile primitive (render)

**Files:**
- Create: `frontend/lib/chartPrimitives/VolumeProfilePrimitive.ts`

Pattern: copy the structure of `FibPrimitive.ts` (renderer + pane view + primitive). Draws horizontal bars anchored to the right edge; POC highlighted.

- [ ] **Step 1: Implement**

```ts
// frontend/lib/chartPrimitives/VolumeProfilePrimitive.ts
import type {
  ISeriesPrimitive, IPrimitivePaneView, IPrimitivePaneRenderer,
  ISeriesApi, SeriesAttachedParameter,
} from 'lightweight-charts';
import type { CanvasRenderingTarget2D } from 'fancy-canvas';
import type { VolumeProfile } from '@/types/overlays';

class VPRenderer implements IPrimitivePaneRenderer {
  constructor(private vp: VolumeProfile, private series: ISeriesApi<'Candlestick'>) {}
  draw(target: CanvasRenderingTarget2D): void {
    target.useMediaCoordinateSpace(({ mediaSize, context: ctx }) => {
      const toY = (p: number) => this.series.priceToCoordinate(p);
      const maxV = Math.max(...this.vp.bins.map((b) => b.volume), 1);
      const maxW = mediaSize.width * 0.25;            // bars occupy right 25%
      const binPx = this.vp.bins.length > 1
        ? Math.abs((toY(this.vp.bins[1].price) ?? 0) - (toY(this.vp.bins[0].price) ?? 0))
        : 4;
      for (const b of this.vp.bins) {
        const y = toY(b.price);
        if (y === null) continue;
        const w = (b.volume / maxV) * maxW;
        const isPoc = this.vp.poc !== null && Math.abs(b.price - this.vp.poc) < 1e-9;
        ctx.fillStyle = isPoc ? 'rgba(224,160,48,0.55)' : 'rgba(90,106,207,0.45)';
        ctx.fillRect(mediaSize.width - w, y - binPx / 2, w, Math.max(1, binPx - 1));
      }
    });
  }
}
class VPView implements IPrimitivePaneView {
  constructor(private vp: VolumeProfile, private series: ISeriesApi<'Candlestick'>) {}
  renderer(): IPrimitivePaneRenderer { return new VPRenderer(this.vp, this.series); }
}
export class VolumeProfilePrimitive implements ISeriesPrimitive {
  private series: ISeriesApi<'Candlestick'> | null = null;
  constructor(private vp: VolumeProfile) {}
  attached(p: SeriesAttachedParameter): void { this.series = p.series as ISeriesApi<'Candlestick'>; p.requestUpdate(); }
  paneViews(): readonly IPrimitivePaneView[] { return this.series ? [new VPView(this.vp, this.series)] : []; }
}
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/chartPrimitives/VolumeProfilePrimitive.ts
git commit -m "feat(chart): volume profile primitive renderer"
```

---

### Task 1.7: MTF dashboard table component

**Files:**
- Create: `frontend/components/organisms/MtfDashboard/index.tsx`
- Create: `frontend/components/organisms/MtfDashboard/MtfDashboard.module.css`

- [ ] **Step 1: Implement the component**

```tsx
// frontend/components/organisms/MtfDashboard/index.tsx
'use client';
import { Text } from '@/components/primitives';
import type { MtfRow } from '@/types/overlays';
import styles from './MtfDashboard.module.css';

export default function MtfDashboard({ rows }: { rows: MtfRow[] }) {
  if (rows.length === 0) return null;
  return (
    <div className={styles.box}>
      <div className={styles.head}>
        <Text size={10} tone="dim">TF</Text>
        <Text size={10} tone="dim">Trend</Text>
        <Text size={10} tone="dim">RSI</Text>
        <Text size={10} tone="dim">Chg%</Text>
      </div>
      {rows.map((r) => (
        <div key={r.tf} className={styles.row}>
          <Text size={11}>{r.tf}</Text>
          <Text size={11} tone={r.trendUp ? 'pass' : 'reject'}>{r.trendUp ? '▲' : '▼'}</Text>
          <Text size={11}>{r.rsi.toFixed(0)}</Text>
          <Text size={11} tone={r.changePct >= 0 ? 'pass' : 'reject'}>{r.changePct.toFixed(1)}</Text>
        </div>
      ))}
    </div>
  );
}
```

```css
/* frontend/components/organisms/MtfDashboard/MtfDashboard.module.css */
.box { position: absolute; top: 8px; right: 8px; z-index: 5;
  background: var(--bg-surface); border: 1px solid var(--border-subtle);
  padding: 6px 8px; display: grid; gap: 2px; }
.head, .row { display: grid; grid-template-columns: 40px 44px 36px 48px; gap: 6px; align-items: center; }
```

- [ ] **Step 2: Typecheck + commit**

```bash
cd frontend && npm run typecheck
git add frontend/components/organisms/MtfDashboard
git commit -m "feat(chart): MTF dashboard table component"
```

---

### Task 1.8: Register overlays in IndicatorPanel

**Files:**
- Modify: `frontend/components/organisms/IndicatorPanel/index.tsx`

- [ ] **Step 1: Append overlay entries to the `AVAILABLE` array (after line 18)**

```ts
  // ── New chart overlays (params come from OVERLAY_DEFAULTS) ──
  { type: 'MASUITE',   label: 'MA Suite (4)',     pane: 'main', defaultParams: { ma1: 9, ma2: 21, ma3: 50, ma4: 200 }, color: '#4f8ef7' },
  { type: 'XSIGNAL',   label: 'EMA/SMA Cross',    pane: 'main', defaultParams: { emaLen: 9, smaLen: 20 },              color: '#e0a030' },
  { type: 'AVWAP',     label: 'Anchored VWAP',    pane: 'main', defaultParams: { anchorMs: 1735689600000 },           color: '#b070e0' },
  { type: 'KEYLEVELS', label: 'Key Levels',       pane: 'main', defaultParams: { day: 1, week: 1 },                   color: '#808080' },
  { type: 'HTFLEVELS', label: 'Higher-TF Levels', pane: 'main', defaultParams: { tfMin: 240 },                        color: '#30a060' },
  { type: 'SIGNALS',   label: 'Signal Markers',   pane: 'main', defaultParams: { fast: 9, slow: 21, rsi: 14 },        color: '#26a69a' },
  { type: 'MTF',       label: 'MTF Dashboard',    pane: 'main', defaultParams: { rsi: 14 },                           color: '#888888' },
  { type: 'VPROFILE',  label: 'Volume Profile',   pane: 'main', defaultParams: { lookback: 200, rows: 24 },           color: '#5a6acf' },
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean. Toggling now adds these to `chartStore.activeIndicators` (on/off + editable params already work via the existing panel UI).

- [ ] **Step 3: Commit**

```bash
git add frontend/components/organisms/IndicatorPanel/index.tsx
git commit -m "feat(chart): expose new overlays in IndicatorPanel"
```

---

### Task 1.9: Render overlays in ChartWorkspace

**Files:**
- Modify: `frontend/components/organisms/ChartWorkspace/index.tsx`

This task wires the pure calcs + primitive + MTF component into the workspace. Line-overlays (MA suite, anchored VWAP, key levels, HTF) are added as extra `SeriesConfig` entries; markers via `createSeriesMarkers`; volume profile via primitive attach; MTF via the component.

- [ ] **Step 1: Extend `buildMainSeries` to emit the new line overlays**

In `buildMainSeries` (around line 39, inside the indicators loop), add handling after the existing `BB` block:

```ts
    if (ind.type === 'MASUITE') {
      const lens = [ind.params.ma1, ind.params.ma2, ind.params.ma3, ind.params.ma4].filter(Boolean);
      const cols = ['#4f8ef7', '#e0a030', '#e0e040', '#e040e0'];
      lens.forEach((len, i) => series.push({ id: `${ind.id}-ma${i}`, type: 'Line', data: calcEMA(candles, len), color: cols[i] }));
    }
    if (ind.type === 'AVWAP') {
      series.push({ id: ind.id, type: 'Line', data: calcAnchoredVWAP(candles, ind.params.anchorMs), color: ind.color });
    }
    if (ind.type === 'KEYLEVELS') {
      const lv = calcKeyLevels(candles, interval);
      const flat = (v: number | null) => v == null ? [] : candles.map((c) => ({ time: c.time, value: v }));
      if (ind.params.day)  { series.push({ id: `${ind.id}-pdh`, type: 'Line', data: flat(lv.pdh), color: '#808080' }); series.push({ id: `${ind.id}-pdl`, type: 'Line', data: flat(lv.pdl), color: '#808080' }); }
      if (ind.params.week) { series.push({ id: `${ind.id}-pwh`, type: 'Line', data: flat(lv.pwh), color: '#4a90a4' }); series.push({ id: `${ind.id}-pwl`, type: 'Line', data: flat(lv.pwl), color: '#4a90a4' }); }
    }
```

Add imports at top: `import { calcEMA, ... } from '@/lib/indicators';` already present — add `import { calcAnchoredVWAP, calcKeyLevels, calcCrossSignals, calcSignalMarkers, calcVolumeProfile } from '@/lib/chart/overlays';`.

> **HTF levels note:** `HTFLEVELS` needs higher-timeframe bars. For this task, derive HTF H/L/C by resampling the current `candles` to `tfMin` with a small `resample(candles, tfMin)` helper added to `lib/chart/overlays.ts` (no backend dependency). A true HTF fetch can replace it later via the existing backend `candles_router` (REST candles endpoint) — see `frontend/lib/api.ts` for how the historical-store feature calls backend endpoints.

- [ ] **Step 2: Add markers + volume-profile + MTF rendering**

In the component body, after `mainSeriesRef` is set, add an effect that attaches markers and the VP primitive:

```ts
// markers (XSIGNAL + SIGNALS) and volume-profile primitive
const vpPrimRef = useRef<VolumeProfilePrimitive | null>(null);
const markersRef = useRef<ReturnType<typeof createSeriesMarkers> | null>(null);
useEffect(() => {
  const series = mainSeriesRef.current;
  if (!series) return;
  const markers: MarkerPoint[] = [];
  for (const ind of activeIndicators) {
    if (ind.type === 'XSIGNAL') markers.push(...calcCrossSignals(candles, ind.params.emaLen, ind.params.smaLen));
    if (ind.type === 'SIGNALS') markers.push(...calcSignalMarkers(candles, ind.params.fast, ind.params.slow, ind.params.rsi));
  }
  markers.sort((a, b) => Number(a.time) - Number(b.time));
  if (!markersRef.current) markersRef.current = createSeriesMarkers(series, []);
  markersRef.current.setMarkers(markers.map((m) => ({ time: m.time as Time, position: m.position, color: m.color, shape: m.shape, text: m.text })));

  // volume profile
  if (vpPrimRef.current) { try { series.detachPrimitive(vpPrimRef.current); } catch {} vpPrimRef.current = null; }
  const vpCfg = activeIndicators.find((i) => i.type === 'VPROFILE');
  if (vpCfg) {
    const vp = calcVolumeProfile(candles, vpCfg.params.lookback, vpCfg.params.rows);
    vpPrimRef.current = new VolumeProfilePrimitive(vp);
    series.attachPrimitive(vpPrimRef.current);
  }
}, [candles, activeIndicators]);
```

Add imports: `import { createSeriesMarkers, type Time } from 'lightweight-charts';`, `import { VolumeProfilePrimitive } from '@/lib/chartPrimitives/VolumeProfilePrimitive';`, `import MtfDashboard from '@/components/organisms/MtfDashboard';`, `import { buildMtfRow } from '@/lib/chart/mtf';`, `import type { MarkerPoint, MtfRow } from '@/types/overlays';`.

- [ ] **Step 3: Render MTF dashboard inside `.mainPane`**

After `<ChartOverlays … />` inside `.mainPane` (around line 308):

```tsx
{activeIndicators.some((i) => i.type === 'MTF') && (
  <MtfDashboard rows={mtfRows} />
)}
```

And compute `mtfRows` (MVP: single-timeframe placeholder until per-TF fetch is added — derive from the current candles so it renders immediately):

```ts
const mtfRows: MtfRow[] = useMemo(
  () => activeIndicators.some((i) => i.type === 'MTF')
    ? [buildMtfRow(interval, candles, 14)]
    : [],
  [activeIndicators, interval, candles],
);
```

> **Follow-up (separate task if desired):** fetch candles for 15m/1h/4h/1D/1W via the existing data client and map each through `buildMtfRow` to fill the full table. The single-row MVP keeps this task self-contained.

- [ ] **Step 4: Typecheck + manual verify**

Run: `cd frontend && npm run typecheck` (expected clean), then `npm run dev`, open `/chart`, toggle each overlay in the Indicators panel — lines/markers/VP/MTF appear and clear on toggle.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/organisms/ChartWorkspace/index.tsx
git commit -m "feat(chart): render MA suite, anchored VWAP, key levels, signals, volume profile, MTF"
```

---

## PHASE 2 — Drawing tools (primitives + persistence)

### Task 2.1: Drawing primitives

**Files:**
- Create: `frontend/lib/chartPrimitives/HorizontalLinePrimitive.ts`
- Create: `frontend/lib/chartPrimitives/TrendLinePrimitive.ts`
- Create: `frontend/lib/chartPrimitives/RectanglePrimitive.ts`

Each follows `FibPrimitive.ts`. Example (horizontal line):

- [ ] **Step 1: Implement HorizontalLinePrimitive**

```ts
// frontend/lib/chartPrimitives/HorizontalLinePrimitive.ts
import type { ISeriesPrimitive, IPrimitivePaneView, IPrimitivePaneRenderer, ISeriesApi, SeriesAttachedParameter } from 'lightweight-charts';
import type { CanvasRenderingTarget2D } from 'fancy-canvas';
import type { Drawing } from '@/types/overlays';

class R implements IPrimitivePaneRenderer {
  constructor(private d: Drawing, private s: ISeriesApi<'Candlestick'>) {}
  draw(t: CanvasRenderingTarget2D): void {
    t.useMediaCoordinateSpace(({ mediaSize, context: ctx }) => {
      const y = this.s.priceToCoordinate(this.d.points[0].price);
      if (y === null) return;
      ctx.strokeStyle = this.d.color; ctx.lineWidth = this.d.width;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(mediaSize.width, y); ctx.stroke();
    });
  }
}
class V implements IPrimitivePaneView {
  constructor(private d: Drawing, private s: ISeriesApi<'Candlestick'>) {}
  renderer(): IPrimitivePaneRenderer { return new R(this.d, this.s); }
}
export class HorizontalLinePrimitive implements ISeriesPrimitive {
  private s: ISeriesApi<'Candlestick'> | null = null;
  constructor(private d: Drawing) {}
  attached(p: SeriesAttachedParameter): void { this.s = p.series as ISeriesApi<'Candlestick'>; p.requestUpdate(); }
  paneViews(): readonly IPrimitivePaneView[] { return this.s ? [new V(this.d, this.s)] : []; }
}
```

- [ ] **Step 2: Implement TrendLinePrimitive** — same shape; in `draw`, convert both `points` via `series.priceToCoordinate(price)` for Y and `chart.timeScale().timeToCoordinate(time)` for X (obtain the timeScale through `attached(param)` → `param.chart`). Draw `moveTo(x0,y0); lineTo(x1,y1)`.
- [ ] **Step 3: Implement RectanglePrimitive** — convert the two corner points to X/Y and `ctx.strokeRect` + translucent `ctx.fillRect`.

- [ ] **Step 4: Typecheck + commit**

```bash
cd frontend && npm run typecheck
git add frontend/lib/chartPrimitives/HorizontalLinePrimitive.ts frontend/lib/chartPrimitives/TrendLinePrimitive.ts frontend/lib/chartPrimitives/RectanglePrimitive.ts
git commit -m "feat(chart): drawing primitives (hline, trendline, rect)"
```

---

### Task 2.2: Backend drawings table + CRUD

**Files:**
- Create: `backend/app/models/drawing.py` — use shared `Base` from `backend/app/models/base.py`, mirror `backend/app/models/alert.py`
- Create: `backend/app/routers/chart_drawings.py` — mirror `backend/app/routers/chart_alerts.py` (session/DI)
- Modify: `backend/app/main.py` — import + `include_router(chart_drawings_router)` (near line 114)
- Create: Alembic migration in `backend/migrations/versions/`
- Test: `backend/tests/test_chart_drawings.py`

- [ ] **Step 1: Failing test**

```python
# backend/tests/test_chart_drawings.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_create_list_delete_drawing():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {"id": "d1", "symbol": "AAPL", "interval": "1D", "kind": "hline",
                   "points": [{"time": 0, "price": 150.0}], "color": "#fff", "width": 1,
                   "createdAt": "2026-06-04T00:00:00Z"}
        r = await ac.post("/chart/drawings", json=payload); assert r.status_code in (200, 201)
        r = await ac.get("/chart/drawings", params={"symbol": "AAPL", "interval": "1D"})
        assert any(d["id"] == "d1" for d in r.json())
        r = await ac.delete("/chart/drawings/d1"); assert r.status_code in (200, 204)
```

- [ ] **Step 2: Run — FAIL.** `cd backend && pytest tests/test_chart_drawings.py -v`

- [ ] **Step 3: Implement the model, schema, router (mirror `backend/app/routers/chart_alerts.py` for style), register the router in `app/main.py`, and generate the migration.** Run alembic from the backend dir so it picks up `backend/migrations/env.py`: `cd backend && alembic revision --autogenerate -m "drawings table"` → the new file lands in `backend/migrations/versions/`.

```python
# backend/app/routers/chart_drawings.py (shape — adapt to project session/DI patterns in chart_alerts.py)
from fastapi import APIRouter, Depends
from pydantic import BaseModel
router = APIRouter(prefix="/chart/drawings", tags=["drawings"])

class DrawingPoint(BaseModel):
    time: int; price: float
class DrawingIn(BaseModel):
    id: str; symbol: str; interval: str; kind: str
    points: list[DrawingPoint]; color: str; width: int; createdAt: str

@router.post("")
async def create(d: DrawingIn): ...   # upsert by id
@router.get("")
async def list_(symbol: str, interval: str): ...   # filter
@router.delete("/{drawing_id}")
async def delete(drawing_id: str): ...
```

- [ ] **Step 4: Run — PASS.** `cd backend && pytest tests/test_chart_drawings.py -v`
- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/chart_drawings.py backend/app/models/drawing.py backend/migrations/versions/*drawings* backend/app/main.py backend/tests/test_chart_drawings.py
git commit -m "feat(api): chart drawings CRUD + table"
```

---

### Task 2.3: Drawing store (frontend, backend-synced)

**Files:**
- Create: `frontend/lib/drawingStore.ts`
- Test: `frontend/lib/drawingStore.test.ts`

Mirror `chartAlertStore.ts` (persist, `skipHydration`, fire-and-forget POST/DELETE, `syncFromBackend`).

- [ ] **Step 1: Failing test** (add/remove in store; assert state shape).
- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3: Implement** `addDrawing(d)`, `removeDrawing(id)`, `clearForSymbol(symbol, interval)`, `syncFromBackend(symbol, interval)`, persisted under `bamendjou:drawings`, posting to `/chart/drawings`.
- [ ] **Step 4: Run — PASS.**
- [ ] **Step 5: Typecheck + commit**

```bash
cd frontend && npm run typecheck
git add frontend/lib/drawingStore.ts frontend/lib/drawingStore.test.ts
git commit -m "feat(chart): drawing store with backend sync"
```

---

### Task 2.4: Wire click-to-draw in ChartWorkspace

**Files:**
- Modify: `frontend/components/organisms/ChartWorkspace/index.tsx`
- Modify: `frontend/components/organisms/ChartOverlays/index.tsx` (or add a `DrawingOverlays` sibling) to attach drawing primitives from `drawingStore`.

- [ ] **Step 1: Add a click handler effect keyed on `drawingTool`**

```ts
useEffect(() => {
  const chart = chartApiRef.current; const series = mainSeriesRef.current;
  if (!chart || !series) return;
  if (!['trendline', 'hline', 'rect', 'alert', 'buy'].includes(drawingTool)) return;
  const pending: { time: number; price: number }[] = [];
  const onClick = (param: { time?: unknown; point?: { x: number; y: number } }) => {
    if (!param.point) return;
    const price = series.coordinateToPrice(param.point.y);
    const time = Number(param.time ?? 0);
    if (price == null) return;
    if (drawingTool === 'hline') { addDrawing({ id: rid(), symbol, interval, kind: 'hline', points: [{ time, price }], color: '#dddddd', width: 1, createdAt: new Date().toISOString() }); return; }
    if (drawingTool === 'alert') { setClickPopover({ kind: 'alert', price, time }); return; }
    if (drawingTool === 'buy')   { setClickPopover({ kind: 'buy', price, time }); return; }
    pending.push({ time, price });
    if (pending.length === 2) {
      addDrawing({ id: rid(), symbol, interval, kind: drawingTool as 'trendline' | 'rect', points: [...pending], color: '#dddddd', width: 1, createdAt: new Date().toISOString() });
      pending.length = 0;
    }
  };
  chart.subscribeClick(onClick);
  return () => chart.unsubscribeClick(onClick);
}, [drawingTool, symbol, interval]);
```

Add `const rid = () => Date.now().toString(36) + Math.random().toString(36).slice(2,6);` and `const { addDrawing } = useDrawingStore();` plus `const [clickPopover, setClickPopover] = useState<{kind:'alert'|'buy'; price:number; time:number}|null>(null);`.

- [ ] **Step 2: Attach drawing primitives** — add a `DrawingOverlays` effect (copy `ChartOverlays`) that, for each `drawingStore.drawings` matching `symbol+interval`, instantiates the right primitive and `attachPrimitive`s it; detaches on change. Sync on mount: `useDrawingStore.getState().syncFromBackend(symbol, interval)`.
- [ ] **Step 3: Typecheck + manual verify** — select Trendline, click two points → line persists and survives reload.
- [ ] **Step 4: Commit**

```bash
git add frontend/components/organisms/ChartWorkspace/index.tsx frontend/components/organisms/ChartOverlays/index.tsx
git commit -m "feat(chart): click-to-draw trendline/hline/rect with persistence"
```

---

## PHASE 3 — Click-to-alert

### Task 3.1: Prefill support in AlertRuleBuilder

**Files:**
- Modify: `frontend/components/organisms/AlertRuleBuilder/index.tsx`

- [ ] **Step 1: Add an optional `prefill` prop**

Extend `Props` (line 10):

```ts
interface Props {
  onClose: () => void;
  editRule?: AlertRule | null;
  prefill?: { price: number } | null;   // from a chart click
}
```

Initialise `conditions` from prefill when present:

```ts
const [conditions, setConditions] = useState<Condition[]>(
  editRule?.group.conditions
  ?? (prefill ? [{ kind: 'price', operator: 'crosses_above', value: prefill.price } as PriceCondition] : [emptyPriceCondition()]),
);
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean (existing call sites pass no `prefill` → defaults to undefined).

- [ ] **Step 3: Commit**

```bash
git add frontend/components/organisms/AlertRuleBuilder/index.tsx
git commit -m "feat(alerts): AlertRuleBuilder accepts a price prefill"
```

---

### Task 3.2: ChartClickPopover + open alert builder on click

**Files:**
- Create: `frontend/components/molecules/ChartClickPopover/index.tsx` (+ `.module.css`)
- Modify: `frontend/components/organisms/ChartWorkspace/index.tsx`

- [ ] **Step 1: Implement the popover** (confirms price + opens the right action)

```tsx
// frontend/components/molecules/ChartClickPopover/index.tsx
'use client';
import { Text } from '@/components/primitives';
import styles from './ChartClickPopover.module.css';

interface Props {
  kind: 'alert' | 'buy';
  price: number;
  qty: number;
  onQty?: (n: number) => void;
  onConfirm: () => void;
  onCancel: () => void;
}
export default function ChartClickPopover({ kind, price, qty, onQty, onConfirm, onCancel }: Props) {
  return (
    <div className={styles.pop}>
      <Text size={12} weight={500}>{kind === 'alert' ? 'Set alert' : 'Paper buy'} @ ${price.toFixed(2)}</Text>
      {kind === 'buy' && (
        <label className={styles.qty}><Text size={11} tone="dim">Shares</Text>
          <input type="number" min={1} value={qty} onChange={(e) => onQty?.(Math.max(1, Number(e.target.value) || 1))} />
        </label>
      )}
      <div className={styles.actions}>
        <button onClick={onCancel}>Cancel</button>
        <button onClick={onConfirm}>{kind === 'alert' ? 'Configure' : 'Buy'}</button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Wire in ChartWorkspace** — when `clickPopover?.kind === 'alert'` and confirmed, open `AlertRuleBuilder` with `prefill={{ price: clickPopover.price }}` (set `showAlerts` true + a `prefillPrice` state), then clear the popover.

- [ ] **Step 3: Typecheck + manual verify** — select Alert tool, click chart → popover → Configure → builder opens pre-filled with the clicked price; saving creates a rule that syncs to backend (Telegram/Gmail on trigger).
- [ ] **Step 4: Commit**

```bash
git add frontend/components/molecules/ChartClickPopover frontend/components/organisms/ChartWorkspace/index.tsx
git commit -m "feat(chart): click-to-alert via prefilled AlertRuleBuilder"
```

---

## PHASE 4 — Click-to-buy (paper underlying)

### Task 4.1: Paper position builder (pure)

**Files:**
- Create: `frontend/lib/paperTrade.ts`
- Test: `frontend/lib/paperTrade.test.ts`

- [ ] **Step 1: Failing test**

```ts
// frontend/lib/paperTrade.test.ts
import { buildPaperStockPosition } from './paperTrade';

describe('buildPaperStockPosition', () => {
  it('creates a long underlying position tagged as paper stock', () => {
    const p = buildPaperStockPosition('AAPL', 150, 10);
    expect(p.symbol).toBe('AAPL');
    expect(p.contract).toBe('AAPL|STOCK');
    expect(p.entryPrice).toBe(150);
    expect(p.contracts).toBe(10);
    expect(p.direction).toBe('long');
  });
});
```

- [ ] **Step 2: Run — FAIL.** `cd frontend && npm run test -- --testPathPattern=paperTrade`

- [ ] **Step 3: Implement** (conform to `PortfolioPosition` in `types/domain.ts`; stock pseudo-contract `SYMBOL|STOCK`, no expiry/targets)

```ts
// frontend/lib/paperTrade.ts
import type { PortfolioPosition } from '@/types/domain';

export function buildPaperStockPosition(symbol: string, price: number, shares: number): PortfolioPosition {
  const today = new Date().toISOString().slice(0, 10);
  return {
    symbol,
    contract: `${symbol}|STOCK`,
    direction: 'long',
    entryPrice: price,
    contracts: shares,
    entryDate: today,
    expiry: '',
    stop: 0,
    targets: [],
    dteTotal: 0,
    dteRemaining: 0,
    status: 'PENDING',
    recId: 'PAPER-' + Date.now().toString(36),
    currentPrice: price,
    pnlDollar: 0,
    pnlPct: 0,
  } as PortfolioPosition;
}
```

> Verify each field against `types/domain.ts`; adjust names if the `PortfolioPosition` shape differs. The portfolio table should render `|STOCK` rows without an option-specific column blowing up (check `PortfolioPosition` optional fields).

- [ ] **Step 4: Run — PASS.**
- [ ] **Step 5: Typecheck + commit**

```bash
cd frontend && npm run typecheck
git add frontend/lib/paperTrade.ts frontend/lib/paperTrade.test.ts
git commit -m "feat(chart): paper underlying-stock position builder"
```

---

### Task 4.2: Wire click-to-buy in ChartWorkspace

**Files:**
- Modify: `frontend/components/organisms/ChartWorkspace/index.tsx`

- [ ] **Step 1: On buy-popover confirm, add the paper position**

```ts
// when clickPopover.kind === 'buy' and confirmed:
usePortfolioStore.getState().addPosition(buildPaperStockPosition(symbol, clickPopover.price, buyQty));
setClickPopover(null);
```

Add `import { usePortfolioStore } from '@/lib/portfolioStore';`, `import { buildPaperStockPosition } from '@/lib/paperTrade';`, and a `const [buyQty, setBuyQty] = useState(1);`.

- [ ] **Step 2: Typecheck + manual verify** — select Buy tool, click chart → popover with qty → Buy → a `SYMBOL|STOCK` paper position appears in `/portfolio` (and syncs via existing `postPosition`).
- [ ] **Step 3: Commit**

```bash
git add frontend/components/organisms/ChartWorkspace/index.tsx
git commit -m "feat(chart): click-to-buy adds paper underlying position"
```

---

## Final verification

- [ ] **Frontend full test + typecheck:** `cd frontend && npm run test && npm run typecheck` — all pass, clean.
- [ ] **Backend tests:** `cd backend && pytest -q` — green.
- [ ] **Manual smoke on `/chart`:** toggle each overlay on/off, edit a default param and see it update, draw a trendline + hline + rectangle (persist across reload), set an alert by clicking (rule appears, syncs), paper-buy by clicking (position appears in portfolio).
- [ ] **Finish the branch** with `superpowers:finishing-a-development-branch`.

---

## Self-review notes (coverage map)

- MA Suite → 1.8/1.9 · EMA/SMA cross → 1.3/1.9 · Anchored VWAP → 1.1/1.9 · Key Levels → 1.2/1.9 · Higher-TF Levels → 1.9 (resample MVP, fetch follow-up) · Volume Profile → 1.4/1.6/1.9 · Signal Markers → 1.3/1.9 · MTF Dashboard → 1.5/1.7/1.9 (single-row MVP, multi-TF follow-up).
- On/off + editable defaults → 0.2 + 1.8 (existing IndicatorPanel pattern).
- Drawing → 2.1–2.4 · Click-to-alert → 3.1–3.2 · Click-to-buy → 4.1–4.2.
- All alerts → backend/notifications → reuses `chartAlertStore` → `/alerts/rules` (already live); no new alert pipeline.
- **Known follow-ups (explicitly deferred, not gaps):** true HTF candle fetch (vs resample) via the existing backend `candles_router`; full multi-TF dashboard fetch (same endpoint); portfolio table polish for `|STOCK` rows.
