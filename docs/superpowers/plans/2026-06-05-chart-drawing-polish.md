# Chart Drawing Polish + Axis Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `/chart` workspace's drawing tools usable and the panes synced — refactor the stacked sub-indicators into ONE multi-pane chart (shared time axis + crosshair), add live drawing feedback (origin marker + rubber-band preview for line & rectangle), add a text-box tool, add delete (eraser + clear-all), and add drag-to-move / edit-in-place.

**Architecture:** Phase A converts `ChartWorkspace`'s N separate `ChartPane` instances into a single lightweight-charts v5.1 chart with native panes (indicators on `paneIndex` 1+), so the time axis and crosshair sync for free. Phases B–E build an interactive drawing layer on top of the existing primitive system (`lib/chartPrimitives/*`, `DrawingOverlays`, `drawingStore`, backend `/chart/drawings`): a transient preview primitive driven by `subscribeCrosshairMove`, a `TextPrimitive` with a persisted `text` field, pure geometry hit-testing for an eraser + drag, and `updateDrawing` (re-POST upsert) for drag/edit persistence.

**Tech Stack:** Next.js 15 / React 19, TypeScript strict, Zustand v5, lightweight-charts v5.1 (native panes + primitive `hitTest`), CSS Modules, Jest; FastAPI + SQLAlchemy v2 + Alembic + pytest (backend).

---

## Conventions (read once)

- Frontend tests: `cd frontend && npm run test -- --testPathPattern=<name>` · Typecheck: `cd frontend && npm run typecheck` (must be clean before each commit) · Backend tests: `cd backend && python -m pytest tests/<file> -v`.
- Commit per task after tests+typecheck pass. End every commit body with: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Branch off `main` first: `git checkout -b feat/chart-drawing-polish`.
- **Verified lightweight-charts v5.1 APIs** (in `frontend/node_modules/lightweight-charts/dist/typings.d.ts`):
  - Multi-pane: `chart.addSeries(def, opts, paneIndex?)`, `chart.addPane()`, `chart.panes()`, `chart.removePane(i)`, `chart.paneSize(paneIndex?)`, `series.moveToPane(i)`. Panes in one chart share the time scale + crosshair automatically.
  - Primitive interactivity: `ISeriesPrimitive.hitTest?(x, y): PrimitiveHoveredItem | null`. We still implement our OWN pure geometry hit-test (more testable); the lib `hitTest` is optional.
  - Mouse: `chart.subscribeCrosshairMove(cb)` → `param.point {x,y}`, `param.time`. `series.coordinateToPrice(y)`, `chart.timeScale().coordinateToTime(x)` / `.timeToCoordinate(t)`, `series.priceToCoordinate(p)`.
  - Pan/zoom toggle during drag: `chart.applyOptions({ handleScroll: false, handleScale: false })` and back to `true`.
- **Existing files to reuse:** `frontend/lib/chartPrimitives/FibPrimitive.ts` (primitive pattern), `frontend/components/organisms/ChartPane/index.tsx` (chart host), `frontend/components/organisms/ChartWorkspace/index.tsx` (workspace), `frontend/components/organisms/DrawingOverlays/index.tsx`, `frontend/lib/drawingStore.ts`, `frontend/components/organisms/DrawingToolbar/index.tsx`, `frontend/types/overlays.ts`, backend `app/routers/chart_drawings.py` + `app/models/drawing.py`.

**Scope note:** This is two subsystems — **Phase A (multi-pane refactor)** and **Phases B–E (drawing layer)** — bundled per request. They are independent; A is foundational and lower-risk to land + review first. Each phase is shippable on its own.

---

## File Structure

**New**
- `frontend/lib/chart/hitTest.ts` — pure geometry: distance-to-segment, point-near-hline, point-in/near-rect, `hitTestDrawing()` returning `{hit, handle}`.
- `frontend/lib/chartPrimitives/PreviewPrimitive.ts` — transient origin-marker + rubber-band line/rect that follows the cursor.
- `frontend/lib/chartPrimitives/TextPrimitive.ts` — draws a text label with a background box at an anchor point.
- `frontend/components/molecules/TextInputPopover/index.tsx` (+ `.module.css`) — text entry/edit popover.

