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
});
