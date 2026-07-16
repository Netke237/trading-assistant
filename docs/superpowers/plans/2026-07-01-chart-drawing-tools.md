# Chart Drawing Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add five new drawing tools to the Bamendjou chart (arrow, arrow mark up, arrow mark down, path, circle) plus a colour picker so users can change the stroke colour of any drawing.

**Architecture:** Each new tool follows the existing pattern: a `DrawingKind` enum value → a Canvas-primitive class in `lib/chartPrimitives/` → wired into `DrawingOverlays/makePrimitive` → a toolbar button in `DrawingToolbar`. Colour is held in local React state (`drawingColor`) in `ChartWorkspace` and passed as a prop to `DrawingToolbar`; all `addDrawing` calls receive the active colour instead of the hardcoded `'#dddddd'`. A `drawingColorRef` mirrors `drawingColor` so the effect cleanup can read the current colour without being in the dep array (avoids committing a partial path when only the colour changes). Path is an N-point tool; its interaction finalises on `Escape` (cancel) or on tool-switch (effect-cleanup commits ≥ 2 pts). Arrow/circle share the 2-click pattern; arrow_up/arrow_down are 1-click. `PreviewPrimitive` is extended to support `'arrow'` kind (mirrors trendline). Drag-to-move for all new kinds is handled in the existing drag handler by explicit case coverage for 1-point drawings and N-point paths.

**Tech Stack:** TypeScript, lightweight-charts v5 Canvas2D primitives (`useMediaCoordinateSpace`), Zustand, CSS Modules.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `frontend/types/overlays.ts` | Extend `DrawingKind` with 5 new values |
| Create | `frontend/lib/chartPrimitives/ArrowPrimitive.ts` | 2-point directed arrow with arrowhead |
| Create | `frontend/lib/chartPrimitives/ArrowUpPrimitive.ts` | 1-point filled upward triangle |
| Create | `frontend/lib/chartPrimitives/ArrowDownPrimitive.ts` | 1-point filled downward triangle |
| Create | `frontend/lib/chartPrimitives/CirclePrimitive.ts` | 2-point circle (centre + perimeter point) |
| Create | `frontend/lib/chartPrimitives/PathPrimitive.ts` | N-point polyline |
| Modify | `frontend/lib/chartPrimitives/PreviewPrimitive.ts` | Add `'arrow'` to supported preview kinds |
| Modify | `frontend/lib/chartPrimitives/primitives.test.ts` | Tests for 5 new primitives (imports added at top) |
| Modify | `frontend/lib/chart/hitTest.ts` | Hit-test cases for 5 new kinds |
| Modify | `frontend/lib/chart/hitTest.test.ts` | Tests for new hit-test branches |
| Modify | `frontend/components/organisms/DrawingOverlays/index.tsx` | Wire new primitives into `makePrimitive` |
| Modify | `frontend/components/organisms/DrawingToolbar/index.tsx` | Add 5 tool buttons + colour swatch |
| Modify | `frontend/components/organisms/DrawingToolbar/DrawingToolbar.module.css` | Colour swatch styles |
| Modify | `frontend/components/organisms/ChartWorkspace/index.tsx` | `drawingColor` state + ref, new tool interactions, drag-to-move fixes |
| Verify | `backend/app/` | Confirm or update backend schema for new `DrawingKind` values |

---

## Task 1: Extend DrawingKind

**Files:**
- Modify: `frontend/types/overlays.ts`

- [ ] **Step 1: Add new kind values**

Open `frontend/types/overlays.ts`. Replace line 45:
```ts
export type DrawingKind = 'trendline' | 'hline' | 'rect' | 'text';
```
with:
```ts
export type DrawingKind =
  | 'trendline' | 'hline' | 'rect' | 'text'
  | 'arrow'      // 2-point directed line with filled arrowhead at point[1]
  | 'arrow_up'   // 1-point upward triangle marker
  | 'arrow_down' // 1-point downward triangle marker
  | 'circle'     // 2-point: point[0]=centre, point[1]=perimeter
  | 'path';      // N-point polyline (≥2 points)
```

- [ ] **Step 2: Verify typecheck passes**

```bash
cd frontend && npm run typecheck
```
Expected: 0 errors (new union is additive — no existing code breaks yet).

- [ ] **Step 3: Commit**

```bash
git add frontend/types/overlays.ts
git commit -m "feat(chart): extend DrawingKind with arrow/arrow_up/arrow_down/circle/path"
```

---

## Task 2: ArrowPrimitive (2-point directed arrow)

**Files:**
- Create: `frontend/lib/chartPrimitives/ArrowPrimitive.ts`

- [ ] **Step 1: Write the file**

```ts
// frontend/lib/chartPrimitives/ArrowPrimitive.ts
import type {
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

const HEAD = 14; // arrowhead length in pixels

class ArrowRenderer implements IPrimitivePaneRenderer {
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

      if (x0 == null || y0 == null || x1 == null || y1 == null) return;

      const angle = Math.atan2(y1 - y0, x1 - x0);

      ctx.strokeStyle = this.d.color;
      ctx.lineWidth = this.d.width;
      ctx.beginPath();
      ctx.moveTo(x0, y0);
      ctx.lineTo(x1, y1);
      ctx.stroke();

      // Filled arrowhead at point[1]
      ctx.fillStyle = this.d.color;
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(
        x1 - HEAD * Math.cos(angle - Math.PI / 6),
        y1 - HEAD * Math.sin(angle - Math.PI / 6),
      );
      ctx.lineTo(
        x1 - HEAD * Math.cos(angle + Math.PI / 6),
        y1 - HEAD * Math.sin(angle + Math.PI / 6),
      );
      ctx.closePath();
      ctx.fill();
    });
  }
}

class ArrowPaneView implements IPrimitivePaneView {
  constructor(
    private readonly d: Drawing,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}
  renderer(): IPrimitivePaneRenderer | null {
    return new ArrowRenderer(this.d, this.chart, this.series);
  }
}

export class ArrowPrimitive implements UpdatablePrimitive {
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
    return [new ArrowPaneView(this.d, this.chart, this.series)];
  }
}
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && npm run typecheck
```
Expected: 0 errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/chartPrimitives/ArrowPrimitive.ts
git commit -m "feat(chart): add ArrowPrimitive (2-point directed arrow)"
```

---

## Task 3: ArrowUpPrimitive and ArrowDownPrimitive (1-point markers)

**Files:**
- Create: `frontend/lib/chartPrimitives/ArrowUpPrimitive.ts`
- Create: `frontend/lib/chartPrimitives/ArrowDownPrimitive.ts`

- [ ] **Step 1: Write ArrowUpPrimitive**

```ts
// frontend/lib/chartPrimitives/ArrowUpPrimitive.ts
import type {
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

const S = 10;     // half-base of triangle in pixels
const H = 16;     // height of triangle in pixels
const OFFSET = 6; // gap between price pixel and triangle base

class ArrowUpRenderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly d: Drawing,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}

  draw(target: CanvasRenderingTarget2D): void {
    target.useMediaCoordinateSpace(({ context: ctx }) => {
      const x = this.chart.timeScale().timeToCoordinate(this.d.points[0].time as unknown as Time);
      const y = this.series.priceToCoordinate(this.d.points[0].price);
      if (x == null || y == null) return;

      // Triangle points upward, rendered above the price point
      const tipY  = y - OFFSET - H;
      const baseY = y - OFFSET;
      ctx.fillStyle = this.d.color;
      ctx.beginPath();
      ctx.moveTo(x, tipY);
      ctx.lineTo(x - S, baseY);
      ctx.lineTo(x + S, baseY);
      ctx.closePath();
      ctx.fill();
    });
  }
}

