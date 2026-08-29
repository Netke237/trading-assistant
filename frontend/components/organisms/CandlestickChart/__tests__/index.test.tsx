import { render } from '@testing-library/react';
import { createChart } from 'lightweight-charts';
import { CandlestickChart } from '@/components/organisms/CandlestickChart';
import type { Candle } from '@/types/chart';

function mockComputedStyle(tokens: Record<string, string> = {}) {
  jest.spyOn(window, 'getComputedStyle').mockReturnValue({
    getPropertyValue: (name: string) => tokens[name] ?? '',
  } as unknown as CSSStyleDeclaration);
}

describe('CandlestickChart — malformed bars', () => {
  beforeEach(() => {
    (createChart as jest.Mock).mockClear();
    mockComputedStyle();
  });

  // Regression for the "Candlestick series item data value of open must be a
  // number, got=object, value=null" crash: a bad upstream OHLCV bar (NaN,
  // rounds-tripped through JSON as null) must be dropped before setData, not
  // passed through and crash the whole chart.
  it('drops non-finite OHLC bars before calling setData, keeping the valid ones', () => {
    const data = [
      { time: '2026-01-05', open: 100, high: 101, low: 99, close: 100.5, volume: 1000 },
      { time: '2026-01-06', open: null, high: null, low: null, close: null, volume: 500 },
      { time: '2026-01-07', open: 102, high: 103, low: 101, close: 102.5, volume: 1200 },
    ] as unknown as Candle[];

    render(<CandlestickChart data={data} showToggles={false} defaultIndicators={[]} />);

    const chart = (createChart as jest.Mock).mock.results[0].value;
    const candleSeries = chart.addSeries.mock.results[0].value;

    expect(candleSeries.setData).toHaveBeenCalledWith([
      { time: '2026-01-05', open: 100, high: 101, low: 99, close: 100.5 },
      { time: '2026-01-07', open: 102, high: 103, low: 101, close: 102.5 },
    ]);
  });

  it('still renders (and calls setData with everything) when all bars are valid', () => {
    const data: Candle[] = [
      { time: '2026-01-05', open: 100, high: 101, low: 99, close: 100.5, volume: 1000 },
      { time: '2026-01-06', open: 101, high: 102, low: 100, close: 101.5, volume: 900 },
    ];

    render(<CandlestickChart data={data} showToggles={false} defaultIndicators={[]} />);

    const chart = (createChart as jest.Mock).mock.results[0].value;
    const candleSeries = chart.addSeries.mock.results[0].value;
    expect(candleSeries.setData).toHaveBeenCalledWith([
      { time: '2026-01-05', open: 100, high: 101, low: 99, close: 100.5 },
      { time: '2026-01-06', open: 101, high: 102, low: 100, close: 101.5 },
    ]);
  });

  // The two tests above render with defaultIndicators={[]}, which never
  // exercises IndicatorPanel's own setData() calls (volume/RSI/MACD) — a bad
  // bar reaching those would crash the chart just as surely as reaching the
  // candle series. This test uses the component's real default
  // (defaultIndicators=['volume','rsi']) and asserts on the actual data each
  // indicator series' own setData() received, not just that render() didn't
  // throw -- the jest mock's setData() never validates its input (it's a
  // bare jest.fn()), so a not-yet-fixed component with a NaN bar reaching
  // calculateRSI/calculateVolume would render "successfully" in this mock
  // even though the real lightweight-charts library would crash. Only
  // inspecting the actual values setData was called with can catch that.
  it('keeps the volume/RSI indicator panes in sync with the same filtered bars, under default props', () => {
    // 16 bars, one bad (time: 2) — 15 clean bars is exactly enough for RSI's
    // default 14-period (candles.length >= period + 1) to produce output.
    // Gains-only closes (each +1 after the first) make RSI's avgLoss === 0,
    // which calculateRSI special-cases to exactly 100 — a deterministic
    // expected value with no floating-point rounding to account for.
    const data = [
      { time: 1, open: 100, high: 101, low: 99, close: 100.5, volume: 1000 },
      { time: 2, open: null, high: null, low: null, close: null, volume: null },
      { time: 3, open: 102, high: 103, low: 101, close: 102.5, volume: 1200 },
      { time: 4, open: 103, high: 104, low: 102, close: 103.5, volume: 1300 },
      { time: 5, open: 104, high: 105, low: 103, close: 104.5, volume: 1400 },
      { time: 6, open: 105, high: 106, low: 104, close: 105.5, volume: 1500 },
      { time: 7, open: 106, high: 107, low: 105, close: 106.5, volume: 1600 },
      { time: 8, open: 107, high: 108, low: 106, close: 107.5, volume: 1700 },
      { time: 9, open: 108, high: 109, low: 107, close: 108.5, volume: 1800 },
      { time: 10, open: 109, high: 110, low: 108, close: 109.5, volume: 1900 },
      { time: 11, open: 110, high: 111, low: 109, close: 110.5, volume: 2000 },
      { time: 12, open: 111, high: 112, low: 110, close: 111.5, volume: 2100 },
      { time: 13, open: 112, high: 113, low: 111, close: 112.5, volume: 2200 },
      { time: 14, open: 113, high: 114, low: 112, close: 113.5, volume: 2300 },
      { time: 15, open: 114, high: 115, low: 113, close: 114.5, volume: 2400 },
      { time: 16, open: 115, high: 116, low: 114, close: 115.5, volume: 2500 },
    ] as unknown as Candle[];

    render(<CandlestickChart data={data} />);

    const chart = (createChart as jest.Mock).mock.results[0].value;

    // activeIndicators defaults to ['volume', 'rsi'] (INDICATOR_ORDER order),
    // so IndicatorPanel mounts volume's pane first, RSI's second.
    const volumePane = chart.addPane.mock.results[0].value;
    const rsiPane = chart.addPane.mock.results[1].value;
    const volumeSeries = volumePane.addSeries.mock.results[0].value;
    const rsiSeries = rsiPane.addSeries.mock.results[0].value;

    // Volume: one point per clean bar (15, not 16), all finite, bad bar's
    // time (2) absent -- would include a null-value point at time 2 if
    // indicatorData were still built from raw `data`.
    const volumeCalls = volumeSeries.setData.mock.calls[0][0] as Array<{ time: number; value: number }>;
    expect(volumeCalls).toHaveLength(15);
    expect(volumeCalls.every((p) => Number.isFinite(p.value))).toBe(true);
    expect(volumeCalls.map((p) => p.time)).not.toContain(2);
    expect(volumeCalls[0]).toMatchObject({ time: 1, value: 1000 });
    expect(volumeCalls[14]).toMatchObject({ time: 16, value: 2500 });

    // RSI: exactly one output point (15 clean closes - 14 period = 1),
    // value === 100 (gains-only closes => avgLoss 0 special case). Reverting
    // the fix (raw `data` instead of cleanData) would let the null close at
    // time 2 poison the gain/loss recurrence with NaN instead.
    const rsiCalls = rsiSeries.setData.mock.calls[0][0] as Array<{ time: number; value: number }>;
    expect(rsiCalls).toHaveLength(1);
    expect(rsiCalls[0]).toEqual({ time: 16, value: 100 });
  });
});