**Modified**
- `frontend/components/organisms/ChartPane/index.tsx` — accept multi-pane series config (`paneIndex`), render indicators as panes of one chart.
- `frontend/components/organisms/ChartWorkspace/index.tsx` — stop rendering separate sub-`ChartPane`s; feed sub-indicators as extra panes; wire preview, eraser, clear-all, drag, text.
- `frontend/components/organisms/DrawingToolbar/index.tsx` — add `text` + `eraser` tools; add a "Clear" button.
- `frontend/components/organisms/DrawingOverlays/index.tsx` — render `TextPrimitive` for `kind:'text'`.
- `frontend/lib/drawingStore.ts` — add `updateDrawing`; make `clearForSymbol` also delete from backend.
- `frontend/types/overlays.ts` — `DrawingKind` add `'text'`; `Drawing` add `text?: string`.
- `backend/app/models/drawing.py`, `backend/app/routers/chart_drawings.py` — add nullable `text` column + field.
- Alembic migration in `backend/migrations/versions/`.

---

# PHASE A — Single multi-pane chart (time-axis + crosshair sync)

### Task A1: ChartPane accepts a `paneIndex` per series

**Files:** Modify `frontend/components/organisms/ChartPane/index.tsx`

Today `SeriesConfig` has `{id,type,data,color,priceScaleId?}` and every series is added to pane 0. Add an optional `paneIndex` and pass it to `addSeries`.

- [ ] **Step 1: Read the file**, locate the `SeriesConfig` interface and the `chart.addSeries(...)` calls (the `if (cfg.type === ...)` block).
- [ ] **Step 2: Extend the interface** — add `paneIndex?: number;` to `SeriesConfig`.
- [ ] **Step 3: Pass paneIndex** to every `chart.addSeries(Def, opts, cfg.paneIndex ?? 0)` call (Candlestick/Bar/Line/Histogram). lightweight-charts auto-creates panes referenced by index.
- [ ] **Step 4:** `cd frontend && npm run typecheck` → clean. (No behavior change yet — all callers omit `paneIndex`, default 0.)
- [ ] **Step 5: Commit**

```bash
git add frontend/components/organisms/ChartPane/index.tsx
git commit -m "feat(chart): ChartPane supports per-series paneIndex

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task A2: Render sub-indicators as panes of the main chart

**Files:** Modify `frontend/components/organisms/ChartWorkspace/index.tsx`

Today: one `<ChartPane series={mainSeries} .../>` plus `{subPanes.map(... <ChartPane key={id} series={series} height={100}/>)}` — separate charts. Change to feed sub-indicator series into the SAME `mainSeries` array with increasing `paneIndex`, and stop rendering the extra `<ChartPane>`s.

- [ ] **Step 1:** Read the component. Find `buildSubSeries`, the `subPanes` memo, the `mainSeries` memo, and the JSX that renders the sub `<ChartPane>`s.
- [ ] **Step 2:** Replace `subPanes` with a flat `paneSeries` memo that assigns each active sub-indicator its own pane index (starting at 1) and tags every series it produces with that `paneIndex`:

```ts
const allSeries = useMemo(() => {
  const main = buildMainSeries(candles, activeIndicators, chartType, interval); // pane 0
  const subs: SeriesConfig[] = [];
  let pane = 1;
  for (const ind of activeIndicators.filter((i) => i.pane === 'sub')) {
    for (const s of buildSubSeries(candles, ind)) subs.push({ ...s, paneIndex: pane });
    pane += 1;
  }
  return [...main, ...subs];
}, [candles, activeIndicators, chartType, interval]);
```
- [ ] **Step 3:** Pass `allSeries` to the single `<ChartPane series={allSeries} ... />` and DELETE the `{subPanes.map(...)}` block (one chart now holds all panes).
- [ ] **Step 4:** In `ChartPane`, set pane heights after series are added so indicators aren't cramped: after the add/update loop, if `chart.panes().length > 1`, call `chart.panes()[0].setHeight(...)` proportionally (e.g. main 60%, each sub split the rest) using `containerRef.current.clientHeight`. Read the `IPaneApi` `setHeight` signature in the typings and apply. Keep it simple: main pane gets 60%, remaining panes share 40%.
- [ ] **Step 5:** `cd frontend && npm run typecheck` → clean. Manually verify on `/chart`: toggle RSI/Volume/MACD — they appear as stacked panes and **scroll/zoom together with the price pane**, crosshair lines up vertically.
- [ ] **Step 6: Commit**

```bash
git add frontend/components/organisms/ChartWorkspace/index.tsx frontend/components/organisms/ChartPane/index.tsx
git commit -m "feat(chart): indicators render as native panes of one chart (synced time axis + crosshair)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task A3: Verify overlays/drawings/markers still attach to the main series