class ArrowUpPaneView implements IPrimitivePaneView {
  constructor(
    private readonly d: Drawing,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}
  renderer(): IPrimitivePaneRenderer | null {
    return new ArrowUpRenderer(this.d, this.chart, this.series);
  }
}

export class ArrowUpPrimitive implements UpdatablePrimitive {
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
    return [new ArrowUpPaneView(this.d, this.chart, this.series)];
  }
}
```

- [ ] **Step 2: Write ArrowDownPrimitive**

```ts
// frontend/lib/chartPrimitives/ArrowDownPrimitive.ts
import type {
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

const S = 10;
const H = 16;
const OFFSET = 6;

class ArrowDownRenderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly d: Drawing,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}

  draw(target: CanvasRenderingTarget2D): void {
    target.useMediaCoordinateSpace(({ context: ctx }) => {
      const x = this.chart.timeScale().timeToCoordinate(this.d.points[0].time as unknown as Time);
      const y = this.series.priceToCoordinate(this.d.points[0].price);
      if (x == null || y == null) return;

      // Triangle points downward, rendered below the price point
      const tipY  = y + OFFSET + H;
      const baseY = y + OFFSET;
      ctx.fillStyle = this.d.color;
      ctx.beginPath();
      ctx.moveTo(x, tipY);
      ctx.lineTo(x - S, baseY);
      ctx.lineTo(x + S, baseY);
      ctx.closePath();
      ctx.fill();
    });
  }
}

class ArrowDownPaneView implements IPrimitivePaneView {
  constructor(
    private readonly d: Drawing,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}
  renderer(): IPrimitivePaneRenderer | null {
    return new ArrowDownRenderer(this.d, this.chart, this.series);
  }
}

export class ArrowDownPrimitive implements UpdatablePrimitive {
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
    return [new ArrowDownPaneView(this.d, this.chart, this.series)];
  }
}
```

- [ ] **Step 3: Typecheck**

```bash
cd frontend && npm run typecheck
```
Expected: 0 errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/chartPrimitives/ArrowUpPrimitive.ts frontend/lib/chartPrimitives/ArrowDownPrimitive.ts
git commit -m "feat(chart): add ArrowUpPrimitive and ArrowDownPrimitive"
```

---

## Task 4: CirclePrimitive (2-point: centre + perimeter)

**Files:**
- Create: `frontend/lib/chartPrimitives/CirclePrimitive.ts`

- [ ] **Step 1: Write the file**

```ts
// frontend/lib/chartPrimitives/CirclePrimitive.ts
import type {
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

class CircleRenderer implements IPrimitivePaneRenderer {
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

      if (x0 == null || y0 == null || x1 == null || y1 == null) return;

      const radius = Math.hypot(x1 - x0, y1 - y0);
      ctx.strokeStyle = this.d.color;
      ctx.lineWidth = this.d.width;
      ctx.beginPath();
      ctx.arc(x0, y0, radius, 0, 2 * Math.PI);
      ctx.stroke();
    });
  }
}

class CirclePaneView implements IPrimitivePaneView {
  constructor(
    private readonly d: Drawing,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}
  renderer(): IPrimitivePaneRenderer | null {
    return new CircleRenderer(this.d, this.chart, this.series);
  }
}

export class CirclePrimitive implements UpdatablePrimitive {
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
    return [new CirclePaneView(this.d, this.chart, this.series)];
  }
}
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && npm run typecheck
```
Expected: 0 errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/chartPrimitives/CirclePrimitive.ts
git commit -m "feat(chart): add CirclePrimitive (2-point circle)"
```

---

## Task 5: PathPrimitive (N-point polyline)

**Files:**
- Create: `frontend/lib/chartPrimitives/PathPrimitive.ts`

- [ ] **Step 1: Write the file**

```ts
// frontend/lib/chartPrimitives/PathPrimitive.ts
import type {
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

class PathRenderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly d: Drawing,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}

  draw(target: CanvasRenderingTarget2D): void {
    target.useMediaCoordinateSpace(({ context: ctx }) => {
      const toX = (t: number) => this.chart.timeScale().timeToCoordinate(t as unknown as Time);
      const toY = (p: number) => this.series.priceToCoordinate(p);

      const pts = this.d.points
        .map((pt) => ({ x: toX(pt.time), y: toY(pt.price) }))
        .filter((pt): pt is { x: number; y: number } => pt.x != null && pt.y != null);

      if (pts.length < 2) return;

      ctx.strokeStyle = this.d.color;
      ctx.lineWidth = this.d.width;
      ctx.beginPath();
      ctx.moveTo(pts[0].x, pts[0].y);
      for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y);
      ctx.stroke();
    });
  }
}

class PathPaneView implements IPrimitivePaneView {
  constructor(
    private readonly d: Drawing,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<'Candlestick'>,
  ) {}
  renderer(): IPrimitivePaneRenderer | null {
    return new PathRenderer(this.d, this.chart, this.series);
  }
}

export class PathPrimitive implements UpdatablePrimitive {
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
    return [new PathPaneView(this.d, this.chart, this.series)];
  }
}
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && npm run typecheck
```
Expected: 0 errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/chartPrimitives/PathPrimitive.ts
git commit -m "feat(chart): add PathPrimitive (N-point polyline)"
```

---

## Task 6: Extend PreviewPrimitive to support arrow and circle preview

**Files:**
- Modify: `frontend/lib/chartPrimitives/PreviewPrimitive.ts`

The existing `PreviewPrimitive` has:
```ts
export interface PreviewState {
  kind: 'trendline' | 'rect' | null;
  ...
}
```
The render logic at line 39 branches `if (kind === 'trendline')` → dashed line, else → dashed rect.
`arrow` and `circle` should both show the dashed-line rubber-band preview (same as trendline).
We extend the `kind` union and add `'arrow' | 'circle'` to the trendline render branch.

- [ ] **Step 1: Update PreviewPrimitive.ts**

Replace the file content:

