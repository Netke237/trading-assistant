# Five High-Severity Audit Findings — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 5 High-severity findings from the 2026-08-15 codebase audit (`bamendjou-audit.html`): a `<select>`-hijacking keyboard shortcut, hardcoded dark-only chart colors, no-op Options-mode fundamentals sliders, an event-loop-blocking order-placement path, and unreachable "reversal" watch-alert logic.

**Architecture:** Five independent, surgical fixes across frontend (StepNavBar, ChartPane, RunScanButton, api.ts) and backend (schemas, fundamentals_gate service, broker router, strategy_watch_evaluator). No shared dependencies between tasks — each is a self-contained vertical slice with its own tests. Order is easiest/lowest-risk first.

**Tech Stack:** Next.js 15 / TypeScript / Jest + Testing Library (frontend); FastAPI / Pydantic v2 / pytest + pytest-asyncio (backend).

---

## Background: what's broken (from the audit)

1. **Arrow-key nav hijacks `<select>`** — `StepNavBar`'s global ←/→ listener guards `INPUT`/`TEXTAREA`/contenteditable but not `SELECT`. Focusing Step 2's horizon `<select>` and pressing arrow keys silently navigates the wizard instead of cycling dropdown options.
2. **`ChartPane` hardcodes dark colors** — the standalone `/chart` workspace (via `ChartWorkspace`) never reads theme tokens, unlike the sibling `CandlestickChart`. Light theme never repaints it.
3. **Options-mode "fundamentals caution/reject above" sliders are no-ops** — the Step-3 sliders write into `scanOverrides`, which for Options scans rides in the generic `overrides` dict. The Options `ScanRequest` schema has no field for these values and the Options scan pipeline never patches them into the fundamentals gate (unlike the Stocks pipeline, which does).
4. **Order placement blocks the event loop** — `POST /broker/stock-order` and `/broker/option-order` call `router_.execute(...)` directly on the async handler's stack. For IBKR/Tradier/Alpaca this runs a synchronous `httpx.post` (up to 8-10s timeout) with no `to_thread` hop, freezing the whole app for the round trip.
5. **The "reversal" watch alert can never fire** — `strategy_watch_evaluator.py`'s armed-phase reversal check compares `signal.direction != state.get("direction")`, but `signal` is always computed with the watch's own fixed direction, so `signal.direction` can never disagree with the armed state's direction (which was set from that same signal). The branch is dead code.

---

## Task 1: Fix arrow-key navigation hijacking `<select>` elements

**Files:**
- Modify: `frontend/components/organisms/StepNavBar/index.tsx:56-57`
- Test: `frontend/components/organisms/StepNavBar/__tests__/StepNavBar.test.tsx`

- [ ] **Step 1: Write the failing test**

Add to the existing `describe` block in `frontend/components/organisms/StepNavBar/__tests__/StepNavBar.test.tsx` (after the last test, before the closing `});`):

```tsx
  it('ArrowRight key does not advance when a <select> element has focus', () => {
    useScanStore.setState({ combinedRegime: 'PASS' } as any);
    render(
      <>
        <StepNavBar />
        <select data-testid="horizon-select">
          <option value="swing">Swing</option>
          <option value="position">Position</option>
        </select>
      </>,
    );
    const select = screen.getByTestId('horizon-select');
    select.focus();
    fireEvent.keyDown(select, { key: 'ArrowRight' });
    expect(mockPush).not.toHaveBeenCalled();
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- --testPathPattern=StepNavBar`
Expected: FAIL — `mockPush` was called with `/screener/step-2-universe` because the keydown handler doesn't guard `SELECT` elements, so `e.target` (the `<select>`) falls through to the `ArrowRight` branch.

- [ ] **Step 3: Add the `SELECT` guard**

In `frontend/components/organisms/StepNavBar/index.tsx`, change line 57:

```tsx
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
```

to:

```tsx
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- --testPathPattern=StepNavBar`
Expected: PASS — all StepNavBar tests green, including the new one.

- [ ] **Step 5: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean, no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/components/organisms/StepNavBar/index.tsx frontend/components/organisms/StepNavBar/__tests__/StepNavBar.test.tsx
git commit -m "fix(step-nav): don't hijack arrow keys inside a focused <select>"
```

---

## Task 2: Fix `ChartPane` hardcoded dark-theme colors

`ChartPane` (backs the standalone `/chart` workspace — its only consumer is `ChartWorkspace`; `InlineChartPanel` renders `CandlestickChart` directly and is untouched by this task) hardcodes hex colors in `createChart()` and in each series' `upColor`/`downColor`/default `color`. The sibling `CandlestickChart` component reads CSS custom properties via `getComputedStyle` and falls back to a hardcoded default only if the token is empty — this task ports that token-reading pattern into `ChartPane`.

It deliberately does **not** port `CandlestickChart`'s full teardown-and-recreate-the-whole-chart response to a live theme toggle. `ChartWorkspace` hangs substantial state off the specific chart/series instance across a session — volume-profile/preview overlays, drag-to-move pointer handlers bound to `chartApi.chartElement()`, and a regime-overlay series added directly via `chart.addSeries` outside `ChartPane`'s own `series` prop — and none of that is exercised by a test. Recreating the chart on every theme toggle would put all of it at risk for no reason. Instead: colors are read fresh at chart-creation time (fixes the core bug — a `ChartPane` mounted under either theme now renders with that theme's real palette, the common case since theme is normally set once in Settings before a user ever opens `/chart`), and a live theme *toggle* while the chart is already mounted is handled by calling `chart.applyOptions(...)` and each tracked series' `.applyOptions(...)` — lightweight-charts' own live-restyle API — never `remove()`/`createChart()` again. The chart instance, and everything `ChartWorkspace` has wired to it, is never torn down.

**Files:**
- Modify: `frontend/components/organisms/ChartPane/index.tsx`
- Modify: `frontend/__mocks__/lightweight-charts.js` (currently an empty stub — needs a minimal fake so ChartPane can be rendered in tests)
- Modify: `frontend/jest.setup.ts` (needs a `ResizeObserver` polyfill — jsdom doesn't implement it and `ChartPane` calls it unconditionally on mount)
- Test: `frontend/components/organisms/ChartPane/__tests__/ChartPane.test.tsx` (new)

- [ ] **Step 1: Extend the `lightweight-charts` mock**

Replace the entire contents of `frontend/__mocks__/lightweight-charts.js`:

```js
// Minimal fake of the lightweight-charts v5 surface ChartPane/CandlestickChart use.
// createChart is a jest.fn so tests can inspect the options it was called with
// (mock.calls) and the fake chart instance it returned (mock.results).

