# Chart Interaction Stability Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the stability bugs identified in the chart interaction code review — eliminating primitive flicker during drag, lost final drag positions, chart lock-up on mobile pointer-cancel, stale null refs passed to overlay components, and click-jitter suppressing text-edit.

**Architecture:** Four orthogonal changes: (1) mutable `update()` on all drawing primitives + diff-based `DrawingOverlays`; (2) drag lifecycle hardening in `ChartWorkspace`; (3) stable `updateDrawing` ref to remove it from drag-effect deps; (4) `onSeriesReady` callback from `ChartPane` so `ChartWorkspace` holds chart/series in React state, eliminating stale-ref propagation to all overlay children.

**Tech Stack:** TypeScript 5.7, React 18, lightweight-charts v5, Zustand v5, Jest (no DOM — unit tests only for pure/class logic).

---

## Files

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `frontend/lib/chartPrimitives/types.ts` | Shared `UpdatablePrimitive` interface |
| Modify | `frontend/lib/chartPrimitives/HorizontalLinePrimitive.ts` | Add `update()` |
| Modify | `frontend/lib/chartPrimitives/TrendLinePrimitive.ts` | Add `update()` |
| Modify | `frontend/lib/chartPrimitives/RectanglePrimitive.ts` | Add `update()` |
| Modify | `frontend/lib/chartPrimitives/TextPrimitive.ts` | Add `update()` |
| Create | `frontend/lib/chartPrimitives/primitives.test.ts` | Unit tests for `update()` |
| Create | `frontend/lib/chart/drawingOverlaysDiff.ts` | Pure diff utility (testable) |
| Create | `frontend/lib/chart/drawingOverlaysDiff.test.ts` | Tests for diff utility |
| Modify | `frontend/components/organisms/DrawingOverlays/index.tsx` | Diff-based primitive management |
| Modify | `frontend/components/organisms/ChartPane/index.tsx` | Add `onSeriesReady` prop |
| Modify | `frontend/components/organisms/ChartWorkspace/index.tsx` | Drag fixes + useState for chart/series |

---

## Task 1: UpdatablePrimitive interface + `update()` on all 4 drawing primitives

**Why:** `DrawingOverlays` currently detaches and re-attaches every primitive on each `drawings` change. During drag (throttled to 50ms), this destroys and recreates all canvas objects repeatedly, causing flicker. Adding `update()` lets the diff layer mutate data in-place and request a single redraw.

**Files:**
- Create: `frontend/lib/chartPrimitives/types.ts`
- Modify: `frontend/lib/chartPrimitives/HorizontalLinePrimitive.ts`
- Modify: `frontend/lib/chartPrimitives/TrendLinePrimitive.ts`
- Modify: `frontend/lib/chartPrimitives/RectanglePrimitive.ts`
- Modify: `frontend/lib/chartPrimitives/TextPrimitive.ts`
- Create: `frontend/lib/chartPrimitives/primitives.test.ts`

---

- [ ] **Step 1: Write the failing tests**

Create `frontend/lib/chartPrimitives/primitives.test.ts`:

```ts
import { HorizontalLinePrimitive } from './HorizontalLinePrimitive';
import { TrendLinePrimitive } from './TrendLinePrimitive';
import { RectanglePrimitive } from './RectanglePrimitive';
import { TextPrimitive } from './TextPrimitive';
import type { Drawing } from '@/types/overlays';

const baseDrawing = (price = 100): Drawing => ({
  id: 'test', symbol: 'SPY', interval: '1D' as const,
  kind: 'hline', points: [{ time: 1000, price }],
  color: '#fff', width: 1, createdAt: '',
});

const trendDrawing = (p0 = 100, p1 = 110): Drawing => ({
  id: 'test', symbol: 'SPY', interval: '1D' as const,
  kind: 'trendline',
  points: [{ time: 1000, price: p0 }, { time: 2000, price: p1 }],
  color: '#fff', width: 1, createdAt: '',
});

const mockParam = (requestUpdate: jest.Mock) => ({
  chart: { timeScale: () => ({ timeToCoordinate: jest.fn(() => null) }) },
  series: { priceToCoordinate: jest.fn(() => null) },
  requestUpdate,
  paneId: '0',
} as never);

describe('HorizontalLinePrimitive.update()', () => {
  it('calls requestUpdate on update after attach', () => {
    const req = jest.fn();
    const prim = new HorizontalLinePrimitive(baseDrawing());
    prim.attached(mockParam(req));
    req.mockClear();
    prim.update(baseDrawing(200));
    expect(req).toHaveBeenCalledTimes(1);
  });

  it('does not throw when called before attach', () => {
    const prim = new HorizontalLinePrimitive(baseDrawing());
    expect(() => prim.update(baseDrawing(200))).not.toThrow();
  });
});

describe('TrendLinePrimitive.update()', () => {
  it('calls requestUpdate on update after attach', () => {
    const req = jest.fn();
    const prim = new TrendLinePrimitive(trendDrawing());
    prim.attached(mockParam(req));
    req.mockClear();
    prim.update(trendDrawing(150, 160));
    expect(req).toHaveBeenCalledTimes(1);
  });
});

describe('RectanglePrimitive.update()', () => {
  it('calls requestUpdate on update after attach', () => {
    const req = jest.fn();
    const d: Drawing = { ...trendDrawing(), kind: 'rect' };
    const prim = new RectanglePrimitive(d);
    prim.attached(mockParam(req));
    req.mockClear();
    prim.update({ ...d, color: '#f00' });
    expect(req).toHaveBeenCalledTimes(1);
  });
});

describe('TextPrimitive.update()', () => {
  it('calls requestUpdate on update after attach', () => {
    const req = jest.fn();
    const d: Drawing = { ...baseDrawing(), kind: 'text', text: 'hello' };
    const prim = new TextPrimitive(d);
    prim.attached(mockParam(req));
    req.mockClear();
    prim.update({ ...d, text: 'world' });
    expect(req).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run to confirm tests fail**

```bash
cd frontend && npm run test -- --testPathPattern=primitives.test
```

Expected: compilation error — `update` does not exist on any primitive type.

- [ ] **Step 3: Create `types.ts`**

Create `frontend/lib/chartPrimitives/types.ts`:

```ts
import type { ISeriesPrimitive } from 'lightweight-charts';
import type { Drawing } from '@/types/overlays';