**Files:** Modify `frontend/components/organisms/ChartWorkspace/index.tsx` (only if needed)

The markers/VP/overlay/drawing code attaches to `mainSeriesRef` (the pane-0 candlestick series). The refactor keeps that series in pane 0, so refs should still resolve.

- [ ] **Step 1:** Manually verify on `/chart`: enable an overlay (MA suite), a marker (Signal Markers), Volume Profile, and draw an hline — all still render on the price pane.
- [ ] **Step 2:** If `mainSeriesRef` is now set incorrectly (e.g., a sub-pane series overwrote it), guard the assignment in `ChartPane` so `mainSeriesRef` is only set for the `candles-*` series in pane 0 (it already keys on `candles-` per the prior fix; confirm). Fix only if broken.
- [ ] **Step 3:** `npm run test` (full) + `npm run typecheck` → green/clean.
- [ ] **Step 4: Commit** (only if a fix was needed)

```bash
git add frontend/components/organisms/ChartWorkspace/index.tsx
git commit -m "fix(chart): keep main-series ref on pane-0 candles after multi-pane refactor

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

# PHASE B — Drawing preview (origin marker + rubber-band)

### Task B1: PreviewPrimitive

**Files:** Create `frontend/lib/chartPrimitives/PreviewPrimitive.ts`

Draws (a) a cross/dot at the origin and (b) a ghost line or rectangle from origin to the current cursor. Both points are pixel coordinates supplied each frame (no time/price conversion needed inside — the workspace computes pixels from crosshair + origin).

- [ ] **Step 1: Implement** (mirror `FibPrimitive.ts` structure: renderer + pane view + primitive). The primitive holds a mutable `state` object and exposes `setState()` + `requestUpdate` via the stored `param`.

```ts
import type { ISeriesPrimitive, IPrimitivePaneView, IPrimitivePaneRenderer, SeriesAttachedParameter } from 'lightweight-charts';
import type { CanvasRenderingTarget2D } from 'fancy-canvas';

export interface PreviewState {
  kind: 'trendline' | 'rect' | null;
  origin: { x: number; y: number } | null;   // pixels
  cursor: { x: number; y: number } | null;   // pixels
}