const CandlestickSeries = { __brand: 'CandlestickSeries' };
const BarSeries = { __brand: 'BarSeries' };
const LineSeries = { __brand: 'LineSeries' };
const HistogramSeries = { __brand: 'HistogramSeries' };

function makeSeriesApi(seriesOptions) {
  return {
    __options: seriesOptions,
    setData: jest.fn(),
    applyOptions: jest.fn(),
  };
}

function makePaneApi() {
  return {
    setHeight: jest.fn(),
    getSeries: jest.fn(() => []),
  };
}

const createChart = jest.fn((_container, options) => {
  const panes = [makePaneApi()];
  return {
    __options: options,
    addSeries: jest.fn((_type, seriesOptions) => makeSeriesApi(seriesOptions)),
    removeSeries: jest.fn(),
    removePane: jest.fn(),
    panes: jest.fn(() => panes),
    subscribeCrosshairMove: jest.fn(),
    applyOptions: jest.fn(),
    remove: jest.fn(),
    timeScale: jest.fn(() => ({ fitContent: jest.fn() })),
  };
});

module.exports = { createChart, CandlestickSeries, BarSeries, LineSeries, HistogramSeries };
```

- [ ] **Step 2: Add a `ResizeObserver` polyfill to the Jest setup**

`ChartPane`'s mount effect calls `new ResizeObserver(...)` unconditionally. The installed `jest-environment-jsdom` does not implement `ResizeObserver` at all — every test that renders `ChartPane` (or any other component that uses it, e.g. `CandlestickChart`, `PnlChart`, `EarningsChart`, none of which currently have test files either) will throw `TypeError: ResizeObserver is not a constructor` before any assertion runs. Add a minimal stub to the shared Jest setup file so this is fixed once, for every current and future test that needs it — not scoped to just this one test file.

Add to `frontend/jest.setup.ts`:

```ts
import '@testing-library/jest-dom';

// jsdom does not implement ResizeObserver. Components that watch their
// container size (ChartPane, CandlestickChart, PnlChart, EarningsChart) call
// `new ResizeObserver(...)` unconditionally on mount, which throws under
// jsdom without this stub.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
global.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
```

- [ ] **Step 3: Write the failing test**

Create `frontend/components/organisms/ChartPane/__tests__/ChartPane.test.tsx`:

```tsx
import { render } from '@testing-library/react';
import { createChart } from 'lightweight-charts';
import ChartPane from '@/components/organisms/ChartPane';
import { useThemeStore } from '@/lib/theme';

const TOKENS: Record<string, string> = {
  '--bg-surface': '#FFFFFF',
  '--border-subtle': '#DDE1F0',
  '--text-secondary': '#5A6070',
  '--pass': '#1A9188',
  '--reject': '#D32F2F',
};

function mockComputedStyle(tokens: Record<string, string>) {
  jest.spyOn(window, 'getComputedStyle').mockReturnValue({
    getPropertyValue: (name: string) => tokens[name] ?? '',
  } as unknown as CSSStyleDeclaration);
}