```ts
import type {
  ISeriesPrimitive,
  IPrimitivePaneView,
  IPrimitivePaneRenderer,
  SeriesAttachedParameter,
} from 'lightweight-charts';
import type { CanvasRenderingTarget2D } from 'fancy-canvas';

export interface PreviewState {
  kind: 'trendline' | 'rect' | 'arrow' | 'circle' | null;
  origin: { x: number; y: number } | null; // pixels
  cursor: { x: number; y: number } | null; // pixels
}

class PreviewRenderer implements IPrimitivePaneRenderer {
  constructor(private readonly state: PreviewState) {}

  draw(target: CanvasRenderingTarget2D): void {
    target.useMediaCoordinateSpace(({ context: ctx }) => {
      const { origin, cursor, kind } = this.state;
      if (!origin) return;

      // origin cross
      ctx.strokeStyle = 'rgba(255,255,255,0.9)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(origin.x - 6, origin.y);
      ctx.lineTo(origin.x + 6, origin.y);
      ctx.moveTo(origin.x, origin.y - 6);
      ctx.lineTo(origin.x, origin.y + 6);
      ctx.stroke();

      if (!cursor || !kind) return;

      ctx.setLineDash([4, 4]);
      ctx.strokeStyle = 'rgba(255,255,255,0.6)';

      if (kind === 'trendline' || kind === 'arrow' || kind === 'circle') {
        ctx.beginPath();
        ctx.moveTo(origin.x, origin.y);
        ctx.lineTo(cursor.x, cursor.y);
        ctx.stroke();
      } else {
        // rect
        const x = Math.min(origin.x, cursor.x);
        const y = Math.min(origin.y, cursor.y);
        ctx.strokeRect(x, y, Math.abs(cursor.x - origin.x), Math.abs(cursor.y - origin.y));
      }

      ctx.setLineDash([]);
    });
  }
}

class PreviewPaneView implements IPrimitivePaneView {
  constructor(private readonly state: PreviewState) {}

  renderer(): IPrimitivePaneRenderer | null {
    return new PreviewRenderer(this.state);
  }
}

export class PreviewPrimitive implements ISeriesPrimitive {
  private requestUpdate?: () => void;

  state: PreviewState = { kind: null, origin: null, cursor: null };

  attached(param: SeriesAttachedParameter): void {
    this.requestUpdate = param.requestUpdate;
  }

  setState(next: PreviewState): void {
    this.state = next;
    this.requestUpdate?.();
  }

  paneViews(): readonly IPrimitivePaneView[] {
    if (!this.state.origin) return [];
    return [new PreviewPaneView(this.state)];
  }
}
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && npm run typecheck
```
Expected: 0 errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/chartPrimitives/PreviewPrimitive.ts
git commit -m "feat(chart): extend PreviewPrimitive kind union to include arrow and circle"
```

---

## Task 7: Tests for all 5 new primitives

**Files:**
- Modify: `frontend/lib/chartPrimitives/primitives.test.ts`

**Important:** Add the five new `import` lines at the **top** of the file alongside the existing imports — not appended at the end.

- [ ] **Step 1: Add imports at the top of the file**

In `frontend/lib/chartPrimitives/primitives.test.ts`, find the existing import block (lines 1–5):
```ts
import { HorizontalLinePrimitive } from './HorizontalLinePrimitive';
import { TrendLinePrimitive } from './TrendLinePrimitive';
import { RectanglePrimitive } from './RectanglePrimitive';
import { TextPrimitive } from './TextPrimitive';
import type { Drawing } from '@/types/overlays';
```
Replace with:
```ts
import { HorizontalLinePrimitive } from './HorizontalLinePrimitive';
import { TrendLinePrimitive } from './TrendLinePrimitive';
import { RectanglePrimitive } from './RectanglePrimitive';
import { TextPrimitive } from './TextPrimitive';
import { ArrowPrimitive } from './ArrowPrimitive';
import { ArrowUpPrimitive } from './ArrowUpPrimitive';
import { ArrowDownPrimitive } from './ArrowDownPrimitive';
import { CirclePrimitive } from './CirclePrimitive';
import { PathPrimitive } from './PathPrimitive';
import type { Drawing } from '@/types/overlays';
```

- [ ] **Step 2: Append test blocks at the end of the file**

Append after the last existing `describe` block:

```ts
const arrowDrawing = (): Drawing => ({
  id: 'a', symbol: 'SPY', interval: '1D' as const,
  kind: 'arrow',
  points: [{ time: 1000, price: 100 }, { time: 2000, price: 110 }],
  color: '#fff', width: 1, createdAt: '',
});

const onePointDrawing = (kind: Drawing['kind']): Drawing => ({
  id: 'b', symbol: 'SPY', interval: '1D' as const,
  kind,
  points: [{ time: 1000, price: 100 }],
  color: '#fff', width: 1, createdAt: '',
});

const pathDrawing = (): Drawing => ({
  id: 'c', symbol: 'SPY', interval: '1D' as const,
  kind: 'path',
  points: [{ time: 1000, price: 100 }, { time: 2000, price: 110 }, { time: 3000, price: 105 }],
  color: '#fff', width: 1, createdAt: '',
});

describe('ArrowPrimitive.update()', () => {
  it('calls requestUpdate after attach', () => {
    const req = jest.fn();
    const prim = new ArrowPrimitive(arrowDrawing());
    prim.attached(mockParam(req));
    req.mockClear();
    prim.update(arrowDrawing());
    expect(req).toHaveBeenCalledTimes(1);
  });
  it('does not throw before attach', () => {
    const prim = new ArrowPrimitive(arrowDrawing());
    expect(() => prim.update(arrowDrawing())).not.toThrow();
  });
});

describe('ArrowUpPrimitive.update()', () => {
  it('calls requestUpdate after attach', () => {
    const req = jest.fn();
    const prim = new ArrowUpPrimitive(onePointDrawing('arrow_up'));
    prim.attached(mockParam(req));
    req.mockClear();
    prim.update(onePointDrawing('arrow_up'));
    expect(req).toHaveBeenCalledTimes(1);
  });
  it('does not throw before attach', () => {
    const prim = new ArrowUpPrimitive(onePointDrawing('arrow_up'));
    expect(() => prim.update(onePointDrawing('arrow_up'))).not.toThrow();
  });
});

describe('ArrowDownPrimitive.update()', () => {
  it('calls requestUpdate after attach', () => {
    const req = jest.fn();
    const prim = new ArrowDownPrimitive(onePointDrawing('arrow_down'));
    prim.attached(mockParam(req));
    req.mockClear();
    prim.update(onePointDrawing('arrow_down'));
    expect(req).toHaveBeenCalledTimes(1);
  });
  it('does not throw before attach', () => {
    const prim = new ArrowDownPrimitive(onePointDrawing('arrow_down'));
    expect(() => prim.update(onePointDrawing('arrow_down'))).not.toThrow();
  });
});