/** Drawing primitive that supports in-place data mutation without detach/re-attach. */
export interface UpdatablePrimitive extends ISeriesPrimitive {
  update(drawing: Drawing): void;
}
```

- [ ] **Step 4: Update `HorizontalLinePrimitive.ts`**

Replace the entire file with. **Note:** `d` is intentionally changed from `readonly` to mutable — this enables `update()` to swap drawing data in-place and trigger a single redraw without detach/re-attach.

```ts
import type {
  ISeriesPrimitive,
  IPrimitivePaneView,
  IPrimitivePaneRenderer,
  ISeriesApi,
  SeriesAttachedParameter,
} from 'lightweight-charts';
import type { CanvasRenderingTarget2D } from 'fancy-canvas';
import type { Drawing } from '@/types/overlays';
import type { UpdatablePrimitive } from './types';

class HorizontalLineRenderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly d: Drawing,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}

  draw(target: CanvasRenderingTarget2D): void {
    target.useMediaCoordinateSpace(({ mediaSize, context: ctx }) => {
      const y = this.series.priceToCoordinate(this.d.points[0].price);
      if (y === null) return;
      ctx.strokeStyle = this.d.color;
      ctx.lineWidth = this.d.width;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(mediaSize.width, y);
      ctx.stroke();
    });
  }
}

class HorizontalLinePaneView implements IPrimitivePaneView {
  constructor(
    private readonly d: Drawing,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}

  renderer(): IPrimitivePaneRenderer | null {
    return new HorizontalLineRenderer(this.d, this.series);
  }
}

export class HorizontalLinePrimitive implements UpdatablePrimitive {
  private series: ISeriesApi<'Candlestick'> | null = null;
  private requestUpdateFn?: () => void;

  constructor(private d: Drawing) {}

  attached(param: SeriesAttachedParameter): void {
    this.series = param.series as ISeriesApi<'Candlestick'>;
    this.requestUpdateFn = param.requestUpdate;
    param.requestUpdate();
  }

  update(drawing: Drawing): void {
    this.d = drawing;
    this.requestUpdateFn?.();
  }

  paneViews(): readonly IPrimitivePaneView[] {
    if (!this.series) return [];
    return [new HorizontalLinePaneView(this.d, this.series)];
  }
}
```

- [ ] **Step 5: Update `TrendLinePrimitive.ts`**

Replace the entire file with:

```ts
import type {
  ISeriesPrimitive,
  IPrimitivePaneView,
  IPrimitivePaneRenderer,
  IChartApi,
  ISeriesApi,
  SeriesAttachedParameter,
  Time,
} from 'lightweight-charts';
import type { CanvasRenderingTarget2D } from 'fancy-canvas';
import type { Drawing } from '@/types/overlays';
import type { UpdatablePrimitive } from './types';

class TrendLineRenderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly d: Drawing,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}

  draw(target: CanvasRenderingTarget2D): void {
    target.useMediaCoordinateSpace(({ context: ctx }) => {
      const toX = (t: number) => this.chart.timeScale().timeToCoordinate(t as unknown as Time);
      const toY = (p: number) => this.series.priceToCoordinate(p);

      const x0 = toX(this.d.points[0].time);
      const y0 = toY(this.d.points[0].price);
      const x1 = toX(this.d.points[1].time);
      const y1 = toY(this.d.points[1].price);

      if (x0 === null || y0 === null || x1 === null || y1 === null) return;

      ctx.strokeStyle = this.d.color;
      ctx.lineWidth = this.d.width;
      ctx.beginPath();
      ctx.moveTo(x0, y0);
      ctx.lineTo(x1, y1);
      ctx.stroke();
    });
  }
}

class TrendLinePaneView implements IPrimitivePaneView {
  constructor(
    private readonly d: Drawing,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}

  renderer(): IPrimitivePaneRenderer | null {
    return new TrendLineRenderer(this.d, this.chart, this.series);
  }
}

export class TrendLinePrimitive implements UpdatablePrimitive {
  private chart: IChartApi | null = null;
  private series: ISeriesApi<'Candlestick'> | null = null;
  private requestUpdateFn?: () => void;

  constructor(private d: Drawing) {}

  attached(param: SeriesAttachedParameter): void {
    this.chart = param.chart;
    this.series = param.series as ISeriesApi<'Candlestick'>;
    this.requestUpdateFn = param.requestUpdate;
    param.requestUpdate();
  }

  update(drawing: Drawing): void {
    this.d = drawing;
    this.requestUpdateFn?.();
  }

  paneViews(): readonly IPrimitivePaneView[] {
    if (!this.chart || !this.series) return [];
    return [new TrendLinePaneView(this.d, this.chart, this.series)];
  }
}
```

- [ ] **Step 6: Update `RectanglePrimitive.ts`**

Replace the entire file with:

```ts
import type {
  ISeriesPrimitive,
  IPrimitivePaneView,
  IPrimitivePaneRenderer,
  IChartApi,
  ISeriesApi,
  SeriesAttachedParameter,
  Time,
} from 'lightweight-charts';
import type { CanvasRenderingTarget2D } from 'fancy-canvas';
import type { Drawing } from '@/types/overlays';
import type { UpdatablePrimitive } from './types';

class RectangleRenderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly d: Drawing,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}

  draw(target: CanvasRenderingTarget2D): void {
    target.useMediaCoordinateSpace(({ context: ctx }) => {
      const toX = (t: number) => this.chart.timeScale().timeToCoordinate(t as unknown as Time);
      const toY = (p: number) => this.series.priceToCoordinate(p);

      const x0 = toX(this.d.points[0].time);
      const y0 = toY(this.d.points[0].price);
      const x1 = toX(this.d.points[1].time);
      const y1 = toY(this.d.points[1].price);

      if (x0 === null || y0 === null || x1 === null || y1 === null) return;

      const x = Math.min(x0, x1);
      const y = Math.min(y0, y1);
      const w = Math.abs(x1 - x0);
      const h = Math.abs(y1 - y0);

      ctx.strokeStyle = this.d.color;
      ctx.lineWidth = this.d.width;
      ctx.fillStyle = 'rgba(120,140,255,0.10)';
      ctx.fillRect(x, y, w, h);
      ctx.strokeRect(x, y, w, h);
    });
  }
}

class RectanglePaneView implements IPrimitivePaneView {
  constructor(
    private readonly d: Drawing,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}

  renderer(): IPrimitivePaneRenderer | null {
    return new RectangleRenderer(this.d, this.chart, this.series);
  }
}

export class RectanglePrimitive implements UpdatablePrimitive {
  private chart: IChartApi | null = null;
  private series: ISeriesApi<'Candlestick'> | null = null;
  private requestUpdateFn?: () => void;

  constructor(private d: Drawing) {}

  attached(param: SeriesAttachedParameter): void {
    this.chart = param.chart;
    this.series = param.series as ISeriesApi<'Candlestick'>;
    this.requestUpdateFn = param.requestUpdate;
    param.requestUpdate();
  }

  update(drawing: Drawing): void {
    this.d = drawing;
    this.requestUpdateFn?.();
  }

  paneViews(): readonly IPrimitivePaneView[] {
    if (!this.chart || !this.series) return [];
    return [new RectanglePaneView(this.d, this.chart, this.series)];
  }
}
```

- [ ] **Step 7: Update `TextPrimitive.ts`**

Replace the entire file with:

```ts
import type {
  ISeriesPrimitive,
  IPrimitivePaneView,
  IPrimitivePaneRenderer,
  IChartApi,
  ISeriesApi,
  SeriesAttachedParameter,
  Time,
} from 'lightweight-charts';
import type { CanvasRenderingTarget2D } from 'fancy-canvas';
import type { Drawing } from '@/types/overlays';
import type { UpdatablePrimitive } from './types';

class TextRenderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly d: Drawing,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}

  draw(target: CanvasRenderingTarget2D): void {
    target.useMediaCoordinateSpace(({ context: ctx }) => {
      const p = this.d.points[0];
      const x = this.chart.timeScale().timeToCoordinate(p.time as unknown as Time);
      const y = this.series.priceToCoordinate(p.price);
      if (x === null || y === null) return;

      const label = this.d.text ?? '';
      ctx.font = '12px sans-serif';
      const w = ctx.measureText(label).width;

      ctx.fillStyle = 'rgba(20,24,40,0.85)';
      ctx.fillRect(x, y - 16, w + 10, 18);
      ctx.strokeStyle = this.d.color;
      ctx.lineWidth = 1;
      ctx.strokeRect(x, y - 16, w + 10, 18);

      ctx.fillStyle = '#fff';
      ctx.fillText(label, x + 5, y - 3);
    });
  }
}

class TextPaneView implements IPrimitivePaneView {
  constructor(
    private readonly d: Drawing,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}

  renderer(): IPrimitivePaneRenderer | null {
    return new TextRenderer(this.d, this.chart, this.series);
  }
}

export class TextPrimitive implements UpdatablePrimitive {
  private chart: IChartApi | null = null;
  private series: ISeriesApi<'Candlestick'> | null = null;
  private requestUpdateFn?: () => void;

  constructor(private d: Drawing) {}

  attached(param: SeriesAttachedParameter): void {
    this.chart = param.chart;
    this.series = param.series as ISeriesApi<'Candlestick'>;
    this.requestUpdateFn = param.requestUpdate;
    param.requestUpdate();
  }

  update(drawing: Drawing): void {
    this.d = drawing;
    this.requestUpdateFn?.();
  }

  paneViews(): readonly IPrimitivePaneView[] {
    if (!this.chart || !this.series) return [];
    return [new TextPaneView(this.d, this.chart, this.series)];
  }
}
```

- [ ] **Step 8: Run tests — expect pass**

```bash
cd frontend && npm run test -- --testPathPattern=primitives.test
```

Expected: 5 tests pass (2 for HorizontalLine, 1 each for TrendLine, Rectangle, Text).

- [ ] **Step 9: Typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: no errors.

- [ ] **Step 10: Commit**

```bash
git add frontend/lib/chartPrimitives/types.ts frontend/lib/chartPrimitives/HorizontalLinePrimitive.ts frontend/lib/chartPrimitives/TrendLinePrimitive.ts frontend/lib/chartPrimitives/RectanglePrimitive.ts frontend/lib/chartPrimitives/TextPrimitive.ts frontend/lib/chartPrimitives/primitives.test.ts
git commit -m "feat(chart): add update() to drawing primitives via UpdatablePrimitive interface"
```

---

## Task 2: Pure diff utility + diff-based DrawingOverlays

**Why:** Replace the destroy-all / recreate-all pattern in `DrawingOverlays` with a keyed diff. Only drawings that are added, removed, or changed are touched per render. During a 50ms-throttled drag, only the one drawing being moved gets `update()` called — no detach/re-attach.

**Files:**
- Create: `frontend/lib/chart/drawingOverlaysDiff.ts`
- Create: `frontend/lib/chart/drawingOverlaysDiff.test.ts`
- Modify: `frontend/components/organisms/DrawingOverlays/index.tsx`

---

- [ ] **Step 1: Write failing tests for the diff utility**

Create `frontend/lib/chart/drawingOverlaysDiff.test.ts`:

```ts
import { diffDrawings } from './drawingOverlaysDiff';
import type { AttachedEntry } from './drawingOverlaysDiff';
import type { Drawing } from '@/types/overlays';

