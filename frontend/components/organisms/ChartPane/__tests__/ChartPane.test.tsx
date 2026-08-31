import { render, act } from '@testing-library/react';
import { createChart } from 'lightweight-charts';
import ChartPane, { mainSeriesId } from '@/components/organisms/ChartPane';
import { useThemeStore } from '@/lib/theme';

const TOKENS: Record<string, string> = {
  '--bg-surface': '#FFFFFF',
  '--border-subtle': '#DDE1F0',
  '--text-secondary': '#5A6070',
  '--pass': '#1A9188',
  '--reject': '#D32F2F',
  '--accent': '#2962FF',
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
    jest.useFakeTimers();
    try {
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
      // The actual color read is deferred to the next tick (see ChartPane's
      // comment: an ancestor, ThemeProvider, updates <html data-theme> in its
      // own effect, which — because React fires descendant effects before
      // ancestor effects — hasn't landed yet by the end of this synchronous
      // render pass). Flush that deferred read before asserting.
      act(() => { jest.runAllTimers(); });

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
    } finally {
      jest.useRealTimers();
    }
  });

  it('restyles an uncolored Line series on theme toggle but leaves an explicitly-colored one alone', () => {
    jest.useFakeTimers();
    try {
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

      // Creation-time default must be the neutral --accent token, not --pass —
      // a plain price/indicator line isn't a PASS/CAUTION/REJECT status.
      const [, defaultLineCreateOptions] = chart.addSeries.mock.calls[0];
      expect(defaultLineCreateOptions.color).toBe(TOKENS['--accent']);

      mockComputedStyle({ ...TOKENS, '--accent': '#00FF00' });
      useThemeStore.setState({ theme: 'light' });
      rerender(
        <ChartPane
          series={[
            { id: 'default-line', type: 'Line', data: [] },
            { id: 'custom-line', type: 'Line', data: [], color: '#AB12CD' },
          ]}
        />,
      );
      act(() => { jest.runAllTimers(); });

      // Neutral --accent, not --pass/--reject -- an unstyled price/indicator
      // line must not always render as "PASS green" regardless of price action.
      expect(defaultLineSeries.applyOptions).toHaveBeenCalledWith(
        expect.objectContaining({ color: '#00FF00' }),
      );
      expect(customLineSeries.applyOptions).not.toHaveBeenCalled();
    } finally {
      jest.useRealTimers();
    }
  });
});