describe('CirclePrimitive.update()', () => {
  it('calls requestUpdate after attach', () => {
    const req = jest.fn();
    const d: Drawing = { ...arrowDrawing(), kind: 'circle' };
    const prim = new CirclePrimitive(d);
    prim.attached(mockParam(req));
    req.mockClear();
    prim.update(d);
    expect(req).toHaveBeenCalledTimes(1);
  });
  it('does not throw before attach', () => {
    const d: Drawing = { ...arrowDrawing(), kind: 'circle' };
    const prim = new CirclePrimitive(d);
    expect(() => prim.update(d)).not.toThrow();
  });
});

describe('PathPrimitive.update()', () => {
  it('calls requestUpdate after attach', () => {
    const req = jest.fn();
    const prim = new PathPrimitive(pathDrawing());
    prim.attached(mockParam(req));
    req.mockClear();
    prim.update(pathDrawing());
    expect(req).toHaveBeenCalledTimes(1);
  });
  it('does not throw with single point before attach', () => {
    const d: Drawing = { ...pathDrawing(), points: [{ time: 1000, price: 100 }] };
    const prim = new PathPrimitive(d);
    expect(() => prim.update(d)).not.toThrow();
  });
});
```

- [ ] **Step 3: Run tests**

```bash
cd frontend && npm run test -- --testPathPattern=primitives.test
```
Expected: All tests pass (PASS).

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/chartPrimitives/primitives.test.ts
git commit -m "test(chart): cover 5 new drawing primitives"
```

---

## Task 8: Extend hit-test for new drawing kinds

**Files:**
- Modify: `frontend/lib/chart/hitTest.ts`
- Modify: `frontend/lib/chart/hitTest.test.ts`

The hit-test for `arrow_up`/`arrow_down` uses a directional bounding rect (not a radial distance) to match the visual area of the rendered triangle above/below the price point.

- [ ] **Step 1: Write failing hit-test tests first**

In `frontend/lib/chart/hitTest.test.ts`, the existing imports already bring in `hitTestDrawing`, `distToSegment`, and `Drawing`. Append the following **describe blocks only** at the end of the file (do not add new imports):

```ts
describe('hitTestDrawing — arrow', () => {
  const d: Drawing = {
    id: 'x', symbol: 'S', interval: '1D' as const,
    kind: 'arrow',
    points: [{ time: 0, price: 0 }, { time: 100, price: 0 }],
    color: '#fff', width: 1, createdAt: '',
  };
  const toX = (t: number) => t as number;
  const toY = (p: number) => p as number;
  it('hits near midpoint of line', () => {
    expect(hitTestDrawing(d, 50, 3, toX, toY, 8).hit).toBe(true);
  });
  it('misses far from line', () => {
    expect(hitTestDrawing(d, 50, 30, toX, toY, 8).hit).toBe(false);
  });
  it('handle p0 near first point', () => {
    expect(hitTestDrawing(d, 2, 2, toX, toY, 8).handle).toBe('p0');
  });
  it('handle p1 near second point', () => {
    expect(hitTestDrawing(d, 98, 2, toX, toY, 8).handle).toBe('p1');
  });
});

describe('hitTestDrawing — arrow_up', () => {
  // Rendered: triangle tip at y-22, base at y-6, half-width 10px, above price pixel
  const d: Drawing = {
    id: 'x', symbol: 'S', interval: '1D' as const,
    kind: 'arrow_up',
    points: [{ time: 50, price: 50 }],
    color: '#fff', width: 1, createdAt: '',
  };
  const toX = (t: number) => t as number;
  const toY = (p: number) => p as number;
  it('hits inside rendered triangle area (above price)', () => {
    // price pixel y=50, OFFSET=6, H=16 → tipY=28, baseY=44; y=38 is inside [28..44]
    expect(hitTestDrawing(d, 50, 38, toX, toY, 8).hit).toBe(true);
  });
  it('misses below price point (wrong direction)', () => {
    expect(hitTestDrawing(d, 50, 65, toX, toY, 8).hit).toBe(false);
  });
  it('misses far to the side', () => {
    expect(hitTestDrawing(d, 100, 38, toX, toY, 8).hit).toBe(false);
  });
});

describe('hitTestDrawing — arrow_down', () => {
  // Rendered: triangle tip at y+22, base at y+6, half-width 10px, below price pixel
  const d: Drawing = {
    id: 'x', symbol: 'S', interval: '1D' as const,
    kind: 'arrow_down',
    points: [{ time: 50, price: 50 }],
    color: '#fff', width: 1, createdAt: '',
  };
  const toX = (t: number) => t as number;
  const toY = (p: number) => p as number;
  it('hits inside rendered triangle area (below price)', () => {
    expect(hitTestDrawing(d, 50, 62, toX, toY, 8).hit).toBe(true);
  });
  it('misses above price point (wrong direction)', () => {
    expect(hitTestDrawing(d, 50, 35, toX, toY, 8).hit).toBe(false);
  });
  it('misses far to the side', () => {
    expect(hitTestDrawing(d, 100, 62, toX, toY, 8).hit).toBe(false);
  });
});

describe('hitTestDrawing — circle', () => {
  // centre=(100,100), perimeter=(100,150) → radius=50
  const d: Drawing = {
    id: 'x', symbol: 'S', interval: '1D' as const,
    kind: 'circle',
    points: [{ time: 100, price: 100 }, { time: 100, price: 150 }],
    color: '#fff', width: 1, createdAt: '',
  };
  const toX = (t: number) => t as number;
  const toY = (p: number) => p as number;
  it('hits near circumference (right side, tol=8)', () => {
    // dist from (100,100) to (150,100) = 50 = radius → |50-50|=0 ≤ 8
    expect(hitTestDrawing(d, 150, 100, toX, toY, 8).hit).toBe(true);
  });
  it('misses at centre (well inside)', () => {
    // dist=0, |0-50|=50 > 8
    expect(hitTestDrawing(d, 100, 100, toX, toY, 8).hit).toBe(false);
  });
  it('misses well outside', () => {
    // dist=100, |100-50|=50 > 8
    expect(hitTestDrawing(d, 200, 100, toX, toY, 8).hit).toBe(false);
  });
});

describe('hitTestDrawing — path', () => {
  const d: Drawing = {
    id: 'x', symbol: 'S', interval: '1D' as const,
    kind: 'path',
    points: [{ time: 0, price: 0 }, { time: 50, price: 50 }, { time: 100, price: 0 }],
    color: '#fff', width: 1, createdAt: '',
  };
  const toX = (t: number) => t as number;
  const toY = (p: number) => p as number;
  it('hits near first segment', () => {
    expect(hitTestDrawing(d, 25, 28, toX, toY, 8).hit).toBe(true);
  });
  it('hits near second segment', () => {
    expect(hitTestDrawing(d, 75, 22, toX, toY, 8).hit).toBe(true);
  });
  it('misses far from all segments', () => {
    expect(hitTestDrawing(d, 50, 80, toX, toY, 8).hit).toBe(false);
  });
  it('returns false for single-point path', () => {
    const single: Drawing = { ...d, points: [{ time: 0, price: 0 }] };
    expect(hitTestDrawing(single, 0, 0, toX, toY, 8).hit).toBe(false);
  });
});
```