const d = (id: string, price = 100): Drawing => ({
  id, symbol: 'SPY', interval: '1D' as const,
  kind: 'hline', points: [{ time: 1000, price }],
  color: '#fff', width: 1, createdAt: '',
});

const mockEntry = (drawing: Drawing): AttachedEntry => ({
  primitive: { update: jest.fn(), attached: jest.fn(), paneViews: jest.fn(() => []) },
  drawing,
});

describe('diffDrawings', () => {
  it('adds all drawings when prev map is empty', () => {
    const result = diffDrawings(new Map(), [d('a'), d('b')]);
    expect(result.toAdd).toHaveLength(2);
    expect(result.toRemove).toHaveLength(0);
    expect(result.toUpdate).toHaveLength(0);
  });

  it('removes drawings absent from next', () => {
    const prev = new Map([['a', mockEntry(d('a'))]]);
    const result = diffDrawings(prev, []);
    expect(result.toRemove).toHaveLength(1);
    expect(result.toRemove[0].drawing.id).toBe('a');
    expect(result.toAdd).toHaveLength(0);
  });

  it('updates drawings whose object reference changed', () => {
    const original = d('a', 100);
    const updated = d('a', 200); // same id, different reference
    const prev = new Map([['a', mockEntry(original)]]);
    const result = diffDrawings(prev, [updated]);
    expect(result.toUpdate).toHaveLength(1);
    expect(result.toUpdate[0].drawing).toBe(updated);
    expect(result.toAdd).toHaveLength(0);
    expect(result.toRemove).toHaveLength(0);
  });

  it('skips update when drawing reference is identical', () => {
    const drawing = d('a');
    const prev = new Map([['a', mockEntry(drawing)]]);
    const result = diffDrawings(prev, [drawing]); // same reference
    expect(result.toUpdate).toHaveLength(0);
    expect(result.toAdd).toHaveLength(0);
    expect(result.toRemove).toHaveLength(0);
  });

  it('handles add + remove + update in one call', () => {
    const existing = d('a');
    const modified = d('a', 999);
    const toBeRemoved = d('b');
    const toBeAdded = d('c');
    const prev = new Map([
      ['a', mockEntry(existing)],
      ['b', mockEntry(toBeRemoved)],
    ]);
    const result = diffDrawings(prev, [modified, toBeAdded]);
    expect(result.toAdd).toHaveLength(1);
    expect(result.toAdd[0].id).toBe('c');
    expect(result.toRemove).toHaveLength(1);
    expect(result.toRemove[0].drawing.id).toBe('b');
    expect(result.toUpdate).toHaveLength(1);
    expect(result.toUpdate[0].drawing.id).toBe('a');
  });
});
```

- [ ] **Step 2: Run to confirm tests fail**

```bash
cd frontend && npm run test -- --testPathPattern=drawingOverlaysDiff
```

Expected: module not found.

- [ ] **Step 3: Create `drawingOverlaysDiff.ts`**

Create `frontend/lib/chart/drawingOverlaysDiff.ts`:

```ts
import type { Drawing } from '@/types/overlays';
import type { UpdatablePrimitive } from '@/lib/chartPrimitives/types';

export interface AttachedEntry {
  primitive: UpdatablePrimitive;
  drawing: Drawing;
}

export interface DiffResult {
  toAdd: Drawing[];
  toRemove: AttachedEntry[];
  toUpdate: { entry: AttachedEntry; drawing: Drawing }[];
}

/**
 * Computes which drawing primitives need to be added, removed, or updated.
 * Uses object reference equality for update detection — Zustand produces a new
 * Drawing object any time a field changes, so reference check is sufficient.
 */
export function diffDrawings(
  prev: Map<string, AttachedEntry>,
  next: Drawing[],
): DiffResult {
  // Build id→drawing map once (O(m)) to avoid O(n×m) inner find() per prev entry.
  const nextById = new Map(next.map((d) => [d.id, d]));
  const toRemove: AttachedEntry[] = [];
  const toUpdate: { entry: AttachedEntry; drawing: Drawing }[] = [];
  const toAdd: Drawing[] = [];

  prev.forEach((entry, id) => {
    const nextDrawing = nextById.get(id);
    if (!nextDrawing) {
      toRemove.push(entry);
    } else if (entry.drawing !== nextDrawing) {
      toUpdate.push({ entry, drawing: nextDrawing });
    }
  });

  for (const drawing of next) {
    if (!prev.has(drawing.id)) {
      toAdd.push(drawing);
    }
  }

  return { toAdd, toRemove, toUpdate };
}
```

- [ ] **Step 4: Run tests — expect pass**

```bash
cd frontend && npm run test -- --testPathPattern=drawingOverlaysDiff
```

Expected: 5 tests pass.

- [ ] **Step 5: Rewrite `DrawingOverlays/index.tsx`**

Replace the entire file with:

```tsx
'use client';

import { useEffect, useRef } from 'react';
import type { IChartApi, ISeriesApi } from 'lightweight-charts';
import type { Drawing } from '@/types/overlays';
import type { UpdatablePrimitive } from '@/lib/chartPrimitives/types';
import type { AttachedEntry } from '@/lib/chart/drawingOverlaysDiff';
import { diffDrawings } from '@/lib/chart/drawingOverlaysDiff';
import { HorizontalLinePrimitive } from '@/lib/chartPrimitives/HorizontalLinePrimitive';
import { TrendLinePrimitive } from '@/lib/chartPrimitives/TrendLinePrimitive';
import { RectanglePrimitive } from '@/lib/chartPrimitives/RectanglePrimitive';
import { TextPrimitive } from '@/lib/chartPrimitives/TextPrimitive';