describe('ChartPane — theme token colors', () => {
  beforeEach(() => {
    (createChart as jest.Mock).mockClear();
  });

  it('reads chart background/grid/text colors from CSS tokens instead of hardcoded hex', () => {
    mockComputedStyle(TOKENS);
    render(<ChartPane series={[]} />);

    const [, options] = (createChart as jest.Mock).mock.calls[0];
    expect(options.layout.background.color).toBe('#FFFFFF');
    expect(options.layout.textColor).toBe('#5A6070');
    expect(options.grid.vertLines.color).toBe('#DDE1F0');
    expect(options.grid.horzLines.color).toBe('#DDE1F0');
  });

  it('applies pass/reject tokens to a candlestick series instead of hardcoded green/red', () => {
    mockComputedStyle(TOKENS);
    render(
      <ChartPane
        series={[{ id: 'main', type: 'Candlestick', data: [] }]}
      />,
    );

    const chart = (createChart as jest.Mock).mock.results[0].value;
    const [, seriesOptions] = chart.addSeries.mock.calls[0];
    expect(seriesOptions.upColor).toBe('#1A9188');
    expect(seriesOptions.downColor).toBe('#D32F2F');
  });

  it('falls back to the dark default palette when a token is unset', () => {
    mockComputedStyle({});
    render(<ChartPane series={[]} />);

    const [, options] = (createChart as jest.Mock).mock.calls[0];
    expect(options.layout.background.color).toBe('#0b0b14');
  });

  it('live-restyles the existing chart on a theme toggle instead of recreating it', () => {
    mockComputedStyle(TOKENS);
    useThemeStore.setState({ theme: 'dark' });
    const { rerender } = render(
      <ChartPane series={[{ id: 'main', type: 'Candlestick', data: [] }]} />,
    );
    const chart = (createChart as jest.Mock).mock.results[0].value;
    const candleSeries = chart.addSeries.mock.results[0].value;

    mockComputedStyle({ ...TOKENS, '--pass': '#00FF00', '--reject': '#FF0000' });
    useThemeStore.setState({ theme: 'light' });
    rerender(<ChartPane series={[{ id: 'main', type: 'Candlestick', data: [] }]} />);

    // No teardown/recreate — ChartWorkspace's overlays/drawings/drag-handlers
    // stay bound to this exact chart+series instance across a theme toggle.
    expect(createChart).toHaveBeenCalledTimes(1);
    expect(chart.remove).not.toHaveBeenCalled();
    expect(chart.applyOptions).toHaveBeenCalledWith(
      expect.objectContaining({
        layout: expect.objectContaining({ background: { color: TOKENS['--bg-surface'] } }),
      }),
    );
    expect(candleSeries.applyOptions).toHaveBeenCalledWith(
      expect.objectContaining({ upColor: '#00FF00', downColor: '#FF0000' }),
    );
  });
});
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd frontend && npm run test -- --testPathPattern=ChartPane`
Expected: FAIL (now on the actual assertions, not a `ResizeObserver` crash) — `options.layout.background.color` is `'#0b0b14'` (hardcoded) even when the light-theme tokens are mocked; `seriesOptions.upColor` is `'#4caf50'` instead of the token value; the live-restyle test fails because `ChartPane` doesn't subscribe to `useThemeStore` at all yet, so `chart.applyOptions` is never called on a toggle.

- [ ] **Step 5: Rewrite `ChartPane` to read tokens and react to theme changes**

Replace the full contents of `frontend/components/organisms/ChartPane/index.tsx`:

```tsx
'use client';
import { useEffect, useRef, useCallback } from 'react';
import {
  createChart,
  CandlestickSeries,
  BarSeries,
  LineSeries,
  HistogramSeries,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from 'lightweight-charts';
import type { Candle, Point } from '@/lib/indicators';
import { useThemeStore } from '@/lib/theme';
import styles from './ChartPane.module.css';

export interface SeriesConfig {
  id: string;
  type: 'Candlestick' | 'Bar' | 'Line' | 'Histogram';
  data: Candle[] | Point[];
  color?: string;
  priceScaleId?: string;
  paneIndex?: number;
}

interface Props {
  series: SeriesConfig[];
  onCrosshairMove?: (time: string | null, values: Record<string, number>) => void;
  height?: number;   // 0 or omitted = fill container height
  chartApiRef?: React.MutableRefObject<IChartApi | null>;
  mainSeriesRef?: React.MutableRefObject<ISeriesApi<'Candlestick'> | null>;
  /** Called whenever the pane-0 main series is created or replaced (e.g. chart-type switch). */
  onSeriesReady?: (chart: IChartApi, series: ISeriesApi<'Candlestick'>) => void;
}

/** Read a CSS custom property off :root. Mirrors CandlestickChart's helper. */
function token(name: string): string {
  if (typeof window === 'undefined') return '';
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

interface ThemeColors {
  bg: string;
  gridSoft: string;
  textDim: string;
  passColor: string;
  rejColor: string;
}

function readThemeColors(): ThemeColors {
  return {
    bg:        token('--bg-surface')     || '#0b0b14',
    gridSoft:  token('--border-subtle')  || '#1e1e35',
    textDim:   token('--text-secondary') || '#888',
    passColor: token('--pass')           || '#4caf50',
    rejColor:  token('--reject')         || '#e05050',
  };
}

export default function ChartPane({ series, onCrosshairMove, height = 0, chartApiRef, mainSeriesRef, onSeriesReady }: Props) {
  const theme = useThemeStore((s) => s.theme);
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const colorsRef = useRef<ThemeColors>(readThemeColors());
  const seriesMap = useRef<Map<string, ISeriesApi<'Candlestick' | 'Bar' | 'Line' | 'Histogram'>>>(new Map());
  const onCrosshairMoveRef = useRef(onCrosshairMove);
  const prevPaneCountRef = useRef(0);
  const isFirstThemeRunRef = useRef(true);
  const seriesRef = useRef(series);
  useEffect(() => { seriesRef.current = series; }, [series]);
  useEffect(() => { onCrosshairMoveRef.current = onCrosshairMove; }, [onCrosshairMove]);
  const onSeriesReadyRef = useRef(onSeriesReady);
  useEffect(() => { onSeriesReadyRef.current = onSeriesReady; }, [onSeriesReady]);

  const getHeight = useCallback(() => {
    if (height > 0) return height;
    return containerRef.current?.clientHeight || 400;
  }, [height]);

  const initChart = useCallback(() => {
    if (!containerRef.current) return;
    const colors = readThemeColors();
    colorsRef.current = colors;
    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: colors.bg },
        textColor: colors.textDim,
      },
      grid: {
        vertLines: { color: colors.gridSoft },
        horzLines: { color: colors.gridSoft },
      },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: colors.gridSoft },
      timeScale: { borderColor: colors.gridSoft, timeVisible: true },
      width: containerRef.current.clientWidth,
      height: getHeight(),
    });
    chartRef.current = chart;
    if (chartApiRef) chartApiRef.current = chart;

    chart.subscribeCrosshairMove((param) => {
      if (!param.time) { onCrosshairMoveRef.current?.(null, {}); return; }
      const values: Record<string, number> = {};
      seriesMap.current.forEach((s, id) => {
        const v = param.seriesData.get(s);
        if (v && 'close' in v) values[id] = (v as { close: number }).close;
        else if (v && 'value' in v) values[id] = (v as { value: number }).value;
      });
      onCrosshairMoveRef.current?.(String(param.time), values);
    });
  }, [getHeight, chartApiRef]);

  // Chart lifecycle — mount/unmount ONLY. Colors are read once at creation
  // time (correct for the common case: theme was already set in Settings
  // before this component ever mounted). Deliberately NOT keyed on `theme` —
  // see the live-restyle effect below for why a full recreate-on-toggle is
  // avoided here.
  useEffect(() => {
    initChart();
    const observer = new ResizeObserver(() => {
      if (chartRef.current && containerRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
          height: getHeight(),
        });
      }
    });
    if (containerRef.current) observer.observe(containerRef.current);
    return () => {
      observer.disconnect();
      chartRef.current?.remove();
      chartRef.current = null;
      seriesMap.current.clear();
      prevPaneCountRef.current = 0;
    };
  }, [initChart]);

  // Live theme toggle while already mounted — restyle in place via
  // lightweight-charts' own applyOptions API, never remove()/createChart()
  // again. ChartWorkspace hangs volume-profile/preview overlays, drag
  // handlers, and a regime-overlay series off this exact chart/series
  // instance; a full teardown-and-recreate on every toggle would put all of
  // that at risk for a color change. Only series tracked in seriesMap (this
  // component's own `series` prop) are restyled; series ChartWorkspace adds
  // directly to the chart outside that prop are untouched, same as before.
  useEffect(() => {
    if (isFirstThemeRunRef.current) { isFirstThemeRunRef.current = false; return; }
    const chart = chartRef.current;
    if (!chart) return;
    const colors = readThemeColors();
    colorsRef.current = colors;
    chart.applyOptions({
      layout: { background: { color: colors.bg }, textColor: colors.textDim },
      grid: {
        vertLines: { color: colors.gridSoft },
        horzLines: { color: colors.gridSoft },
      },
      rightPriceScale: { borderColor: colors.gridSoft },
      timeScale: { borderColor: colors.gridSoft },
    });
    seriesMap.current.forEach((s, id) => {
      const cfg = seriesRef.current.find((c) => c.id === id);
      if (!cfg) return;
      if (cfg.type === 'Candlestick') {
        (s as ISeriesApi<'Candlestick'>).applyOptions({
          upColor: colors.passColor, downColor: colors.rejColor,
          wickUpColor: colors.passColor, wickDownColor: colors.rejColor,
        });
      } else if (cfg.type === 'Bar') {
        (s as ISeriesApi<'Bar'>).applyOptions({
          upColor: colors.passColor, downColor: colors.rejColor,
        });
      } else if (!cfg.color) {
        // Only restyle indicator series that didn't request an explicit
        // color — one that did (cfg.color set) keeps the caller's choice.
        (s as ISeriesApi<'Line' | 'Histogram'>).applyOptions({
          color: cfg.type === 'Line' ? colors.passColor : colors.gridSoft,
        });
      }
    });
    // theme is the only real trigger here — series is read via seriesRef
    // (not a dep) so this doesn't refire on every live data tick, only on
    // an actual theme toggle.
  }, [theme]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const { passColor, rejColor } = colorsRef.current;

    // Remove series not in current config
    seriesMap.current.forEach((s, id) => {
      if (!series.find(c => c.id === id)) {
        chart.removeSeries(s);
        seriesMap.current.delete(id);
      }
    });

    // Remove panes that are now empty (lightweight-charts does not auto-remove them).
    // Iterate from the last pane downward so that removing by index stays correct.
    const panesAfterRemove = chart.panes();
    for (let i = panesAfterRemove.length - 1; i >= 1; i--) {
      if (panesAfterRemove[i].getSeries().length === 0) {
        chart.removePane(i);
      }
    }

    // Add or update series
    series.forEach((cfg) => {
      let s = seriesMap.current.get(cfg.id);
      if (!s) {
        if (cfg.type === 'Candlestick') {
          s = chart.addSeries(CandlestickSeries, {
            upColor: passColor,
            downColor: rejColor,
            borderVisible: false,
            wickUpColor: passColor,
            wickDownColor: rejColor,
          }, cfg.paneIndex ?? 0);
          if ((cfg.paneIndex ?? 0) === 0) {
            if (mainSeriesRef) mainSeriesRef.current = s as ISeriesApi<'Candlestick'>;
            onSeriesReadyRef.current?.(chart, s as ISeriesApi<'Candlestick'>);
          }
        } else if (cfg.type === 'Bar') {
          s = chart.addSeries(BarSeries, {
            upColor: passColor, downColor: rejColor,
          }, cfg.paneIndex ?? 0);
          if ((cfg.paneIndex ?? 0) === 0) {
            if (mainSeriesRef) mainSeriesRef.current = s as unknown as ISeriesApi<'Candlestick'>;
            onSeriesReadyRef.current?.(chart, s as unknown as ISeriesApi<'Candlestick'>);
          }
        } else if (cfg.type === 'Histogram') {
          s = chart.addSeries(HistogramSeries, {
            color: cfg.color ?? colorsRef.current.gridSoft,
            priceScaleId: cfg.priceScaleId ?? 'right',
          }, cfg.paneIndex ?? 0);
        } else {
          s = chart.addSeries(LineSeries, {
            color: cfg.color ?? passColor,
            lineWidth: 1,
            priceScaleId: cfg.priceScaleId ?? 'right',
          }, cfg.paneIndex ?? 0);
          if ((cfg.paneIndex ?? 0) === 0) {
            if (mainSeriesRef) mainSeriesRef.current = s as unknown as ISeriesApi<'Candlestick'>;
            onSeriesReadyRef.current?.(chart, s as unknown as ISeriesApi<'Candlestick'>);
          }
        }
        seriesMap.current.set(cfg.id, s);
      }

      if (cfg.type === 'Candlestick' || cfg.type === 'Bar') {
        (s as ISeriesApi<'Candlestick' | 'Bar'>).setData(
          (cfg.data as Candle[]).map(c => ({
            time: c.time as Time,
            open: c.open, high: c.high, low: c.low, close: c.close,
          }))
        );
      } else {
        (s as ISeriesApi<'Line' | 'Histogram'>).setData(
          (cfg.data as Point[]).map(p => ({ time: p.time as Time, value: p.value }))
        );
      }
    });

    // Set proportional pane heights only when the pane count changes, not on every data tick.
    // Main pane (0) gets 60%, remaining 40% is split evenly among sub-panes.
    const panes = chart.panes();
    const currentPaneCount = panes.length;
    if (currentPaneCount !== prevPaneCountRef.current) {
      prevPaneCountRef.current = currentPaneCount;
      if (currentPaneCount > 1) {
        const totalHeight = containerRef.current?.clientHeight || getHeight();
        const mainHeight = Math.round(totalHeight * 0.6);
        const subHeight = Math.round((totalHeight - mainHeight) / (currentPaneCount - 1));
        panes[0].setHeight(mainHeight);
        for (let i = 1; i < currentPaneCount; i++) {
          panes[i].setHeight(subHeight);
        }
      }
    }
  }, [series, getHeight, mainSeriesRef]);

  return (
    <div
      ref={containerRef}
      className={styles.pane}
      style={height > 0 ? { height } : { height: '100%' }}
    />
  );
}
```

- [ ] **Step 6: Add a test for the Line/Histogram restyle branch**

The live-restyle effect has a separate code path for non-candlestick series (`else if (!cfg.color) { ... }` — only restyles indicator series that didn't request an explicit color). None of the 4 tests above exercise it. Add one more test to the same `describe` block, after the `'live-restyles the existing chart on a theme toggle...'` test:

```tsx
  it('restyles an uncolored Line series on theme toggle but leaves an explicitly-colored one alone', () => {
    mockComputedStyle(TOKENS);
    useThemeStore.setState({ theme: 'dark' });
    const { rerender } = render(
      <ChartPane
        series={[
          { id: 'default-line', type: 'Line', data: [] },
          { id: 'custom-line', type: 'Line', data: [], color: '#AB12CD' },
        ]}
      />,
    );
    const chart = (createChart as jest.Mock).mock.results[0].value;
    const defaultLineSeries = chart.addSeries.mock.results[0].value;
    const customLineSeries = chart.addSeries.mock.results[1].value;

    mockComputedStyle({ ...TOKENS, '--pass': '#00FF00' });
    useThemeStore.setState({ theme: 'light' });
    rerender(
      <ChartPane
        series={[
          { id: 'default-line', type: 'Line', data: [] },
          { id: 'custom-line', type: 'Line', data: [], color: '#AB12CD' },
        ]}
      />,
    );

    expect(defaultLineSeries.applyOptions).toHaveBeenCalledWith(
      expect.objectContaining({ color: '#00FF00' }),
    );
    expect(customLineSeries.applyOptions).not.toHaveBeenCalled();
  });
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd frontend && npm run test -- --testPathPattern=ChartPane`
Expected: PASS — all five tests green, including the live-restyle-without-recreation test and the Line/Histogram-branch test.

- [ ] **Step 8: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean, no errors.

- [ ] **Step 9: Manual verification in the browser**

Start the dev server (`npm run dev` in `frontend/`), open `/chart`, and confirm the chart renders with the currently-active theme's palette (not always-dark). Then toggle the theme in Settings (Appearance) while `/chart` stays open in another tab/window and confirm the chart repaints live. If any drawings or the volume-profile overlay are visible, confirm they survive the toggle undisturbed (proving the chart instance wasn't torn down).

- [ ] **Step 10: Commit**

```bash
git add frontend/components/organisms/ChartPane/index.tsx frontend/__mocks__/lightweight-charts.js frontend/jest.setup.ts frontend/components/organisms/ChartPane/__tests__/ChartPane.test.tsx
git commit -m "fix(chart-pane): read theme tokens instead of hardcoded dark colors"
```

---

## Task 3: Fix Options-mode fundamentals caution/reject-above sliders

The Step-3 "Fundamentals caution above" / "Fundamentals reject above" sliders (bearish-only: flags shorting a financially strong company) work correctly for Stocks-mode scans (`StockScanRequest` already has `fundamentals_caution_above`/`fundamentals_reject_above` fields, patched into the gate in `routers/stock_scan.py`). For Options-mode scans, the same slider values are sent inside the generic `overrides` dict, which the Options `ScanRequest` schema has no typed field for and the Options pipeline never reads — the sliders silently do nothing.

The fix centralizes the bearish-override patch-in inside the already-shared `resolve_fundamentals_gate()` helper (used by both `routers/scan.py` and `routers/stock_scan.py`), and adds the two missing fields to `ScanRequest`. Because `routers/scan.py` already calls `_resolve_fundamentals_gate(req)` once per scan (`backend/app/routers/scan.py:1166`), no changes are needed there — the fix flows through automatically once the schema field and the shared helper exist.

**Files:**
- Modify: `backend/app/schemas/__init__.py:505-508`
- Modify: `backend/app/services/fundamentals_gate.py`
- Modify: `frontend/lib/api.ts:394-402`
- Modify: `frontend/components/organisms/RunScanButton/index.tsx:140-183`
- Test: `backend/tests/test_scan_schema.py`
- Test: `backend/tests/test_fundamentals_gate_resolve.py` (new)
- Test: `frontend/components/organisms/RunScanButton/__tests__/RunScanButton.test.tsx`

- [ ] **Step 1: Write the failing backend schema test**

Add to `backend/tests/test_scan_schema.py` (after `test_confidence_overrides_default_none`):

```python
def test_scan_request_accepts_bearish_fundamentals_overrides():
    req = ScanRequest.model_validate({
        "universe": ["AAPL"],
        "direction": "Bearish",
        "horizon": "Swing",
        "fundamentals_caution_above": 65,
        "fundamentals_reject_above": 85,
    })
    assert req.fundamentals_caution_above == 65
    assert req.fundamentals_reject_above == 85
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_scan_schema.py::test_scan_request_accepts_bearish_fundamentals_overrides -v`
Expected: FAIL — Pydantic v2 silently ignores the unknown `fundamentals_caution_above`/`fundamentals_reject_above` keys (default `extra='ignore'`), so `req.fundamentals_caution_above` raises `AttributeError`.

- [ ] **Step 3: Add the fields to `ScanRequest`**

In `backend/app/schemas/__init__.py`, after line 508 (`fundamentals_de_reject: Optional[float] = None`), add:

```python
    # Per-scan bearish-fundamentals overrides (Step-3 "Fundamentals Bearish"
    # sliders, BEARISH SCANS ONLY) — health score too high to short safely.
    # Mirrors StockScanRequest's fields of the same name (schemas/stock_scan.py).
    fundamentals_caution_above: Optional[float] = None
    fundamentals_reject_above:  Optional[float] = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_scan_schema.py -v`
Expected: PASS — all schema tests green.

- [ ] **Step 5: Write the failing test for the shared gate resolver**

Create `backend/tests/test_fundamentals_gate_resolve.py`:

```python
from app.schemas import ScanRequest
from app.services.fundamentals_gate import resolve_fundamentals_gate