- [ ] **Step 2: Run tests — confirm failures**

```bash
cd frontend && npm run test -- --testPathPattern=hitTest.test
```
Expected: FAIL on all new describe blocks.

- [ ] **Step 3: Extend hitTestDrawing**

In `frontend/lib/chart/hitTest.ts`, replace the entire `hitTestDrawing` function with the following. The `arrow_up`/`arrow_down` hit logic uses a directional bounding rect matching the rendered triangle area (OFFSET=6, H=16, S=10, so the bounding rect is `[x-S, y-OFFSET-H] → [x+S, y-OFFSET]` for up and `[x+OFFSET, x+OFFSET+H]` for down):

```ts
// Matches render constants in ArrowUpPrimitive / ArrowDownPrimitive
const ARROW_S = 10;
const ARROW_H = 16;
const ARROW_OFFSET = 6;

export function hitTestDrawing(
  d: Drawing, px: number, py: number,
  toX: (time: number) => number | null, toY: (price: number) => number | null, tol: number,
): HitResult {
  const near = (x: number | null, y: number | null) => x != null && y != null && Math.hypot(px - x, py - y) <= tol;
  const p0 = d.points[0];

  if (d.kind === 'hline') {
    const y = toY(p0.price);
    return { hit: y != null && Math.abs(py - y) <= tol, handle: 'whole' };
  }
  if (d.kind === 'text') {
    const x = toX(p0.time), y = toY(p0.price);
    return { hit: x != null && y != null && px >= x - 4 && px <= x + 120 && py >= y - 18 && py <= y + 4, handle: 'whole' };
  }

  // 1-point directional markers — bounding rect matches rendered triangle area
  if (d.kind === 'arrow_up') {
    const x = toX(p0.time), y = toY(p0.price);
    if (x == null || y == null) return { hit: false, handle: null };
    const tipY  = y - ARROW_OFFSET - ARROW_H;
    const baseY = y - ARROW_OFFSET;
    const hit = px >= x - ARROW_S - tol && px <= x + ARROW_S + tol && py >= tipY - tol && py <= baseY + tol;
    return { hit, handle: 'whole' };
  }
  if (d.kind === 'arrow_down') {
    const x = toX(p0.time), y = toY(p0.price);
    if (x == null || y == null) return { hit: false, handle: null };
    const tipY  = y + ARROW_OFFSET + ARROW_H;
    const baseY = y + ARROW_OFFSET;
    const hit = px >= x - ARROW_S - tol && px <= x + ARROW_S + tol && py >= baseY - tol && py <= tipY + tol;
    return { hit, handle: 'whole' };
  }

  // path: hit if near any segment
  if (d.kind === 'path') {
    if (d.points.length < 2) return { hit: false, handle: null };
    for (let i = 0; i < d.points.length - 1; i++) {
      const ax = toX(d.points[i].time), ay = toY(d.points[i].price);
      const bx = toX(d.points[i + 1].time), by = toY(d.points[i + 1].price);
      if (ax == null || ay == null || bx == null || by == null) continue;
      if (distToSegment(px, py, ax, ay, bx, by) <= tol) return { hit: true, handle: 'whole' };
    }
    return { hit: false, handle: null };
  }

  // circle: hit if distance from centre ≈ radius (within tol)
  if (d.kind === 'circle') {
    const x0 = toX(p0.time), y0 = toY(p0.price);
    const x1 = toX(d.points[1].time), y1 = toY(d.points[1].price);
    if (x0 == null || y0 == null || x1 == null || y1 == null) return { hit: false, handle: null };
    const radius = Math.hypot(x1 - x0, y1 - y0);
    const dist = Math.hypot(px - x0, py - y0);
    return { hit: Math.abs(dist - radius) <= tol, handle: 'whole' };
  }

  // 2-point kinds: arrow / trendline / rect
  const p1 = d.points[1];
  const x0 = toX(p0.time), y0 = toY(p0.price), x1 = toX(p1?.time ?? p0.time), y1 = toY(p1?.price ?? p0.price);
  if (x0 == null || y0 == null || x1 == null || y1 == null) return { hit: false, handle: null };
  if (near(x0, y0)) return { hit: true, handle: 'p0' };
  if (near(x1, y1)) return { hit: true, handle: 'p1' };
  if (d.kind === 'trendline' || d.kind === 'arrow') {
    return { hit: distToSegment(px, py, x0, y0, x1, y1) <= tol, handle: 'whole' };
  }
  // rect: near any of the 4 borders
  const onBorder =
    distToSegment(px, py, x0, y0, x1, y0) <= tol || distToSegment(px, py, x1, y0, x1, y1) <= tol ||
    distToSegment(px, py, x1, y1, x0, y1) <= tol || distToSegment(px, py, x0, y1, x0, y0) <= tol;
  return { hit: onBorder, handle: 'whole' };
}
```

- [ ] **Step 4: Update the arrow_up/arrow_down hit test assertions to match the directional bounding rect**

The tests written in Step 1 use y=38 for arrow_up (point at y=50 → baseY=44, tipY=28 → 38 is inside the rect ✓) and y=62 for arrow_down (point at y=50 → baseY=56, tipY=72 → 62 is inside ✓). These are consistent with the implementation. No test changes needed.

- [ ] **Step 5: Run tests — confirm pass**

```bash
cd frontend && npm run test -- --testPathPattern=hitTest.test
```
Expected: All tests pass (PASS).

- [ ] **Step 6: Typecheck**