interface Props {
  chart: IChartApi | null;
  mainSeries: ISeriesApi<'Candlestick'> | null;
  drawings: Drawing[];
}

function makePrimitive(drawing: Drawing): UpdatablePrimitive | null {
  switch (drawing.kind) {
    case 'hline':     return new HorizontalLinePrimitive(drawing);
    case 'trendline': return new TrendLinePrimitive(drawing);
    case 'rect':      return new RectanglePrimitive(drawing);
    case 'text':      return new TextPrimitive(drawing);
    default:          return null;
  }
}

export default function DrawingOverlays({ chart, mainSeries, drawings }: Props) {
  // Keyed by drawing.id — persists across renders
  const attachedRef = useRef<Map<string, AttachedEntry>>(new Map());

  // Effect 1: diff-based update. No cleanup function here — that is handled by
  // Effect 2 below. If cleanup lived here, React would call it on every `drawings`
  // change (before each re-run), which would detach all primitives on every drag tick.
  useEffect(() => {
    if (!chart || !mainSeries) return;
    const attached = attachedRef.current;
    const { toAdd, toRemove, toUpdate } = diffDrawings(attached, drawings);

    for (const entry of toRemove) {
      try { mainSeries.detachPrimitive(entry.primitive); } catch { /* ignore */ }
      attached.delete(entry.drawing.id);
    }

    for (const { entry, drawing } of toUpdate) {
      entry.primitive.update(drawing);
      // Create a new AttachedEntry object rather than mutating the existing one,
      // so the map stays consistent under concurrent React scheduling.
      attached.set(drawing.id, { primitive: entry.primitive, drawing });
    }

    for (const drawing of toAdd) {
      const primitive = makePrimitive(drawing);
      if (!primitive) continue;
      mainSeries.attachPrimitive(primitive);
      attached.set(drawing.id, { primitive, drawing });
    }
  }, [chart, mainSeries, drawings]);

  // Effect 2: detach ALL primitives from the OLD series when chart/series changes.
  // Deps are intentionally `[chart, mainSeries]` only — not `drawings` — so this
  // cleanup never fires on a drawings update, only on series replacement or unmount.
  useEffect(() => {
    const attached = attachedRef.current;
    return () => {
      for (const entry of attached.values()) {
        try { mainSeries?.detachPrimitive(entry.primitive); } catch { /* ignore */ }
      }
      attached.clear();
    };
  }, [chart, mainSeries]);

  return null;
}
```

- [ ] **Step 6: Typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: no errors.

- [ ] **Step 7: Run all tests**

```bash
cd frontend && npm run test
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add frontend/lib/chart/drawingOverlaysDiff.ts frontend/lib/chart/drawingOverlaysDiff.test.ts frontend/components/organisms/DrawingOverlays/index.tsx
git commit -m "feat(chart): diff-based DrawingOverlays — eliminate detach/re-attach on every drag tick"
```

---

## Task 3: Fix drag lifecycle in ChartWorkspace

**Why:** Three bugs in the drag handler: (a) `onPointerUp` never saves the final pointer position — the drawing snaps to wherever the last 50ms throttle fired; (b) no `pointercancel` handler — on mobile interrupt, chart stays locked with scroll/zoom disabled; (c) `wasDragRef` is set on any `pointermove`, including sub-pixel mouse jitter, causing text-edit popover to fail to open after a clean click on a label.

Additionally, `updateDrawing` is in the drag effect deps — if Zustand re-creates the action reference on any state change, all pointer listeners are torn down and re-registered mid-drag. Fix with a stable ref.

**Files:**
- Modify: `frontend/components/organisms/ChartWorkspace/index.tsx`

---

- [ ] **Step 1: Add stable `updateDrawingRef` just before the drag effect**

In `ChartWorkspace/index.tsx`, locate these lines (around line 193–196):

```ts
const drawings = useDrawingStore((s) => s.drawings);
const addDrawing = useDrawingStore((s) => s.addDrawing);
const removeDrawing = useDrawingStore((s) => s.removeDrawing);
const updateDrawing = useDrawingStore((s) => s.updateDrawing);
const clearForSymbol = useDrawingStore((s) => s.clearForSymbol);
```

Add immediately after them (before the `structureVisible` line):

```ts
// Stable ref so the drag effect does not need updateDrawing in its deps.
// Zustand actions are already stable, but this guards against any future refactor.
const updateDrawingRef = useRef(updateDrawing);
useEffect(() => { updateDrawingRef.current = updateDrawing; }, [updateDrawing]);
```

- [ ] **Step 2: Extract `calcUpdatedPoints` helper inside the drag effect**

Locate the drag effect (the `useEffect` beginning with `if (drawingTool !== 'cursor') return;`). Inside the effect body, just above `const onPointerDown`, add:

```ts
const calcUpdatedPoints = (drag: DragState, x: number, y: number): DrawingPoint[] | null => {
  const newTime = chart.timeScale().coordinateToTime(x);
  const newPrice = series.coordinateToPrice(y);
  if (newTime == null || newPrice == null) return null;
  const startTime0 = chart.timeScale().coordinateToTime(drag.startX);
  const startPrice0 = series.coordinateToPrice(drag.startY);
  if (startTime0 == null || startPrice0 == null) return null;
  const dt = Number(newTime) - Number(startTime0);
  const dp = newPrice - startPrice0;
  const { handle, startDrawing } = drag;
  if (handle === 'p0') return [{ time: Number(newTime), price: newPrice }, ...startDrawing.points.slice(1)];
  if (handle === 'p1') return [startDrawing.points[0], { time: Number(newTime), price: newPrice }];
  if (startDrawing.kind === 'hline') return startDrawing.points.map((p) => ({ time: p.time, price: p.price + dp }));
  return startDrawing.points.map((p) => ({ time: p.time + dt, price: p.price + dp }));
};
```

- [ ] **Step 3: Fix `onPointerMove` — use stable ref + 4px threshold**

Find the existing `onPointerMove` handler inside the drag effect and replace it entirely:

```ts
const onPointerMove = (e: PointerEvent) => {
  const drag = dragRef.current;
  if (!drag) return;
  const rect = el.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const y = e.clientY - rect.top;
  // Only flag as drag after 4px of movement — prevents click jitter from
  // suppressing the text-edit popover on a stationary click.
  if (Math.hypot(x - drag.startX, y - drag.startY) > 4) {
    wasDragRef.current = true;
  }
  const updatedPoints = calcUpdatedPoints(drag, x, y);
  if (!updatedPoints) return;
  const now = Date.now();
  if (now - (drag.lastUpdateMs ?? 0) >= 50) {
    drag.lastUpdateMs = now;
    updateDrawingRef.current(drag.id, { points: updatedPoints });
  }
};
```

- [ ] **Step 4: Replace `onPointerUp` — save final position**

Find the existing `onPointerUp` handler and replace it:

```ts
const onPointerUp = (e: PointerEvent) => {
  const drag = dragRef.current;
  if (!drag) return;
  // Always write the exact release position, bypassing the 50ms throttle.
  const rect = el.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const y = e.clientY - rect.top;
  const updatedPoints = calcUpdatedPoints(drag, x, y);
  if (updatedPoints) {
    updateDrawingRef.current(drag.id, { points: updatedPoints });
  }
  dragRef.current = null;
  chart.applyOptions({ handleScroll: true, handleScale: true });
};
```

- [ ] **Step 5: Add `onPointerCancel` handler**

Add this immediately after `onPointerUp`:

```ts
const onPointerCancel = () => {
  if (!dragRef.current) return;
  // Pointer was interrupted (e.g. iOS gesture takeover). Keep last throttled
  // position; just re-enable chart controls.
  dragRef.current = null;
  chart.applyOptions({ handleScroll: true, handleScale: true });
};
```

- [ ] **Step 6: Register and deregister `pointercancel`**

Find the event-listener registration block:

```ts
el.addEventListener('pointerdown', onPointerDown);
el.addEventListener('pointermove', onPointerMove);
el.addEventListener('pointerup', onPointerUp);
```

Replace with:

```ts
el.addEventListener('pointerdown', onPointerDown);
el.addEventListener('pointermove', onPointerMove);
el.addEventListener('pointerup', onPointerUp);
el.addEventListener('pointercancel', onPointerCancel);
```

Find the cleanup block:

```ts
el.removeEventListener('pointerdown', onPointerDown);
el.removeEventListener('pointermove', onPointerMove);
el.removeEventListener('pointerup', onPointerUp);
```

Replace with:

```ts
el.removeEventListener('pointerdown', onPointerDown);
el.removeEventListener('pointermove', onPointerMove);
el.removeEventListener('pointerup', onPointerUp);
el.removeEventListener('pointercancel', onPointerCancel);
```

- [ ] **Step 7: Remove `updateDrawing` from drag effect deps**

Find the deps array at the bottom of the drag effect:

```ts
}, [drawingTool, symbol, interval, updateDrawing]);
```

Replace with (eslint-disable goes on the line immediately before the closing bracket, matching the pattern used elsewhere in this file):

```ts
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drawingTool, symbol, interval]);
```

- [ ] **Step 8: Typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add frontend/components/organisms/ChartWorkspace/index.tsx
git commit -m "fix(chart): final drag position, pointercancel, 4px threshold, stable updateDrawing ref"
```