// Regression suite for a bug where onSeriesReady/mainSeriesRef could be
// silently reassigned to a pane-0 indicator overlay (EMA, SMA, BB...)
// instead of staying on the actual main series. Both the main series (when
// chartType is 'line') and an indicator overlay share SeriesConfig['type']
// === 'Line', so ChartPane must distinguish them by id (mainSeriesId()'s
// `candles-` prefix vs an indicator id like `ema-...`), not type — see
// isMainSeriesId's own comment in ChartPane/index.tsx for the full
// mechanism and consequence (VolumeProfilePrimitive silently drawing
// nothing once mainSeries is left pointing at a removed indicator).
//
// Fixtures below build the main-series id via mainSeriesId(), the same
// helper ChartWorkspace's buildMainSeries calls, rather than hardcoding the
// `candles-...` string — a hardcoded literal here would keep passing even
// if mainSeriesId's own prefix drifted from what isMainSeriesId checks
// against, defeating the point of centralizing it.
describe('ChartPane — onSeriesReady / mainSeriesRef identity', () => {
  beforeEach(() => {
    (createChart as jest.Mock).mockClear();
    mockComputedStyle(TOKENS);
  });

  it('fires onSeriesReady only for the main candlestick series, not for pane-0 indicator Line series created after it', () => {
    const onSeriesReady = jest.fn();
    const mainSeriesRef: Parameters<typeof ChartPane>[0]['mainSeriesRef'] = { current: null };

    render(
      <ChartPane
        series={[
          { id: mainSeriesId('candle'), type: 'Candlestick', data: [] },
          { id: 'ema-20', type: 'Line', data: [], color: '#4f8ef7' },
          { id: 'ema-50', type: 'Line', data: [], color: '#e0a030' },
        ]}
        onSeriesReady={onSeriesReady}
        mainSeriesRef={mainSeriesRef}
      />,
    );

    const chart = (createChart as jest.Mock).mock.results[0].value;
    const candleSeries = chart.addSeries.mock.results[0].value;

    expect(onSeriesReady).toHaveBeenCalledTimes(1);
    expect(onSeriesReady).toHaveBeenCalledWith(chart, candleSeries);
    expect(mainSeriesRef.current).toBe(candleSeries);
  });

  // Same guarantee for the chartType === 'line' case, where the main series
  // itself IS a Line series (id mainSeriesId('line')) sharing a pane with
  // indicator overlays — onSeriesReady must still fire for it, and stay
  // pointed at it rather than the indicator lines created alongside it.
  it('fires onSeriesReady for a Line-type main series (chartType=line) and not for indicator lines around it', () => {
    const onSeriesReady = jest.fn();
    const mainSeriesRef: Parameters<typeof ChartPane>[0]['mainSeriesRef'] = { current: null };

    render(
      <ChartPane
        series={[
          { id: mainSeriesId('line'), type: 'Line', data: [] },
          { id: 'ema-20', type: 'Line', data: [], color: '#4f8ef7' },
        ]}
        onSeriesReady={onSeriesReady}
        mainSeriesRef={mainSeriesRef}
      />,
    );

    const chart = (createChart as jest.Mock).mock.results[0].value;
    const mainLineSeries = chart.addSeries.mock.results[0].value;

    expect(onSeriesReady).toHaveBeenCalledTimes(1);
    expect(onSeriesReady).toHaveBeenCalledWith(chart, mainLineSeries);
    expect(mainSeriesRef.current).toBe(mainLineSeries);
  });

  // End-to-end version of the above: add EMA-20 then EMA-50 (last, so it's
  // the one that would have hijacked mainSeries pre-fix), then remove both
  // — the exact user action ("toggle EMA off") that used to leave
  // mainSeries dangling on a detached series. Asserts reference-identity to
  // the ORIGINAL candlestick series and a call-count of exactly 1, not just
  // "some live, coordinate-resolving pane-0 series" — the latter could in
  // principle be satisfied by a different, spurious reassignment.
  it('keeps mainSeriesRef pointed at the original candlestick series through an indicator add-then-remove cycle', () => {
    const onSeriesReady = jest.fn();
    const mainSeriesRef: Parameters<typeof ChartPane>[0]['mainSeriesRef'] = { current: null };

    const { rerender } = render(
      <ChartPane
        series={[{ id: mainSeriesId('candle'), type: 'Candlestick', data: [] }]}
        onSeriesReady={onSeriesReady}
        mainSeriesRef={mainSeriesRef}
      />,
    );

    const chart = (createChart as jest.Mock).mock.results[0].value;
    const candleSeries = chart.addSeries.mock.results[0].value;

    rerender(
      <ChartPane
        series={[
          { id: mainSeriesId('candle'), type: 'Candlestick', data: [] },
          { id: 'ema-20', type: 'Line', data: [], color: '#4f8ef7' },
          { id: 'ema-50', type: 'Line', data: [], color: '#e0a030' },
        ]}
        onSeriesReady={onSeriesReady}
        mainSeriesRef={mainSeriesRef}
      />,
    );

    // Both indicators removed again — the exact user action ("toggle EMA off")
    // that left mainSeries dangling on a detached series pre-fix.
    rerender(
      <ChartPane
        series={[{ id: mainSeriesId('candle'), type: 'Candlestick', data: [] }]}
        onSeriesReady={onSeriesReady}
        mainSeriesRef={mainSeriesRef}
      />,
    );

    const pane0Series = chart.panes()[0].getSeries();

    expect(onSeriesReady).toHaveBeenCalledTimes(1);
    expect(mainSeriesRef.current).toBe(candleSeries);
    expect(pane0Series).toContain(candleSeries);
    expect(candleSeries.priceToCoordinate(100)).not.toBeNull();
  });

  // The scenario onSeriesReady's own doc comment calls out explicitly
  // ("Called whenever the pane-0 main series is created or replaced, e.g.
  // chart-type switch"): switching chartType while a Line-typed indicator
  // sits on the same pane must retarget mainSeriesRef to the NEW main
  // series exactly once per switch, never landing on the coexisting
  // indicator line even though both are pane-0 Line series during the
  // candle→line transition.
  it('retargets mainSeriesRef to the new main series on a chartType switch, never to a coexisting indicator line', () => {
    const onSeriesReady = jest.fn();
    const mainSeriesRef: Parameters<typeof ChartPane>[0]['mainSeriesRef'] = { current: null };

    const { rerender } = render(
      <ChartPane
        series={[
          { id: mainSeriesId('candle'), type: 'Candlestick', data: [] },
          { id: 'ema-20', type: 'Line', data: [], color: '#4f8ef7' },
        ]}
        onSeriesReady={onSeriesReady}
        mainSeriesRef={mainSeriesRef}
      />,
    );

    const chart = (createChart as jest.Mock).mock.results[0].value;
    const candleSeries = chart.addSeries.mock.results[0].value;
    expect(mainSeriesRef.current).toBe(candleSeries);

    // chartType candle -> line: the old candles-candle series is dropped
    // from the config, a new candles-line series takes its place, and the
    // ema-20 indicator (still Line-typed, still on pane 0) stays put.
    rerender(
      <ChartPane
        series={[
          { id: mainSeriesId('line'), type: 'Line', data: [] },
          { id: 'ema-20', type: 'Line', data: [], color: '#4f8ef7' },
        ]}
        onSeriesReady={onSeriesReady}
        mainSeriesRef={mainSeriesRef}
      />,
    );

    const emaSeries = chart.addSeries.mock.results[1].value;
    const lineSeries = chart.addSeries.mock.results[2].value;

    expect(onSeriesReady).toHaveBeenCalledTimes(2);
    expect(onSeriesReady).toHaveBeenLastCalledWith(chart, lineSeries);
    expect(mainSeriesRef.current).toBe(lineSeries);
    expect(mainSeriesRef.current).not.toBe(emaSeries);

    // And back again, switching line -> candle with the indicator still present.
    rerender(
      <ChartPane
        series={[
          { id: mainSeriesId('candle'), type: 'Candlestick', data: [] },
          { id: 'ema-20', type: 'Line', data: [], color: '#4f8ef7' },
        ]}
        onSeriesReady={onSeriesReady}
        mainSeriesRef={mainSeriesRef}
      />,
    );

    const secondCandleSeries = chart.addSeries.mock.results[3].value;

    expect(onSeriesReady).toHaveBeenCalledTimes(3);
    expect(onSeriesReady).toHaveBeenLastCalledWith(chart, secondCandleSeries);
    expect(mainSeriesRef.current).toBe(secondCandleSeries);
    expect(mainSeriesRef.current).not.toBe(emaSeries);
  });
});