class R implements IPrimitivePaneRenderer {
  constructor(private readonly s: PreviewState) {}
  draw(t: CanvasRenderingTarget2D): void {
    t.useMediaCoordinateSpace(({ context: ctx }) => {
      const { origin, cursor, kind } = this.s;
      if (!origin) return;
      // origin cross
      ctx.strokeStyle = 'rgba(255,255,255,0.9)'; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(origin.x - 6, origin.y); ctx.lineTo(origin.x + 6, origin.y);
      ctx.moveTo(origin.x, origin.y - 6); ctx.lineTo(origin.x, origin.y + 6); ctx.stroke();
      if (!cursor || !kind) return;
      ctx.setLineDash([4, 4]); ctx.strokeStyle = 'rgba(255,255,255,0.6)';
      if (kind === 'trendline') { ctx.beginPath(); ctx.moveTo(origin.x, origin.y); ctx.lineTo(cursor.x, cursor.y); ctx.stroke(); }
      else { const x = Math.min(origin.x, cursor.x), y = Math.min(origin.y, cursor.y); ctx.strokeRect(x, y, Math.abs(cursor.x - origin.x), Math.abs(cursor.y - origin.y)); }
      ctx.setLineDash([]);
    });
  }
}
class V implements IPrimitivePaneView {
  constructor(private readonly s: PreviewState) {}
  renderer(): IPrimitivePaneRenderer | null { return new R(this.s); }
}
export class PreviewPrimitive implements ISeriesPrimitive {
  private requestUpdate?: () => void;
  state: PreviewState = { kind: null, origin: null, cursor: null };
  attached(param: SeriesAttachedParameter): void { this.requestUpdate = param.requestUpdate; }
  setState(next: PreviewState): void { this.state = next; this.requestUpdate?.(); }
  paneViews(): readonly IPrimitivePaneView[] { return [new V(this.state)]; }
}
```
Adapt interface names/return types to match `FibPrimitive.ts` exactly (it compiles today).
- [ ] **Step 2:** `cd frontend && npm run typecheck` → clean.
- [ ] **Step 3: Commit**

```bash
git add frontend/lib/chartPrimitives/PreviewPrimitive.ts
git commit -m "feat(chart): preview primitive (origin cross + rubber-band line/rect)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task B2: Wire the preview into ChartWorkspace

**Files:** Modify `frontend/components/organisms/ChartWorkspace/index.tsx`

- [ ] **Step 1:** Attach one `PreviewPrimitive` to `mainSeriesRef` once (in a `useEffect` keyed on the series ref), store it in `previewRef`. Detach on cleanup.
- [ ] **Step 2:** In the existing click-to-draw effect, when a 2-point tool (`trendline`/`rect`) records the FIRST point, also set the preview origin in pixels: `previewRef.current?.setState({ kind: drawingTool, origin: { x: param.point.x, y: param.point.y }, cursor: null })`. On the second click (commit) and on tool change, clear it: `previewRef.current?.setState({ kind: null, origin: null, cursor: null })`.
- [ ] **Step 3:** Add a `subscribeCrosshairMove` handler (active only while a 2-point tool has a pending origin) that updates the cursor: `previewRef.current?.setState({ ...previewRef.current.state, cursor: param.point ? { x: param.point.x, y: param.point.y } : null })`. Unsubscribe in cleanup. Use `pendingPtsRef.current.length === 1` as the "origin pending" gate.
- [ ] **Step 4:** `npm run typecheck` → clean. Manually verify: pick Trendline → click once → a cross appears at the click and a dashed line follows the cursor → second click commits the real line and the preview clears. Repeat for Rectangle.
- [ ] **Step 5: Commit**