---

## Task 4: Add `onSeriesReady` callback to ChartPane

**Why:** `ChartPane` currently assigns `mainSeriesRef.current` inside a `useEffect`, which is invisible to React's render cycle. `ChartWorkspace` passes `chartApiRef.current` and `mainSeriesRef.current` — raw values at render time — to `DrawingOverlays`, `ChartOverlays`, and the `PreviewPrimitive` effect. On the first render these are `null` and the effects bail out. They only work because a WS candle tick triggers a re-render later. Adding an `onSeriesReady` callback lets `ChartWorkspace` hold the chart and series in React state, which propagates correctly.

This task only changes `ChartPane`. It is backward-compatible — existing callers need no changes yet.

**Files:**
- Modify: `frontend/components/organisms/ChartPane/index.tsx`

---

- [ ] **Step 1: Add `onSeriesReady` to Props**

In `ChartPane/index.tsx`, find the `Props` interface:

```ts
interface Props {
  series: SeriesConfig[];
  onCrosshairMove?: (time: string | null, values: Record<string, number>) => void;
  height?: number;   // 0 or omitted = fill container height
  chartApiRef?: React.MutableRefObject<IChartApi | null>;
  mainSeriesRef?: React.MutableRefObject<ISeriesApi<'Candlestick'> | null>;
}
```

Replace with:

```ts
interface Props {
  series: SeriesConfig[];
  onCrosshairMove?: (time: string | null, values: Record<string, number>) => void;
  height?: number;   // 0 or omitted = fill container height
  chartApiRef?: React.MutableRefObject<IChartApi | null>;
  mainSeriesRef?: React.MutableRefObject<ISeriesApi<'Candlestick'> | null>;
  /** Called whenever the pane-0 main series is created or replaced (e.g. chart-type switch). */
  onSeriesReady?: (chart: IChartApi, series: ISeriesApi<'Candlestick'>) => void;
}
```

- [ ] **Step 2: Destructure `onSeriesReady` in the component**

Find:

```ts
export default function ChartPane({ series, onCrosshairMove, height = 0, chartApiRef, mainSeriesRef }: Props) {
```

Replace with:

```ts
export default function ChartPane({ series, onCrosshairMove, height = 0, chartApiRef, mainSeriesRef, onSeriesReady }: Props) {
```