```bash
cd frontend && npm run typecheck
```
Expected: 0 errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/lib/chart/hitTest.ts frontend/lib/chart/hitTest.test.ts
git commit -m "feat(chart): extend hit-test for arrow/arrow_up/arrow_down/circle/path"
```

---

## Task 9: Wire new primitives into DrawingOverlays

**Files:**
- Modify: `frontend/components/organisms/DrawingOverlays/index.tsx`

- [ ] **Step 1: Add new imports and switch cases**

Replace the content of `frontend/components/organisms/DrawingOverlays/index.tsx`:

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
import { ArrowPrimitive } from '@/lib/chartPrimitives/ArrowPrimitive';
import { ArrowUpPrimitive } from '@/lib/chartPrimitives/ArrowUpPrimitive';
import { ArrowDownPrimitive } from '@/lib/chartPrimitives/ArrowDownPrimitive';
import { CirclePrimitive } from '@/lib/chartPrimitives/CirclePrimitive';
import { PathPrimitive } from '@/lib/chartPrimitives/PathPrimitive';

interface Props {
  chart: IChartApi | null;
  mainSeries: ISeriesApi<'Candlestick'> | null;
  drawings: Drawing[];
}

function makePrimitive(drawing: Drawing): UpdatablePrimitive | null {
  switch (drawing.kind) {
    case 'hline':      return new HorizontalLinePrimitive(drawing);
    case 'trendline':  return new TrendLinePrimitive(drawing);
    case 'rect':       return new RectanglePrimitive(drawing);
    case 'text':       return new TextPrimitive(drawing);
    case 'arrow':      return new ArrowPrimitive(drawing);
    case 'arrow_up':   return new ArrowUpPrimitive(drawing);
    case 'arrow_down': return new ArrowDownPrimitive(drawing);
    case 'circle':     return new CirclePrimitive(drawing);
    case 'path':       return new PathPrimitive(drawing);
    default:           return null;
  }
}

export default function DrawingOverlays({ chart, mainSeries, drawings }: Props) {
  const attachedRef = useRef<Map<string, AttachedEntry>>(new Map());

  useEffect(() => {
    if (!chart || !mainSeries) return;
    const attached = attachedRef.current;
    const { toAdd, toRemove, toUpdate } = diffDrawings(attached, drawings);

    for (const entry of toRemove) {
      try {
        mainSeries.detachPrimitive(entry.primitive);
      } catch (e) {
        if (process.env.NODE_ENV !== 'production') throw e;
      }
      attached.delete(entry.drawing.id);
    }

    for (const { entry, drawing } of toUpdate) {
      entry.primitive.update(drawing);
      attached.set(drawing.id, { primitive: entry.primitive, drawing });
    }

    for (const drawing of toAdd) {
      const primitive = makePrimitive(drawing);
      if (!primitive) continue;
      mainSeries.attachPrimitive(primitive);
      attached.set(drawing.id, { primitive, drawing });
    }
  }, [chart, mainSeries, drawings]);

  useEffect(() => {
    return () => {
      const attached = attachedRef.current;
      for (const entry of attached.values()) {
        try {
          mainSeries?.detachPrimitive(entry.primitive);
        } catch (e) {
          if (process.env.NODE_ENV !== 'production') throw e;
        }
      }
      attached.clear();
    };
  }, [chart, mainSeries]);

  return null;
}
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && npm run typecheck
```
Expected: 0 errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/components/organisms/DrawingOverlays/index.tsx
git commit -m "feat(chart): wire arrow/arrow_up/arrow_down/circle/path into DrawingOverlays"
```

---

## Task 10: Backend schema verification

**Files:**
- Verify: `backend/app/` (routers, models, or any Pydantic schema that validates `kind`)

The `drawingStore` pushes drawings to `POST /chart/drawings`. If the backend validates the `kind` field against a fixed enum or DB check constraint, new kind values will be rejected silently or with a 422.

- [ ] **Step 1: Check for DrawingKind validation in the backend**

Search for the drawing kind validation:
```bash
cd backend && grep -r "DrawingKind\|drawing_kind\|trendline\|hline" app/ --include="*.py" -l
```

- [ ] **Step 2: Update the backend schema if needed**

If a Pydantic model uses `Literal['trendline', 'hline', 'rect', 'text']` or similar, update it to include the five new values:
```python
from typing import Literal
DrawingKind = Literal['trendline', 'hline', 'rect', 'text', 'arrow', 'arrow_up', 'arrow_down', 'circle', 'path']
```

If the DB has a check constraint (look in Alembic migrations for `CHECK (kind IN (...))`), add a new migration:
```bash
cd backend && alembic revision --autogenerate -m "add_new_drawing_kinds"
```
Then manually edit the generated migration to add the new values to the check constraint.

- [ ] **Step 3: Run backend tests**

```bash
cd backend && pytest
```
Expected: All pass.

- [ ] **Step 4: Commit any backend changes**

```bash
git add backend/
git commit -m "feat(backend): support new drawing kinds in schema"
```

---

## Task 11: DrawingToolbar and ChartWorkspace — colour picker + new interactions

**Note:** This task bundles the toolbar changes and all ChartWorkspace changes into one atomic commit so the build is never left in a broken state between them.

**Files:**
- Modify: `frontend/components/organisms/DrawingToolbar/index.tsx`
- Modify: `frontend/components/organisms/DrawingToolbar/DrawingToolbar.module.css`
- Modify: `frontend/components/organisms/ChartWorkspace/index.tsx`

- [ ] **Step 1: Update DrawingToolbar**

Replace `frontend/components/organisms/DrawingToolbar/index.tsx`:

```tsx
'use client';
import styles from './DrawingToolbar.module.css';

export type DrawingTool =
  | 'cursor' | 'trendline' | 'hline' | 'rect'
  | 'arrow' | 'arrow_up' | 'arrow_down'
  | 'circle' | 'path'
  | 'alert' | 'buy'
  | 'fib' | 'text' | 'measure' | 'zoom'
  | 'eraser';

interface Props {
  active: DrawingTool;
  onChange: (t: DrawingTool) => void;
  onClear: () => void;
  color: string;
  onColorChange: (c: string) => void;
}

const TOOLS: { id: DrawingTool; label: string; icon: string }[] = [
  { id: 'cursor',     label: 'Cursor',           icon: '✛' },
  { id: 'trendline',  label: 'Trendline',        icon: '╱' },
  { id: 'hline',      label: 'Horizontal line',  icon: '─' },
  { id: 'rect',       label: 'Rectangle',        icon: '□' },
  { id: 'arrow',      label: 'Arrow',            icon: '→' },
  { id: 'arrow_up',   label: 'Arrow mark up',    icon: '▲' },
  { id: 'arrow_down', label: 'Arrow mark down',  icon: '▼' },
  { id: 'circle',     label: 'Circle',           icon: '○' },
  { id: 'path',       label: 'Path',             icon: '∿' },
  { id: 'text',       label: 'Text',             icon: 'T' },
  { id: 'alert',      label: 'Set alert',        icon: '🔔' },
  { id: 'buy',        label: 'Paper buy',        icon: '＄' },
  { id: 'eraser',     label: 'Eraser',           icon: '⌫' },
];