```bash
git add frontend/components/organisms/ChartWorkspace/index.tsx
git commit -m "feat(chart): live origin marker + rubber-band preview while drawing

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

# PHASE C — Text box

### Task C1: Backend — add nullable `text` column to drawings

**Files:** Modify `backend/app/models/drawing.py`, `backend/app/routers/chart_drawings.py`; Create Alembic migration in `backend/migrations/versions/`; Test `backend/tests/test_chart_drawings.py`

- [ ] **Step 1: Failing test** — extend `test_chart_drawings.py` with a case that POSTs a `kind:"text"` drawing including `"text":"hello"` and asserts the GET response echoes `text == "hello"`. Run → FAIL (field dropped).
- [ ] **Step 2: Implement** — add `text = Column(String, nullable=True)` to `DrawingModel`; add `text: str | None = None` to the Pydantic `DrawingIn` and to the GET serialization. Generate the migration: `cd backend && alembic revision --autogenerate -m "drawings text column"` → hand-trim to just `op.add_column('drawings', sa.Column('text', sa.String(), nullable=True))` (drop any unrelated autogen noise, matching the existing migration style).
- [ ] **Step 3:** Run the test → PASS. (For an already-created dev DB, the column is added by the migration; tests use `create_all` so they get it automatically.)
- [ ] **Step 4: Commit**

```bash
git add backend/app/models/drawing.py backend/app/routers/chart_drawings.py backend/migrations/versions/*text* backend/tests/test_chart_drawings.py
git commit -m "feat(api): drawings text column for text-box annotations

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task C2: Types + TextPrimitive

**Files:** Modify `frontend/types/overlays.ts`; Create `frontend/lib/chartPrimitives/TextPrimitive.ts`

- [ ] **Step 1:** In `overlays.ts`: add `'text'` to `DrawingKind`, and add `text?: string;` to the `Drawing` interface. Typecheck stays clean.
- [ ] **Step 2: Implement `TextPrimitive.ts`** (mirror `HorizontalLinePrimitive.ts`; one anchor point `points[0]`, draws `d.text` with a translucent background box):

```ts
import type { ISeriesPrimitive, IPrimitivePaneView, IPrimitivePaneRenderer, ISeriesApi, SeriesAttachedParameter, IChartApi, Time } from 'lightweight-charts';
import type { CanvasRenderingTarget2D } from 'fancy-canvas';
import type { Drawing } from '@/types/overlays';

class R implements IPrimitivePaneRenderer {
  constructor(private readonly d: Drawing, private readonly s: ISeriesApi<'Candlestick'>, private readonly c: IChartApi) {}
  draw(t: CanvasRenderingTarget2D): void {
    t.useMediaCoordinateSpace(({ context: ctx }) => {
      const p = this.d.points[0];
      const x = this.c.timeScale().timeToCoordinate(p.time as unknown as Time);
      const y = this.s.priceToCoordinate(p.price);
      if (x === null || y === null) return;
      const label = this.d.text ?? '';
      ctx.font = '12px sans-serif';
      const w = ctx.measureText(label).width;
      ctx.fillStyle = 'rgba(20,24,40,0.85)';
      ctx.fillRect(x, y - 16, w + 10, 18);
      ctx.strokeStyle = this.d.color; ctx.lineWidth = 1; ctx.strokeRect(x, y - 16, w + 10, 18);
      ctx.fillStyle = '#fff'; ctx.fillText(label, x + 5, y - 3);
    });
  }
}
class V implements IPrimitivePaneView {
  constructor(private readonly d: Drawing, private readonly s: ISeriesApi<'Candlestick'>, private readonly c: IChartApi) {}
  renderer(): IPrimitivePaneRenderer | null { return new R(this.d, this.s, this.c); }
}
export class TextPrimitive implements ISeriesPrimitive {
  private s: ISeriesApi<'Candlestick'> | null = null;
  private c: IChartApi | null = null;
  constructor(private readonly d: Drawing) {}
  attached(param: SeriesAttachedParameter): void { this.s = param.series as ISeriesApi<'Candlestick'>; this.c = param.chart; param.requestUpdate(); }
  paneViews(): readonly IPrimitivePaneView[] { return this.s && this.c ? [new V(this.d, this.s, this.c)] : []; }
}
```
Mirror how `TrendLinePrimitive.ts` obtained `param.chart` (it does the same).
- [ ] **Step 3:** `npm run typecheck` → clean.
- [ ] **Step 4: Commit**

```bash
git add frontend/types/overlays.ts frontend/lib/chartPrimitives/TextPrimitive.ts
git commit -m "feat(chart): text drawing type + TextPrimitive

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task C3: TextInputPopover + render text drawings

**Files:** Create `frontend/components/molecules/TextInputPopover/index.tsx` (+ `.module.css`); Modify `frontend/components/organisms/DrawingOverlays/index.tsx`

- [ ] **Step 1: Implement TextInputPopover** — a small centered popover with a text `<input>` (autofocus), Save/Cancel. Props: `{ initial?: string; onSave: (text: string) => void; onCancel: () => void }`. Mirror `ChartClickPopover`'s CSS approach (`.pop` absolute-centered). Save calls `onSave(value.trim())` only when non-empty.
- [ ] **Step 2:** In `DrawingOverlays`, add a branch mapping `kind:'text'` → `new TextPrimitive(drawing)` (alongside hline/trendline/rect). Import `TextPrimitive`.
- [ ] **Step 3:** `npm run typecheck` → clean.
- [ ] **Step 4: Commit**

```bash
git add frontend/components/molecules/TextInputPopover frontend/components/organisms/DrawingOverlays/index.tsx
git commit -m "feat(chart): text input popover + render text primitives

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task C4: Wire the Text tool

**Files:** Modify `frontend/components/organisms/DrawingToolbar/index.tsx`, `frontend/components/organisms/ChartWorkspace/index.tsx`

- [ ] **Step 1:** In `DrawingToolbar`, add `{ id: 'text', label: 'Text', icon: 'T' }` to `TOOLS` (the `'text'` member already exists in the union).
- [ ] **Step 2:** In the click effect, allow `'text'` in the guard, and add a branch: on click with the Text tool, capture `{ time, price }` and set a `textDraft` state `{ time, price, x, y }` (pixel coords for popover placement optional). Render `TextInputPopover` when `textDraft` is set; on Save, `addDrawing({ id: rid(), symbol, interval, kind: 'text', points: [{ time, price }], color: '#dddddd', width: 1, text, createdAt: new Date().toISOString() })` then clear `textDraft`.
- [ ] **Step 3:** `npm run typecheck` → clean. Manually verify: Text tool → click → type → Save → label with a box appears at that point, scrolls with the chart, and persists across reload.
- [ ] **Step 4: Commit**

```bash
git add frontend/components/organisms/DrawingToolbar/index.tsx frontend/components/organisms/ChartWorkspace/index.tsx
git commit -m "feat(chart): text-box tool — click to place a persisted text annotation

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

# PHASE D — Delete (eraser + clear-all)

### Task D1: Pure hit-test geometry

**Files:** Create `frontend/lib/chart/hitTest.ts`; Test `frontend/lib/chart/hitTest.test.ts`

- [ ] **Step 1: Failing test**:

```ts
import { distToSegment, hitTestDrawing } from './hitTest';
import type { Drawing } from '@/types/overlays';

describe('hit-test geometry', () => {
  it('distToSegment is ~0 on the segment, large off it', () => {
    expect(distToSegment(5, 0, 0, 0, 10, 0)).toBeCloseTo(0);
    expect(distToSegment(5, 20, 0, 0, 10, 0)).toBeCloseTo(20);
  });
  it('hitTestDrawing flags an hline when cursor is near its y', () => {
    const d = { id: 'a', symbol: 'X', interval: '1D', kind: 'hline', points: [{ time: 0, price: 100 }], color: '#fff', width: 1, createdAt: '' } as Drawing;
    // toX irrelevant for hline; toY maps price 100 -> 50px
    const hit = hitTestDrawing(d, 200, 52, () => 0, () => 50, 6);
    expect(hit.hit).toBe(true);
  });
});
```
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3: Implement** `frontend/lib/chart/hitTest.ts`:

```ts
import type { Drawing } from '@/types/overlays';

export function distToSegment(px: number, py: number, x1: number, y1: number, x2: number, y2: number): number {
  const dx = x2 - x1, dy = y2 - y1;
  const len2 = dx * dx + dy * dy;
  let t = len2 === 0 ? 0 : ((px - x1) * dx + (py - y1) * dy) / len2;
  t = Math.max(0, Math.min(1, t));
  const cx = x1 + t * dx, cy = y1 + t * dy;
  return Math.hypot(px - cx, py - cy);
}

export type Handle = 'p0' | 'p1' | 'whole' | null;
export interface HitResult { hit: boolean; handle: Handle; }

/** toX: time->pixel, toY: price->pixel. tol in pixels. */
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
  const p1 = d.points[1];
  const x0 = toX(p0.time), y0 = toY(p0.price), x1 = toX(p1?.time ?? p0.time), y1 = toY(p1?.price ?? p0.price);
  if (x0 == null || y0 == null || x1 == null || y1 == null) return { hit: false, handle: null };
  if (near(x0, y0)) return { hit: true, handle: 'p0' };
  if (near(x1, y1)) return { hit: true, handle: 'p1' };
  if (d.kind === 'trendline') return { hit: distToSegment(px, py, x0, y0, x1, y1) <= tol, handle: 'whole' };
  // rect: near any of the 4 borders
  const onBorder =
    distToSegment(px, py, x0, y0, x1, y0) <= tol || distToSegment(px, py, x1, y0, x1, y1) <= tol ||
    distToSegment(px, py, x1, y1, x0, y1) <= tol || distToSegment(px, py, x0, y1, x0, y0) <= tol;
  return { hit: onBorder, handle: 'whole' };
}
```
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5: Commit**

```bash
git add frontend/lib/chart/hitTest.ts frontend/lib/chart/hitTest.test.ts
git commit -m "feat(chart): pure geometry hit-testing for drawings

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task D2: drawingStore — persisted clear + update