- [ ] **Step 3: Add `onSeriesReadyRef` for stable closure access**

Find:

```ts
const onCrosshairMoveRef = useRef(onCrosshairMove);
const prevPaneCountRef = useRef(0);
useEffect(() => { onCrosshairMoveRef.current = onCrosshairMove; }, [onCrosshairMove]);
```

Add below it:

```ts
const onSeriesReadyRef = useRef(onSeriesReady);
useEffect(() => { onSeriesReadyRef.current = onSeriesReady; }, [onSeriesReady]);
```

- [ ] **Step 4: Call `onSeriesReady` in all three main-series branches**

**Important:** All three replacements below are inside the `if (!s) { ... }` block in `ChartPane`'s series `forEach`. The `if (!s)` guard ensures this only fires on series *creation*, not on every `setData` call (which would fire `onSeriesReady` on every candle tick).

In the series update effect, find the Candlestick branch:

```ts
if (mainSeriesRef && (cfg.paneIndex ?? 0) === 0) mainSeriesRef.current = s as ISeriesApi<'Candlestick'>;
```

Replace with:

```ts
if ((cfg.paneIndex ?? 0) === 0) {
  if (mainSeriesRef) mainSeriesRef.current = s as ISeriesApi<'Candlestick'>;
  onSeriesReadyRef.current?.(chart, s as ISeriesApi<'Candlestick'>);
}
```

Find the Bar branch:

```ts
if (mainSeriesRef && (cfg.paneIndex ?? 0) === 0) mainSeriesRef.current = s as unknown as ISeriesApi<'Candlestick'>;
```

Replace with:

```ts
if ((cfg.paneIndex ?? 0) === 0) {
  if (mainSeriesRef) mainSeriesRef.current = s as unknown as ISeriesApi<'Candlestick'>;
  onSeriesReadyRef.current?.(chart, s as unknown as ISeriesApi<'Candlestick'>);
}
```

Find the Line branch (pane 0 only):

```ts
if (mainSeriesRef && (cfg.paneIndex ?? 0) === 0) {
  mainSeriesRef.current = s as unknown as ISeriesApi<'Candlestick'>;
}
```

Replace with:

```ts
if ((cfg.paneIndex ?? 0) === 0) {
  if (mainSeriesRef) mainSeriesRef.current = s as unknown as ISeriesApi<'Candlestick'>;
  onSeriesReadyRef.current?.(chart, s as unknown as ISeriesApi<'Candlestick'>);
}
```

- [ ] **Step 5: Typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/components/organisms/ChartPane/index.tsx
git commit -m "feat(chart): onSeriesReady callback for reactive series identity tracking"
```

---

## Task 5: useState for chart/series in ChartWorkspace — fix stale refs and PreviewPrimitive

**Why:** After Task 4, `ChartPane` can notify `ChartWorkspace` when the main series changes. This task wires that up: `ChartWorkspace` stores `chartApi` and `mainSeries` in React state, passes them as real props to `DrawingOverlays` and `ChartOverlays` (eliminating the stale `.current` anti-pattern), and keys the `PreviewPrimitive` effect on series identity so it correctly re-attaches when chart type changes.

**Files:**
- Modify: `frontend/components/organisms/ChartWorkspace/index.tsx`

---

- [ ] **Step 1: Add `useState` for chart and series**

In `ChartWorkspace/index.tsx`, find the existing state declarations block (starts around line 161). Add two new state variables immediately after `const [connState, setConnState] = useState...`:

```ts
const [chartApi, setChartApi] = useState<IChartApi | null>(null);
const [mainSeries, setMainSeries] = useState<ISeriesApi<'Candlestick'> | null>(null);
```

- [ ] **Step 2: Add `handleSeriesReady` callback**

Find where `wsRef`, `chartApiRef`, `mainSeriesRef`, etc. are declared (around line 173). Add immediately after those declarations:

```ts
const handleSeriesReady = useCallback(
  (chart: IChartApi, series: ISeriesApi<'Candlestick'>) => {
    chartApiRef.current = chart;
    mainSeriesRef.current = series;
    setChartApi(chart);
    setMainSeries(series);
  },
  // chartApiRef and mainSeriesRef are stable refs — no deps needed
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [],
);
```

- [ ] **Step 3: Replace `PreviewPrimitive` attachment effect**

Find the existing effect (around line 224):

```ts
useEffect(() => {
  const series = mainSeriesRef.current;
  if (!series) return;
  if (previewRef.current) return;
  const prim = new PreviewPrimitive();
  series.attachPrimitive(prim);
  previewRef.current = prim;
  return () => {
    try { series.detachPrimitive(prim); } catch { /* ignore */ }
    previewRef.current = null;
  };
// eslint-disable-next-line react-hooks/exhaustive-deps
}, [candles.length]);
```

Replace entirely with:

```ts
// Keyed on mainSeries identity — re-attaches correctly when chart type switches
// (Candlestick → Line/Bar creates a new series object and fires onSeriesReady again).
useEffect(() => {
  if (!mainSeries) return;
  const prim = new PreviewPrimitive();
  mainSeries.attachPrimitive(prim);
  previewRef.current = prim;
  return () => {
    try { mainSeries.detachPrimitive(prim); } catch { /* ignore */ }
    previewRef.current = null;
  };
}, [mainSeries]);
```

- [ ] **Step 4: Fix the markers+VP effect to use `mainSeries` state**

First, add a new one-liner `useEffect` **immediately before** the existing markers+VP effect. This resets the markers plugin ref only when the series instance changes — not on every candle tick. Do NOT place the reset inside the markers+VP effect body, because that effect also runs on `candles.length` change, which would leak a new plugin instance every tick.

```ts
// Reset markers plugin ref when series changes (chart-type switch).
// Separate from the markers+VP effect to avoid resetting on candle ticks.
useEffect(() => {
  markersApiRef.current = null;
}, [mainSeries]);
```

Then find the existing markers+VP effect (around line 379):

```ts
useEffect(() => {
  const series = mainSeriesRef.current;
  if (!series) return;
```

Replace those two lines with:

```ts
useEffect(() => {
  const series = mainSeries;
  if (!series) return;
```

Also update the deps array for this effect. Find:

```ts
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [candles.length, activeIndicators]);
```

Replace with:

```ts
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [candles.length, activeIndicators, mainSeries]);
```

- [ ] **Step 5: Fix drag effect to use state-based chart/series**

**Note:** Task 3 Step 7 already changed the drag effect deps to `[drawingTool, symbol, interval]`. This step adds `chartApi` and `mainSeries` on top of that. The final deps array in this step supersedes what Task 3 Step 7 produced.

In the drag effect (the `useEffect` beginning with `if (drawingTool !== 'cursor') return;`), find:

```ts
const chart = chartApiRef.current;
const series = mainSeriesRef.current;
if (!chart || !series) return;
```

Replace with:

```ts
const chart = chartApi;
const series = mainSeries;
if (!chart || !series) return;
```

Update the drag effect's deps array. Find (from Task 3):

```ts
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drawingTool, symbol, interval]);
```

Replace with:

```ts
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drawingTool, symbol, interval, chartApi, mainSeries]);
```

- [ ] **Step 6: Wire `onSeriesReady` into `ChartPane` in the JSX**

Find the `<ChartPane ... />` element in the return block:

```tsx
<ChartPane
  series={allSeries}
  onCrosshairMove={handleCrosshair}
  chartApiRef={chartApiRef}
  mainSeriesRef={mainSeriesRef}