export default function DrawingToolbar({ active, onChange, onClear, color, onColorChange }: Props) {
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
      <div className={styles.divider} />
      <label className={styles.colorSwatch} title="Stroke colour" style={{ backgroundColor: color }}>
        <input
          type="color"
          value={color}
          onChange={(e) => onColorChange(e.target.value)}
          className={styles.colorInput}
        />
      </label>
      <button className={styles.tool} title="Clear all drawings" onClick={onClear}>
        ✕
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Update DrawingToolbar CSS**

Replace `frontend/components/organisms/DrawingToolbar/DrawingToolbar.module.css`:

```css
.toolbar {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 6px 0;
  width: 36px;
  background: var(--bg-surface);
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
  background: var(--bg-surface-2);
  color: var(--text-primary);
}

.tool.active {
  background: var(--bg-surface-2);
  color: var(--pass);
}

.divider {
  width: 20px;
  height: 1px;
  background: var(--border-subtle);
  margin: 4px 0;
}

.colorSwatch {
  width: 20px;
  height: 20px;
  border-radius: 3px;
  border: 1px solid var(--border-subtle);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 2px 0;
  overflow: hidden;
}

.colorInput {
  width: 0;
  height: 0;
  padding: 0;
  border: none;
  opacity: 0;
  position: absolute;
}
```

- [ ] **Step 3: Update ChartWorkspace — add drawingColor state and ref**

In `frontend/components/organisms/ChartWorkspace/index.tsx`, find the block of `useState` declarations. After `const [drawingTool, setDrawingTool] = useState<DrawingTool>('cursor');`, add:

```tsx
const [drawingColor, setDrawingColor] = useState('#dddddd');
// Mirror drawingColor in a ref so the effect cleanup can commit a path with the
// current colour without needing drawingColor in the effect dep array.
const drawingColorRef = useRef('#dddddd');
useEffect(() => { drawingColorRef.current = drawingColor; }, [drawingColor]);
```

- [ ] **Step 4: Pass colour props to DrawingToolbar**

Find:
```tsx
<DrawingToolbar active={drawingTool} onChange={setDrawingTool} onClear={() => { clearForSymbol(symbol, interval); }} />
```
Replace with:
```tsx
<DrawingToolbar
  active={drawingTool}
  onChange={setDrawingTool}
  onClear={() => { clearForSymbol(symbol, interval); }}
  color={drawingColor}
  onColorChange={setDrawingColor}
/>
```

- [ ] **Step 5: Extend the click-to-draw useEffect — tool guard**

Find the tool guard at the top of the click-to-draw `useEffect`:
```tsx
if (drawingTool !== 'cursor' && drawingTool !== 'trendline' && drawingTool !== 'hline' && drawingTool !== 'rect' && drawingTool !== 'alert' && drawingTool !== 'buy' && drawingTool !== 'text' && drawingTool !== 'eraser') {
```
Replace with:
```tsx
if (drawingTool !== 'cursor' && drawingTool !== 'trendline' && drawingTool !== 'hline' && drawingTool !== 'rect' && drawingTool !== 'arrow' && drawingTool !== 'arrow_up' && drawingTool !== 'arrow_down' && drawingTool !== 'circle' && drawingTool !== 'path' && drawingTool !== 'alert' && drawingTool !== 'buy' && drawingTool !== 'text' && drawingTool !== 'eraser') {
```

- [ ] **Step 6: Add 1-point tools in the onClick handler**

In the `onClick` handler, before the `hline` block, add:
```tsx
if (drawingTool === 'arrow_up') {
  addDrawing({ id: rid(), symbol, interval, kind: 'arrow_up', points: [{ time, price }], color: drawingColorRef.current, width: 1, createdAt: new Date().toISOString() });
  return;
}
if (drawingTool === 'arrow_down') {
  addDrawing({ id: rid(), symbol, interval, kind: 'arrow_down', points: [{ time, price }], color: drawingColorRef.current, width: 1, createdAt: new Date().toISOString() });
  return;
}
```

- [ ] **Step 7: Update hline addDrawing to use drawingColorRef**

Find:
```tsx
addDrawing({ id: rid(), symbol, interval, kind: 'hline', points: [{ time, price }], color: '#dddddd', width: 1, createdAt: new Date().toISOString() });
```
Replace with:
```tsx
addDrawing({ id: rid(), symbol, interval, kind: 'hline', points: [{ time, price }], color: drawingColorRef.current, width: 1, createdAt: new Date().toISOString() });
```

- [ ] **Step 8: Extend the 2-point guard and commit block for arrow / circle / path**

Replace:
```tsx
if ((drawingTool === 'trendline' || drawingTool === 'rect') && param.time == null) return;
```
with:
```tsx
if ((drawingTool === 'trendline' || drawingTool === 'rect' || drawingTool === 'arrow' || drawingTool === 'circle' || drawingTool === 'path') && param.time == null) return;
```

Replace the pending-points first-click preview setState call:
```tsx
previewRef.current?.setState({
  kind: drawingTool as 'trendline' | 'rect',
  origin: { x: param.point.x, y: param.point.y },
  cursor: null,
});
```
with:
```tsx
previewRef.current?.setState({
  kind: (drawingTool === 'arrow' || drawingTool === 'trendline' || drawingTool === 'circle')
    ? drawingTool as 'trendline' | 'arrow' | 'circle'
    : drawingTool === 'path'
    ? 'trendline'   // path uses trendline-style preview; origin updates on each click below
    : 'rect',
  origin: { x: param.point.x, y: param.point.y },
  cursor: null,
});
```

Replace the 2-point commit block (pendingPtsRef.current.length === 2):
```tsx
} else if (pendingPtsRef.current.length === 2) {
  // Second point (commit) — clear preview then finalise drawing
  previewRef.current?.setState({ kind: null, origin: null, cursor: null });
  addDrawing({ id: rid(), symbol, interval, kind: drawingTool, points: [...pendingPtsRef.current], color: '#dddddd', width: 1, createdAt: new Date().toISOString() });
  pendingPtsRef.current = [];
}
```
with:
```tsx
} else if (pendingPtsRef.current.length === 2) {
  if (drawingTool === 'path') {
    // path: 2nd vertex placed — update origin preview to last placed point so the
    // rubber-band feedback shows the segment from the last vertex to the cursor.
    previewRef.current?.setState({
      kind: 'trendline',
      origin: { x: param.point.x, y: param.point.y },
      cursor: null,
    });
  } else {
    // trendline / rect / arrow / circle: 2-point drawing is now complete
    previewRef.current?.setState({ kind: null, origin: null, cursor: null });
    // Narrow DrawingTool → DrawingKind for the kinds handled by this branch
    const kind = drawingTool as 'trendline' | 'rect' | 'arrow' | 'circle';
    addDrawing({ id: rid(), symbol, interval, kind, points: [...pendingPtsRef.current], color: drawingColorRef.current, width: 1, createdAt: new Date().toISOString() });
    pendingPtsRef.current = [];
  }
} else if (pendingPtsRef.current.length > 2 && drawingTool === 'path') {
  // path: N-th vertex (N > 2) — update preview origin to the newly placed point
  previewRef.current?.setState({
    kind: 'trendline',
    origin: { x: param.point.x, y: param.point.y },
    cursor: null,
  });
}
```

- [ ] **Step 9: Add Escape-to-cancel and commit-on-tool-switch for path**

In the same click-to-draw `useEffect`, after `chart.subscribeClick(onClick)`:

```tsx
const onKeyDown = (e: KeyboardEvent) => {
  if (e.key === 'Escape' && drawingTool === 'path') {
    pendingPtsRef.current = [];
    previewRef.current?.setState({ kind: null, origin: null, cursor: null });
  }
};
window.addEventListener('keydown', onKeyDown);
```

In the cleanup return function, before clearing pendingPtsRef:
```tsx
return () => {
  chart.unsubscribeClick(onClick);
  chart.unsubscribeCrosshairMove(onCrosshair);
  window.removeEventListener('keydown', onKeyDown);
  // Commit any in-progress path when switching away from the path tool.
  // Read colour from ref (not closed-over state) so a colour-only change
  // does not accidentally commit a partial path.
  if (drawingTool === 'path' && pendingPtsRef.current.length >= 2) {
    addDrawing({
      id: rid(), symbol, interval, kind: 'path',
      points: [...pendingPtsRef.current],
      color: drawingColorRef.current,
      width: 1,
      createdAt: new Date().toISOString(),
    });
  }
  pendingPtsRef.current = [];
};
```

- [ ] **Step 10: Update text addDrawing to use drawingColorRef**

Find:
```tsx
addDrawing({ id: rid(), symbol, interval, kind: 'text', points: [{ time: textDraft.time, price: textDraft.price }], color: '#dddddd', width: 1, text, createdAt: new Date().toISOString() });
```
Replace with:
```tsx
addDrawing({ id: rid(), symbol, interval, kind: 'text', points: [{ time: textDraft.time, price: textDraft.price }], color: drawingColorRef.current, width: 1, text, createdAt: new Date().toISOString() });
```

- [ ] **Step 11: Fix drag-to-move for 1-point drawings (arrow_up / arrow_down)**

The existing `whole`-body drag code (the final `startDrawing.points.map(...)` block) already iterates all points and applies both a time offset and a price offset. This covers `arrow_up`, `arrow_down`, and `path` without any change.

The only special case that needed its own branch was `hline`, which should move price-only (no time axis change). That branch already exists.

**Verify:** Read the existing `calcUpdatedPoints` function in `ChartWorkspace/index.tsx` and confirm the final `return startDrawing.points.map(...)` block applies both `snapTime` (time-axis offset) and `p.price + dp` (price offset). If it does, no code change is required for `arrow_up`, `arrow_down`, or `path` drag-to-move.

- [ ] **Step 12: Confirm drawingOverlaysDiff tests still pass**

No changes are needed to `frontend/lib/chart/drawingOverlaysDiff.ts` or its test — `diffDrawings` is kind-agnostic and operates on `Drawing.id` identity. Run to confirm:

```bash
cd frontend && npm run test -- --testPathPattern=drawingOverlaysDiff
```
Expected: All existing tests pass (PASS).

- [ ] **Step 13: Do NOT add drawingColor to the click-to-draw useEffect dep array**

The effect reads colour via `drawingColorRef.current` inside callbacks, so it does not need `drawingColor` in its deps. The existing dep array `[drawingTool, symbol, interval, chartApi, mainSeries]` is correct. Do not add `drawingColor` — doing so would cause a re-run (and path-commit in cleanup) every time the colour is changed while drawing.

- [ ] **Step 14: Typecheck — must be clean before committing**

```bash
cd frontend && npm run typecheck
```
Expected: 0 errors.

- [ ] **Step 15: Run all frontend tests**

```bash
cd frontend && npm run test
```
Expected: All PASS.

- [ ] **Step 16: Commit**

```bash
git add frontend/components/organisms/DrawingToolbar/index.tsx frontend/components/organisms/DrawingToolbar/DrawingToolbar.module.css frontend/components/organisms/ChartWorkspace/index.tsx
git commit -m "feat(chart): colour picker + arrow/arrow_up/arrow_down/circle/path interactions"
```

---

## Final verification

- [ ] **Run full typecheck**

```bash
cd frontend && npm run typecheck
```
Expected: 0 errors.

- [ ] **Run all frontend tests**

```bash
cd frontend && npm run test
```
Expected: All PASS.

- [ ] **Manual smoke test**

Start dev server:
```bash
cd frontend && npm run dev
```

Navigate to `/chart`. Verify:
1. Toolbar shows the 5 new buttons (→ ▲ ▼ ○ ∿) plus colour swatch
2. Click colour swatch → native colour picker opens; pick red → swatch turns red
3. Select `arrow` → click two points → directed arrow appears in red with arrowhead at second point
4. Select `arrow_up` → click once → upward red triangle appears above click point
5. Select `arrow_down` → click once → downward red triangle appears below click point
6. Select `circle` → click two points (centre then perimeter) → circle appears in red
7. Select `path` → click 4 points → switch to `cursor` → polyline with 4 vertices commits and renders
8. Select `path` → click 2 points → press `Escape` → no path is committed
9. Change colour mid-session (while cursor tool is active) → next new drawing uses the new colour; existing drawings keep their original colour
10. Switch to `eraser` → click on any new drawing → it is removed
11. Select `cursor` → drag arrow_up or arrow_down → marker moves in both time and price axes
12. Select `cursor` → drag a path → all N vertices move together

---

## Self-Review

**Spec coverage:**
- Arrow mark up ✓ (`arrow_up` tool + `ArrowUpPrimitive`)
- Arrow mark down ✓ (`arrow_down` tool + `ArrowDownPrimitive`)
- Arrow ✓ (`arrow` tool + `ArrowPrimitive`)
- Path ✓ (`path` tool + `PathPrimitive`)
- Circle ✓ (`circle` tool + `CirclePrimitive`)
- Change colour of **new** drawings ✓ (`drawingColor` state + `drawingColorRef` + colour swatch)
- **Known limitation:** Recolouring an *already-committed* drawing is not in scope. The colour picker sets the colour for the next drawing placed; existing drawings keep their stored colour. A future task would add a "select + recolour" interaction (click drawing in cursor mode → show colour swatch for that drawing → call `updateDrawing(id, { color })`). This is out of scope here.

**Type consistency:**
- `DrawingKind` extended in `overlays.ts` ✓
- `DrawingTool` extended in `DrawingToolbar/index.tsx` ✓
- `DrawingTool → DrawingKind` narrowing explicit in Task 11 Step 8 (`as 'trendline' | 'rect' | 'arrow' | 'circle'`) ✓
- `drawingColorRef` used in all effect closures to avoid stale colour and spurious path commits ✓
- `PreviewPrimitive` extended for `'arrow'` kind in Task 6 ✓
- `color`/`onColorChange` props added and wired in same task (Task 11) to keep build clean ✓
- Backend schema update task added (Task 10) ✓
- Directional hit-test for `arrow_up`/`arrow_down` uses bounding rect matching rendered triangle ✓
- Drag-to-move for 1-point markers and N-point paths handled explicitly ✓

**No placeholders:** All steps contain complete code or explicit read-before-proceed instructions. ✓