**Files:** Modify `frontend/lib/drawingStore.ts`; Test `frontend/lib/drawingStore.test.ts`

- [ ] **Step 1: Failing tests** — (a) `clearForSymbol` calls the DELETE API for each matching id; (b) new `updateDrawing(id, patch)` updates local state and re-POSTs. Mock `global.fetch` (as the existing test does) and assert call counts/state.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3: Implement** — change `clearForSymbol` to capture matching ids, remove them locally, and call `deleteDrawingFromAPI(id)` for each. Add `updateDrawing: (id, patch) => { set(...merge...); const d = get().drawings.find(x=>x.id===id); if (d) pushDrawingToAPI(d); }` (reuse the existing POST upsert helper). Add `updateDrawing` to the state interface.
- [ ] **Step 4:** Run → PASS; `npm run typecheck` → clean.
- [ ] **Step 5: Commit**

```bash
git add frontend/lib/drawingStore.ts frontend/lib/drawingStore.test.ts
git commit -m "feat(chart): drawingStore updateDrawing + backend-persisted clearForSymbol

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task D3: Eraser tool + Clear button

**Files:** Modify `frontend/components/organisms/DrawingToolbar/index.tsx`, `frontend/components/organisms/ChartWorkspace/index.tsx`

- [ ] **Step 1:** In `DrawingToolbar`: add `'eraser'` to the `DrawingTool` union, add `{ id: 'eraser', label: 'Eraser', icon: '⌫' }` to `TOOLS`, and add a separate **Clear** button (not a tool) that calls an `onClear` prop. Add `onClear: () => void` to the toolbar Props.
- [ ] **Step 2:** In `ChartWorkspace`: pass `onClear={() => useDrawingStore.getState().clearForSymbol(symbol, interval)}`. Add `'eraser'` to the click-effect guard; in `onClick`, when the tool is `eraser`, run `hitTestDrawing` over the current `drawings` (filtered to symbol+interval) using `toX = (t)=>chart.timeScale().timeToCoordinate(t as Time)` and `toY = (p)=>series.priceToCoordinate(p)` and `tol=6`; delete the first hit via `useDrawingStore.getState().removeDrawing(hit.id)`.
- [ ] **Step 3:** `npm run typecheck` → clean. Manually verify: draw a few shapes → Eraser → click one → only that one disappears (and stays gone after reload). Clear button → all gone.
- [ ] **Step 4: Commit**

```bash
git add frontend/components/organisms/DrawingToolbar/index.tsx frontend/components/organisms/ChartWorkspace/index.tsx
git commit -m "feat(chart): eraser tool (click to delete) + clear-all button

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