def _req(**overrides) -> ScanRequest:
    base = dict(universe=["AAPL"], direction="Bearish", horizon="Swing")
    base.update(overrides)
    return ScanRequest.model_validate(base)


def test_bearish_scan_patches_caution_and_reject_above_into_gate():
    req = _req(fundamentals_caution_above=65, fundamentals_reject_above=85)
    gate = resolve_fundamentals_gate(req)
    assert gate["cautionAbove"] == 65
    assert gate["rejectAbove"] == 85


def test_bullish_scan_ignores_caution_and_reject_above():
    """The bearish-only override must not leak into bullish scans — those
    values only make sense for 'don't short a strong company' logic."""
    req = _req(direction="Bullish", fundamentals_caution_above=65, fundamentals_reject_above=85)
    gate = resolve_fundamentals_gate(req)
    assert gate.get("cautionAbove") != 65
    assert gate.get("rejectAbove") != 85


def test_absent_overrides_leave_yaml_defaults_untouched():
    req = _req()
    gate = resolve_fundamentals_gate(req)
    from app.services.config_loader import load_scoring_cfg
    default_gate = load_scoring_cfg().get("fundamentals_gate", {})
    assert gate.get("cautionAbove") == default_gate.get("cautionAbove")
    assert gate.get("rejectAbove") == default_gate.get("rejectAbove")
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd backend && pytest tests/test_fundamentals_gate_resolve.py -v`
Expected: FAIL on `test_bearish_scan_patches_caution_and_reject_above_into_gate` — `resolve_fundamentals_gate` doesn't read `fundamentals_caution_above`/`fundamentals_reject_above` at all yet, so `gate["cautionAbove"]` is the YAML default (70), not 65.

- [ ] **Step 7: Implement the bearish-override patch-in**

Replace the full contents of `backend/app/services/fundamentals_gate.py`:

```python
"""Shared helper: merge YAML fundamentals_gate defaults with per-request overrides.

Extracted from app.routers.scan so both the options-scan and stock-scan routers
can import it without a sibling-router cross-dependency.
"""
from __future__ import annotations

