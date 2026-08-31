import { render, act } from '@testing-library/react';
import { createChart } from 'lightweight-charts';
import ChartPane from '@/components/organisms/ChartPane';
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

describe('ChartPane — onSeriesReady / mainSeriesRef identity', () => {
  beforeEach(() => {
    (createChart as jest.Mock).mockClear();
    mockComputedStyle(TOKENS);
  });

  // Regression test for a bug where onSeriesReady/mainSeriesRef could be
  // silently reassigned to a pane-0 indicator overlay (EMA, SMA, BB...)
  // instead of staying on the actual main candlestick series. Both the main
  // series (when chartType would be 'line') and an indicator overlay share
  // SeriesConfig['type'] === 'Line', so ChartPane must distinguish them by id
  // (`candles-${chartType}` vs an indicator id like `ema-...`) rather than
  // firing onSeriesReady for every pane-0 Line series it creates. If it
  // doesn't, removing the last-created indicator later leaves mainSeries
  // pointing at a detached series with no price scale — e.g. breaking
  // VolumeProfilePrimitive, which attaches to mainSeries and silently
  // stops rendering.
  it('fires onSeriesReady only for the main candlestick series, not for pane-0 indicator Line series created after it', () => {
    const onSeriesReady = jest.fn();
    const mainSeriesRef: Parameters<typeof ChartPane>[0]['mainSeriesRef'] = { current: null };

    render(
      <ChartPane
        series={[
          { id: 'candles-candle', type: 'Candlestick', data: [] },
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
  // itself IS a Line series (id `candles-line`) sharing a pane with indicator
  // overlays — onSeriesReady must still fire for it, and stay pointed at it
  // rather than the indicator lines created alongside it.
  it('fires onSeriesReady for a Line-type main series (chartType=line) and not for indicator lines around it', () => {
    const onSeriesReady = jest.fn();
    const mainSeriesRef: Parameters<typeof ChartPane>[0]['mainSeriesRef'] = { current: null };

    render(
      <ChartPane
        series={[
          { id: 'candles-line', type: 'Line', data: [] },
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

  // End-to-end regression test for the actual user-visible symptom (not just
  // ChartPane's internal wiring): Volume Profile attaches to whatever
  // mainSeriesRef points at and calls series.priceToCoordinate() to lay out
  // its bars. Before the fix, removing the last-added pane-0 indicator left
  // mainSeriesRef pointing at that now-detached indicator series — its
  // priceToCoordinate would return null, so the profile drew nothing, with
  // no error anywhere. This reproduces exactly that sequence (add EMA-20,
  // then EMA-50 last so it's the one that would have hijacked mainSeries;
  // remove both) and asserts mainSeriesRef stayed on a series that is both
  // still present in the chart's live pane-0 series list and still resolves
  // coordinates — the two facts VolumeProfilePrimitive's draw() depends on.
  it('keeps mainSeriesRef pointed at a live, coordinate-resolving series through an indicator add-then-remove cycle', () => {
    const onSeriesReady = jest.fn();
    const mainSeriesRef: Parameters<typeof ChartPane>[0]['mainSeriesRef'] = { current: null };

    const { rerender } = render(
      <ChartPane
        series={[{ id: 'candles-candle', type: 'Candlestick', data: [] }]}
        onSeriesReady={onSeriesReady}
        mainSeriesRef={mainSeriesRef}
      />,
    );

    rerender(
      <ChartPane
        series={[
          { id: 'candles-candle', type: 'Candlestick', data: [] },
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
        series={[{ id: 'candles-candle', type: 'Candlestick', data: [] }]}
        onSeriesReady={onSeriesReady}
        mainSeriesRef={mainSeriesRef}
      />,
    );

    const chart = (createChart as jest.Mock).mock.results[0].value;
    const pane0Series = chart.panes()[0].getSeries();

    expect(mainSeriesRef.current).not.toBeNull();
    expect(pane0Series).toContain(mainSeriesRef.current);
    expect(mainSeriesRef.current!.priceToCoordinate(100)).not.toBeNull();
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