# PHASE E — Drag-to-move + edit-in-place

### Task E1: Drag a drawing (pointer handling)

**Files:** Modify `frontend/components/organisms/ChartWorkspace/index.tsx`

Drag uses native pointer events on the chart container (lightweight-charts doesn't expose mousedown/up). While the `cursor` tool is active, pointerdown that hits a drawing starts a drag; pointermove updates its point(s); pointerup commits + persists. Chart pan/zoom is disabled during the drag.

- [ ] **Step 1:** Get the chart container element. `ChartPane` already owns `containerRef`; expose it via a new optional prop `containerRef?: React.MutableRefObject<HTMLDivElement|null>` set to the same div, OR query it from `chartApiRef.current.chartElement()` (check the typings for `chartElement()`; if present, prefer it). Use whichever the API provides.
- [ ] **Step 2:** Add a drag effect (active when `drawingTool === 'cursor'`):
  - `pointerdown`: compute `{x,y}` relative to the container; `toX/toY` as in D3; find the first drawing whose `hitTestDrawing(...).hit`; record `{ id, handle, startDrawing }`; if found, `chart.applyOptions({ handleScroll: false, handleScale: false })` and set a `dragRef`.
  - `pointermove`: if dragging, convert the new pixel `{x,y}` back to `{ time: chart.timeScale().coordinateToTime(x), price: series.coordinateToPrice(y) }`; build the updated `points` (move `p0`, `p1`, or translate `whole` by the delta) and call `useDrawingStore.getState().updateDrawing(id, { points })` (re-renders via DrawingOverlays + persists upsert).
  - `pointerup`: clear `dragRef`, re-enable `chart.applyOptions({ handleScroll: true, handleScale: true })`.
  Add/remove listeners in the effect; clean up on unmount/tool change.
- [ ] **Step 3:** `npm run typecheck` → clean. Manually verify: Cursor tool → grab a line endpoint and drag → it follows and persists; grab a rectangle border → it moves; chart doesn't pan while dragging.
- [ ] **Step 4: Commit**

```bash
git add frontend/components/organisms/ChartWorkspace/index.tsx
git commit -m "feat(chart): drag-to-move drawings (endpoints + whole) with persistence

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task E2: Edit text in place

**Files:** Modify `frontend/components/organisms/ChartWorkspace/index.tsx`

- [ ] **Step 1:** While the `cursor` (or `text`) tool is active, a click that hits a `kind:'text'` drawing opens `TextInputPopover` pre-filled with its current `text`; Save calls `updateDrawing(id, { text })`.
- [ ] **Step 2:** `npm run typecheck` → clean. Manually verify: click an existing text label → edit → Save → label updates and persists.
- [ ] **Step 3: Commit**

```bash
git add frontend/components/organisms/ChartWorkspace/index.tsx
git commit -m "feat(chart): edit a text box in place

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task E3: Final verification

- [ ] **Step 1:** `cd frontend && npm run typecheck && npm run test` → clean + all green.
- [ ] **Step 2:** `cd backend && python -m pytest tests/test_chart_drawings.py -v` → green.
- [ ] **Step 3:** Manual smoke on `/chart`: panes scroll/zoom in sync; draw line & rect with live preview; place + edit a text box; eraser deletes one; clear wipes all; drag moves endpoints and whole shapes; everything survives a reload (backend persistence). If the dev backend is running, restart it so the new `text` column migration is loaded (or run `alembic upgrade head`).
- [ ] **Step 4:** Finish via `superpowers:finishing-a-development-branch`.

---

## Self-review notes (coverage map)

- Axis sync (one multi-pane chart) → A1–A3. · Origin marker + rubber-band preview (line+rect) → B1–B2. · Text box (place/render/persist) → C1–C4. · Delete: eraser → D1+D3; clear-all → D2+D3. · Drag-to-move → E1; edit-in-place → E2.
- Persistence: text via new column (C1); drag/edit via `updateDrawing` upsert (D2); clear via persisted `clearForSymbol` (D2). POST is upsert-by-id, so no new PUT endpoint is needed.
- **Risks called out:** Phase A is a real refactor — land + review it before B–E. Drag (E1) depends on the chart container element (`chartElement()` or a shared `containerRef`) and on `coordinateToTime`/`coordinateToPrice` round-tripping; verify both against the installed typings during E1. Hit-test tolerances (6px) may need tuning.
- **Type consistency:** `hitTestDrawing(d, px, py, toX, toY, tol)` and its `HitResult {hit, handle}` are used identically in D3/E1. `PreviewState` (B1) is set via `setState` in B2. `updateDrawing(id, patch)` (D2) is used in E1/E2.