import copy

from app.services.config_loader import load_scoring_cfg


def resolve_fundamentals_gate(req) -> dict:
    """Return the effective fundamentals_gate config dict for a scan request.

    Starts from the YAML fundamentals_gate block and applies any per-request
    field overrides (fundamentals_enabled, fundamentals_caution_below, etc.).
    Bearish-only overrides (fundamentals_caution_above/reject_above — "don't
    short a company whose fundamentals are too strong") are applied only when
    req.direction is Bearish, matching the Step-3 slider's documented scope.
    """
    g = copy.deepcopy(load_scoring_cfg().get("fundamentals_gate", {}))
    if req.fundamentals_enabled is not None:
        g["enabled"] = req.fundamentals_enabled
    if req.fundamentals_caution_below is not None:
        g["cautionBelow"] = req.fundamentals_caution_below
    if req.fundamentals_reject_below is not None:
        g["rejectBelow"] = req.fundamentals_reject_below
    if req.fundamentals_de_reject is not None:
        g.setdefault("safety", {})["debt_to_equity_reject"] = req.fundamentals_de_reject
    if str(req.direction).lower() in ("bearish", "bear"):
        if req.fundamentals_caution_above is not None:
            g["cautionAbove"] = req.fundamentals_caution_above
        if req.fundamentals_reject_above is not None:
            g["rejectAbove"] = req.fundamentals_reject_above
    return g
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd backend && pytest tests/test_fundamentals_gate_resolve.py tests/test_scan_schema.py tests/test_fundamentals_gate_bearish.py -v`
Expected: PASS — all green, including the pre-existing `test_fundamentals_gate_bearish.py` (unaffected, tests `score_stock` directly with a hand-built gate dict).

- [ ] **Step 9: Run the full backend suite to check for regressions**

Run: `cd backend && pytest tests/test_stock_scan_router.py tests/test_scan_endpoint.py -v`
Expected: PASS — `routers/stock_scan.py`'s own inline bearish-override patch (lines 322-330, 683-689) still runs too and now just redundantly re-assigns the same values `resolve_fundamentals_gate` already set; harmless, not in scope to remove here (tracked separately as a Medium finding).

- [ ] **Step 10: Write the failing frontend test**

Add to `frontend/components/organisms/RunScanButton/__tests__/RunScanButton.test.tsx`, inside the existing `describe` block:

```tsx
  it('sends Step-3 bearish-fundamentals slider values as top-level filters for Options scans', async () => {
    useScanStore.setState({
      screenerMode: 'options',
      context: { direction: 'Bearish', horizonPreset: 'Swing', holdMin: 5, holdMax: 15, universe: 'SP500' },
      scanOverrides: { fundamentals_caution_above: 65, fundamentals_reject_above: 85 },
    } as any);
    mockPostScan.mockResolvedValue({ scan_id: 'S1', timestamp: 't', candidates: [], rejected: [] });

    render(<RunScanButton />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /run scan/i }));
      await Promise.resolve();
    });

    const [, , , , filters, overrides] = mockPostScan.mock.calls[0];
    expect(filters.fundamentals_caution_above).toBe(65);
    expect(filters.fundamentals_reject_above).toBe(85);
    expect(overrides).not.toHaveProperty('fundamentals_caution_above');
    expect(overrides).not.toHaveProperty('fundamentals_reject_above');
  });