describe('ChartPane — malformed bars', () => {
  beforeEach(() => {
    (createChart as jest.Mock).mockClear();
    mockComputedStyle(TOKENS);
  });

  // Same crash lightweight-charts throws on a null OHLC field as
  // CandlestickChart — ChartPane (used by the standalone Chart workspace)
  // has the identical unguarded setData() call, so it needs the same
  // non-finite-bar filter.
  it('drops non-finite OHLC bars before calling setData on a Candlestick series', () => {
    const data = [
      { time: '2026-01-05', open: 100, high: 101, low: 99, close: 100.5 },
      { time: '2026-01-06', open: null, high: null, low: null, close: null },
      { time: '2026-01-07', open: 102, high: 103, low: 101, close: 102.5 },
    ];

    render(
      <ChartPane
        series={[{ id: 'main', type: 'Candlestick', data: data as any }]}
      />,
    );

    const chart = (createChart as jest.Mock).mock.results[0].value;
    const candleSeries = chart.addSeries.mock.results[0].value;
    expect(candleSeries.setData).toHaveBeenCalledWith([
      { time: '2026-01-05', open: 100, high: 101, low: 99, close: 100.5 },
      { time: '2026-01-07', open: 102, high: 103, low: 101, close: 102.5 },
    ]);
  });

  // Same class of bug as the Candlestick test above, but for the Line/Histogram
  // branch — used by the standalone Chart workspace's RSI/MACD/overlay panes,
  // which are Line/Histogram series rendered through ChartPane, not
  // CandlestickChart's own IndicatorPanel. That branch has its own unguarded
  // setData() call, so it needs its own filter and its own regression test.
  it('drops non-finite values before calling setData on a Line series', () => {
    const data = [
      { time: '2026-01-05', value: 50 },
      { time: '2026-01-06', value: null },
      { time: '2026-01-07', value: 55 },
    ];

    render(
      <ChartPane
        series={[{ id: 'rsi', type: 'Line', data: data as any }]}
      />,
    );

    const chart = (createChart as jest.Mock).mock.results[0].value;
    const lineSeries = chart.addSeries.mock.results[0].value;
    expect(lineSeries.setData).toHaveBeenCalledWith([
      { time: '2026-01-05', value: 50 },
      { time: '2026-01-07', value: 55 },
    ]);
  });
});