/>
```

Replace with:

```tsx
<ChartPane
  series={allSeries}
  onCrosshairMove={handleCrosshair}
  chartApiRef={chartApiRef}
  mainSeriesRef={mainSeriesRef}
  onSeriesReady={handleSeriesReady}
/>
```

- [ ] **Step 7: Pass state values to `ChartOverlays` and `DrawingOverlays`**

Find:

```tsx
<ChartOverlays
  chart={chartApiRef.current}
  mainSeries={mainSeriesRef.current}
  signals={structureSignals}
  visibility={structureVisibility}
  visible={structureVisible}
/>
<DrawingOverlays
  chart={chartApiRef.current}
  mainSeries={mainSeriesRef.current}
  drawings={drawings.filter((d) => d.symbol === symbol && d.interval === interval)}
/>
```

Replace with:

```tsx
<ChartOverlays
  chart={chartApi}
  mainSeries={mainSeries}
  signals={structureSignals}
  visibility={structureVisibility}
  visible={structureVisible}
/>
<DrawingOverlays
  chart={chartApi}
  mainSeries={mainSeries}
  drawings={drawings.filter((d) => d.symbol === symbol && d.interval === interval)}
/>
```

- [ ] **Step 8: Also fix the click-to-draw effect**

The click-to-draw effect also reads from refs inside its callbacks. Find inside that effect:

```ts
const toX = (t: number): number | null => chartApiRef.current?.timeScale().timeToCoordinate(t as unknown as Time) ?? null;
const toY = (p: number): number | null => mainSeriesRef.current?.priceToCoordinate(p) ?? null;
```

These appear in two places (eraser hit test and text cursor hit test). Replace both occurrences with:

```ts
const toX = (t: number): number | null => chartApi?.timeScale().timeToCoordinate(t as unknown as Time) ?? null;
const toY = (p: number): number | null => mainSeries?.priceToCoordinate(p) ?? null;
```

Update the deps array of the click-to-draw effect. Find:

```ts
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drawingTool, symbol, interval]);
```

Replace with:

```ts
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drawingTool, symbol, interval, chartApi, mainSeries]);
```

- [ ] **Step 9: Typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: no errors.

- [ ] **Step 10: Run all tests**

```bash
cd frontend && npm run test
```

Expected: all existing tests pass.

- [ ] **Step 11: Commit**

```bash
git add frontend/components/organisms/ChartWorkspace/index.tsx
git commit -m "fix(chart): useState for chart/series — eliminate stale null refs to overlay components"
```

---

## Self-Review Checklist

**Spec coverage:**

| Bug from Code Review Gauntlet | Task that fixes it |
|-------------------------------|-------------------|
| DrawingOverlays full detach/re-attach on every drag tick | Task 2 |
| `onPointerUp` does not save final position | Task 3 |
| No `pointercancel` handler — chart locks on mobile | Task 3 |
| Stale `chartApiRef.current` / `mainSeriesRef.current` as props | Task 5 |
| `PreviewPrimitive` fails to re-attach after chart-type switch | Task 5 |
| `updateDrawing` in drag effect deps — mid-drag teardown risk | Task 3 |
| `wasDragRef` set on sub-pixel jitter — text-edit popover fails | Task 3 |
| `markersApiRef` stale after chart-type switch | Task 5 Step 4 |
| DrawingOverlays cleanup mutates shared Map entry | Task 2 Step 5 |
| diffDrawings O(n×m) inner loop | Task 2 Step 3 |

All 6 findings have coverage. ✓

**Placeholder scan:** No TBD / TODO / "similar to above" patterns. All code blocks are complete. ✓

**Type consistency:**
- `UpdatablePrimitive` defined in Task 1, used in Task 2. ✓
- `AttachedEntry` defined in `drawingOverlaysDiff.ts` (Task 2), imported in `DrawingOverlays` (Task 2). ✓
- `handleSeriesReady` signature matches `onSeriesReady?: (chart: IChartApi, series: ISeriesApi<'Candlestick'>) => void`. ✓
- `chartApi` / `mainSeries` state variables used consistently in Task 5. ✓
- `updateDrawingRef` defined in Task 3, used in the same task's effect. ✓