```

- [ ] **Step 11: Run test to verify it fails**

Run: `cd frontend && npm run test -- --testPathPattern=RunScanButton`
Expected: FAIL — `filters.fundamentals_caution_above` is `undefined`; the values currently land in `overrides` instead.

- [ ] **Step 12: Add the fields to `api.ts`'s `postScan` filters type**

In `frontend/lib/api.ts`, in the `postScan` method's `filters` parameter type (after line 401, `fundamentals_reject_below?: number;`), add:

```ts
      fundamentals_caution_above?: number;
      fundamentals_reject_above?:  number;
```

So the block (lines 394-402) reads:

```ts
    filters?: {
      min_price?: number; max_price?: number; min_cap_usd?: number; max_cap_usd?: number;
      confidence_caution_below?: number; confidence_reject_below?: number;
      confidence_atr_mult_target?: number; confidence_atr_mult_stop?: number;
      fundamentals_enabled?: boolean;
      fundamentals_caution_below?: number;
      fundamentals_reject_below?: number;
      fundamentals_de_reject?: number;
      fundamentals_caution_above?: number;
      fundamentals_reject_above?:  number;
    },
```

- [ ] **Step 13: Wire `RunScanButton` to send the sliders as filters, not overrides**

In `frontend/components/organisms/RunScanButton/index.tsx`, change lines 144-146:

```ts
    const { confidence_caution_below: _cb, confidence_reject_below: _rb,
            confidence_atr_mult_target: _amt, confidence_atr_mult_stop: _ams,
            ...scoreOnlyOverrides } = scanOverrides;
```

to:

```ts
    const { confidence_caution_below: _cb, confidence_reject_below: _rb,
            confidence_atr_mult_target: _amt, confidence_atr_mult_stop: _ams,
            fundamentals_caution_above: _fca, fundamentals_reject_above: _fra,
            ...scoreOnlyOverrides } = scanOverrides;
```

Then, after line 183 (`filters.fundamentals_de_reject = fGate.deReject;`), add:

```ts
    // Bearish-fundamentals override (BEARISH SCANS ONLY) — Step-3 Execution
    // Parameters sliders. Must ride in top-level filters (ScanRequest fields),
    // not the generic overrides dict, which the Options fundamentals gate
    // never reads (see resolve_fundamentals_gate in fundamentals_gate.py).
    if (typeof scanOverrides.fundamentals_caution_above === 'number') {
      filters.fundamentals_caution_above = scanOverrides.fundamentals_caution_above;
    }
    if (typeof scanOverrides.fundamentals_reject_above === 'number') {
      filters.fundamentals_reject_above = scanOverrides.fundamentals_reject_above;
    }
```

- [ ] **Step 14: Run test to verify it passes**

Run: `cd frontend && npm run test -- --testPathPattern=RunScanButton`
Expected: PASS — all RunScanButton tests green.

- [ ] **Step 15: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean, no errors.

- [ ] **Step 16: Commit**

```bash
git add backend/app/schemas/__init__.py backend/app/services/fundamentals_gate.py backend/tests/test_scan_schema.py backend/tests/test_fundamentals_gate_resolve.py frontend/lib/api.ts frontend/components/organisms/RunScanButton/index.tsx frontend/components/organisms/RunScanButton/__tests__/RunScanButton.test.tsx
git commit -m "fix(options-scan): wire bearish-fundamentals sliders into the Options scan request"
```

---

## Task 4: Fix event-loop-blocking order placement

`POST /broker/stock-order` and `POST /broker/option-order` are `async def` handlers, but `router_.execute(req.broker, order)` runs synchronously on the event-loop thread. For IBKR/Tradier/Alpaca, this reaches a blocking `httpx.post(...)` (not `httpx.AsyncClient`) with up to a 10s timeout — freezing every other in-flight request (scans, price fetches, websocket alerts) for the duration. The fix wraps the single `router_.execute(...)` call site in each handler with `asyncio.to_thread(...)`, moving the entire synchronous call chain (including the adapter's blocking HTTP call) off the event loop. This covers all four brokers uniformly through one call site per handler — no adapter-level changes needed.

**Files:**
- Modify: `backend/app/routers/broker.py`
- Test: `backend/tests/test_broker_router.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_broker_router.py` (at the end of the file):

```python
@pytest.mark.asyncio
async def test_stock_order_does_not_block_event_loop():
    """Regression for the High finding: router_.execute() ran straight on the
    event loop with no to_thread hop, so a slow synchronous adapter call (e.g.
    IBKR/Tradier/Alpaca's blocking httpx.post) froze every other coroutine —
    scans, price fetches, websocket alerts — for the whole round trip."""
    import time as _time

    class SlowAdapter:
        def place_order(self, order):
            _time.sleep(0.3)  # simulates a slow synchronous httpx.post
            return OrderResult(order_id="SLOW1", status="ok", broker="ibkr_paper")

    router = BrokerRouter(adapters={"ibkr_paper": SlowAdapter()})
    tick_elapsed: dict[str, float] = {}
    loop = asyncio.get_running_loop()
    t0 = loop.time()

    async def tick_soon():
        await asyncio.sleep(0.05)
        tick_elapsed["seconds"] = loop.time() - t0

    with patch("app.routers.broker.build_router_from_credentials", return_value=router):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            order_task = asyncio.create_task(client.post("/broker/stock-order", json={
                "broker": "ibkr_paper", "symbol": "AAPL",
                "action": "BUY", "effect": "OPEN", "quantity": 1, "order_type": "MKT",
            }))
            tick_task = asyncio.create_task(tick_soon())
            resp = await order_task
            await tick_task
    assert resp.status_code == 200
    # If the handler blocked the loop for the adapter's full 0.3s synchronous
    # sleep, the concurrent 0.05s tick couldn't resolve until that block
    # cleared, landing tick_elapsed near/after 0.3s instead of ~0.05s.
    assert tick_elapsed["seconds"] < 0.2, (
        f"tick_soon() took {tick_elapsed['seconds']:.3f}s to resolve — "
        f"the order handler is still blocking the event loop"
    )
```

Add `import asyncio` to the top of the file if not already present (check first — the file currently has no `asyncio` import).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_broker_router.py::test_stock_order_does_not_block_event_loop -v`
Expected: FAIL — `tick_elapsed["seconds"]` is ~0.3s (or slightly more), because `router_.execute(...)` runs synchronously on the loop and blocks `tick_soon()`'s `asyncio.sleep(0.05)` from resolving until the adapter's `time.sleep(0.3)` finishes.

- [ ] **Step 3: Add `asyncio` import and wrap both `execute` calls in `to_thread`**

In `backend/app/routers/broker.py`, change line 3 from:

```python
import threading
```

to:

```python
import asyncio
import threading
```

Then change line 122 from:

```python
        result = router_.execute(req.broker, order)
```

to:

```python
        result = await asyncio.to_thread(router_.execute, req.broker, order)
```

And change line 183 (the same line inside `place_option_order`) from:

```python
        result = router_.execute(req.broker, order)
```

to:

```python
        result = await asyncio.to_thread(router_.execute, req.broker, order)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_broker_router.py::test_stock_order_does_not_block_event_loop -v`
Expected: PASS — `router_.execute` now runs in a worker thread, freeing the event loop; `tick_elapsed["seconds"]` lands near 0.05s.

- [ ] **Step 5: Run the full broker test suite to check for regressions**

Run: `cd backend && pytest tests/test_broker_router.py tests/test_broker_idempotency.py -v`
Expected: PASS — all existing tests (idempotency dedup, effect propagation, live-broker blocking, etc.) still green; `asyncio.to_thread` preserves exceptions raised inside `router_.execute` (they propagate through the awaited call), so the existing `except ValueError`/`except RuntimeError` handling around each call site is unaffected.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/broker.py backend/tests/test_broker_router.py
git commit -m "fix(broker): run order execution in a worker thread so it can't block the event loop"
```

---

## Task 5: Fix unreachable "reversal" watch alert

`strategy_watch_evaluator.py`'s armed-phase check `signal.direction != state.get("direction")` can never be true: each watch's direction is fixed at creation, `signal` is always computed by calling the strategy's signal function with that same fixed direction (so `signal.direction` always echoes it back), and `state["direction"]` was itself set from an earlier `signal.direction` — so the two can never disagree. The fix makes the reversal check meaningful: when armed and neither stop nor target has hit, also evaluate the signal function for the **opposite** direction (using that direction's own tuned params, same pattern as the existing `get_active(key, wdir)` lookup for the primary direction). If the opposite-direction signal fires, that's a genuine reversal — the watch re-arms in the new direction.

**Files:**
- Modify: `backend/app/services/strategy_watch_evaluator.py`
- Test: `backend/tests/test_strategy_watch_evaluator.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_strategy_watch_evaluator.py` (after `test_armed_holding_emits_nothing`):

```python
@pytest.mark.asyncio
async def test_armed_opposite_direction_signal_fires_reversal():
    """The only way a reversal can be genuine: the OPPOSITE direction's signal
    fires while armed (not stop/target hit). Before this fix, the evaluator
    only ever computed the signal for the watch's own fixed direction, so
    signal.direction could never disagree with state['direction'] and this
    branch was dead code."""
    store = MagicMock()
    store.list_watches.return_value = [_watch("armed", direction="Bullish",
                                              entry_price=100.0, stop_price=95.0,
                                              target_price=110.0)]

    def fake_signal(bars, direction, **k):
        # Bullish primary signal: nothing new (price is holding, not re-triggering).
        # Bearish (opposite) signal: fires -- this is the reversal.
        if direction == "Bearish":
            return _signal(direction="Bearish", entry=102.0, stop=108.0, target=90.0)
        return None

    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(102.0)), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": fake_signal}):
        events = await evaluate_all()

    assert len(events) == 1
    assert events[0].event_type == "reversal"
    assert events[0].direction == "Bearish"
    updated_state = store.update_state.call_args[0][1]
    assert updated_state["phase"] == "armed"
    assert updated_state["direction"] == "Bearish"


@pytest.mark.asyncio
async def test_armed_no_opposite_signal_emits_nothing():
    """Holding steady (no stop/target hit, no opposite-direction signal) must
    still emit nothing -- confirms the new opposite-direction check doesn't
    fire spuriously when there's genuinely no reversal."""
    store = MagicMock()
    store.list_watches.return_value = [_watch("armed", direction="Bullish",
                                              entry_price=100.0, stop_price=95.0,
                                              target_price=110.0)]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(102.0)), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, direction, **k: None}):
        events = await evaluate_all()
    assert events == []
    store.update_state.assert_not_called()


@pytest.mark.asyncio
async def test_stop_hit_takes_priority_over_opposite_direction_signal():
    """If the stop is hit AND the opposite direction would also signal, the
    exit_stop transition must win -- reversal is only checked as the final
    elif, after both stop_hit and target_hit."""
    store = MagicMock()
    store.list_watches.return_value = [_watch("armed", direction="Bullish",
                                              entry_price=100.0, stop_price=95.0,
                                              target_price=110.0)]

    def fake_signal(bars, direction, **k):
        return _signal(direction="Bearish") if direction == "Bearish" else None

    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(94.0)), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": fake_signal}):
        events = await evaluate_all()
    assert events[0].event_type == "exit_stop"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_strategy_watch_evaluator.py::test_armed_opposite_direction_signal_fires_reversal -v`
Expected: FAIL — `events` is `[]` because the current code never calls `fn` with `direction="Bearish"`; the primary `signal` (computed once per watch with the fixed `wdir="Bullish"`) is `None` (per `fake_signal`), so neither the entry/exit branches nor the (dead) reversal `elif` ever see a Bearish signal.

- [ ] **Step 3: Implement the opposite-direction reversal check**

In `backend/app/services/strategy_watch_evaluator.py`, first update the module docstring (the full triple-quoted block, currently lines 2-10) from:

```python
"""Runs each enabled strategy-watch on daily bars and emits state-transition events.

The state machine (per watch) is the dedup mechanism: it only returns events on a
genuine transition (idle→entry, armed→exit_stop/exit_target, armed→reversal), so a
standing setup never re-alerts. Reversal is wired but still dormant in practice:
each watch's direction (Bullish/Bearish) is fixed at creation and there is no
endpoint to change it later, so the signal function is evaluated with the same
direction every tick and can never disagree with the armed state's direction.
"""
```

to:

```python
"""Runs each enabled strategy-watch on daily bars and emits state-transition events.

The state machine (per watch) is the dedup mechanism: it only returns events on a
genuine transition (idle→entry, armed→exit_stop/exit_target, armed→reversal), so a
standing setup never re-alerts. Each watch's direction (Bullish/Bearish) is fixed
at creation, so a reversal can't be detected by comparing the primary signal
(always evaluated in the watch's own fixed direction) against the armed state's
direction -- those can never disagree. Instead, while armed (and neither stop nor
target has hit), the evaluator also evaluates the signal function for the
OPPOSITE direction, using that direction's own tuned params (get_active). If the
opposite-direction signal fires, that's a genuine reversal and the watch re-arms
in the new direction.
"""
```

Then replace the `elif signal is not None and signal.direction != state.get("direction"):` branch (lines 198-210) with:

```python
            else:
                # NOTE: no hysteresis/cooldown here -- if both directions' signal
                # functions are "sticky" (true for several consecutive days, common
                # for trend/breakout signals), a watch can in principle whipsaw
                # Bullish<->Bearish on consecutive ticks, notifying each time.
                # Accepted as a known limitation of this fix (making reversal
                # reachable, not adding debounce) -- revisit if this proves noisy.
                opposite_dir = "Bearish" if sdir == "Bullish" else "Bullish"
                try:
                    opp_params = get_active(key, opposite_dir)
                    opp_params.update(params_override)
                    opp_signal = fn(bars, direction=opposite_dir, **opp_params)
                except Exception as exc:
                    logger.warning("strategy-watch: %s reversal signal failed for %s — %s",
                                    key, symbol, exc)
                    opp_signal = None
                if opp_signal is not None:
                    event = WatchEvent(
                        watch_id=w["id"], symbol=symbol, strategy_key=key,
                        event_type="reversal", direction=opposite_dir,
                        entry=opp_signal.entry_price, stop=opp_signal.stop_price,
                        target=opp_signal.target_price, rr_ratio=round(opp_signal.rr_ratio, 2),
                        close=close,
                        reason=f"{symbol}: {_strategy_label(key)} reversal to {opposite_dir} at {close}",
                    )
                    state = {"phase": "armed", "direction": opposite_dir,
                             "entry_price": opp_signal.entry_price, "stop_price": opp_signal.stop_price,
                             "target_price": opp_signal.target_price, "last_event": "reversal",
                             "last_event_at": _now_iso()}
```

This reuses `params_override` (already computed once per watch, before the phase branch — see lines 109-113) and requires no new imports: `get_active` is already imported at the top of the file (line 25, `from app.services.strategy_param_store import get_active`).

- [ ] **Step 4: Fix a pre-existing test whose mock ignores the `direction` kwarg**

`test_armed_holding_emits_nothing` (in `backend/tests/test_strategy_watch_evaluator.py`, unmodified so far) patches `_SIGNAL_FNS["pullback_ema"]` with `lambda bars, **k: _signal()` — a mock that returns a truthy signal **regardless of which direction it's called with**. Before this task's fix, that didn't matter: the dead reversal branch never called `fn` a second time. After the fix, the new `else` branch calls `fn(bars, direction=opposite_dir, **opp_params)` for the *opposite* direction too, and this direction-blind mock returns non-`None` for that call as well — so `opp_signal is not None` becomes `True`, a spurious `"reversal"` event fires, and the test's `events == []` / `store.update_state.assert_not_called()` assertions now fail. This isn't a new test to write — it's an existing, currently-passing test whose mock happens to rely on behavior this task deliberately changes, so it must be updated in the same commit.

Change the test's mock from:

```python
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: _signal()}):
```

to:

```python
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, direction, **k: _signal(direction) if direction == "Bullish" else None}):
```

This makes the test genuinely represent "armed and holding": the primary (Bullish) direction still signals (the setup is still valid, nothing new), and the opposite (Bearish) direction does not (no reversal) — so nothing should fire, which is exactly what the test already asserts.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/test_strategy_watch_evaluator.py -v`
Expected: PASS — all tests green, including the 3 new ones, the updated `test_armed_holding_emits_nothing`, and every other pre-existing test (stop/target/entry/sustain/composite paths, none of which reach the new `else` branch with a direction-blind mock).

- [ ] **Step 6: Run the full strategy-watch test suite to check for regressions**

Run: `cd backend && pytest tests/test_strategy_watch_evaluator.py tests/test_strategy_watch_bearish.py tests/test_strategy_watch_router.py tests/test_strategy_watch_scheduler.py tests/test_strategy_watch_store.py -v`
Expected: PASS — all green.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/strategy_watch_evaluator.py backend/tests/test_strategy_watch_evaluator.py
git commit -m "fix(strategy-watch): make reversal detection reachable via opposite-direction signal check"
```

---

## Final verification

- [ ] **Full backend suite**

Run: `cd backend && pytest`
Expected: all green, no regressions across the 5 changed modules.

- [ ] **Full frontend suite + typecheck**

Run: `cd frontend && npm run typecheck && npm run test`
Expected: clean typecheck, all tests green.
