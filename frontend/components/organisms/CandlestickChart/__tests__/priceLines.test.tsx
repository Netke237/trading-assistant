import { render } from '@testing-library/react';
import { createChart } from 'lightweight-charts';
import { CandlestickChart } from '@/components/organisms/CandlestickChart';
import type { Candle } from '@/types/chart';

/*
 * Optional `priceLines` prop (STOCK-PRES-P5-PREBREAKOUT T1): one horizontal
 * price line per entry on the candle series, removed on change/unmount.
 *
 * The shared lightweight-charts mock's createPriceLine returns undefined, so a
 * "the OLD handle was removed" assertion could not tell one line from another.
 * This file wraps the mock's createChart (test-local, restored afterwards) so
 * each candle-series createPriceLine call returns a distinct handle object.
 */

const mockedCreateChart = createChart as jest.Mock;
const baseCreateChart = mockedCreateChart.getMockImplementation()!;

function mockComputedStyle(tokens: Record<string, string> = {}) {
  jest.spyOn(window, 'getComputedStyle').mockReturnValue({
    getPropertyValue: (name: string) => tokens[name] ?? '',
  } as unknown as CSSStyleDeclaration);
}

const data: Candle[] = [
  { time: '2026-01-05', open: 100, high: 101, low: 99, close: 100.5, volume: 1000 },
  { time: '2026-01-06', open: 101, high: 102, low: 100, close: 101.5, volume: 900 },
];

function candleSeries() {
  const chart = mockedCreateChart.mock.results[0].value;
  return chart.addSeries.mock.results[0].value;
}

describe('CandlestickChart — priceLines', () => {
  beforeEach(() => {
    mockedCreateChart.mockClear();
    mockComputedStyle({ '--accent': '#4C8DFF' });
    mockedCreateChart.mockImplementation((...args: unknown[]) => {
      const chart = baseCreateChart(...args);
      const baseAddSeries = chart.addSeries.getMockImplementation();
      chart.addSeries.mockImplementation((...a: unknown[]) => {
        const s = baseAddSeries(...a);
        s.createPriceLine.mockImplementation((opts: unknown) => ({ __priceLine: opts }));
        return s;
      });
      return chart;
    });
  });

  afterEach(() => {
    mockedCreateChart.mockImplementation(baseCreateChart);
    jest.restoreAllMocks();
  });

  it('draws one price line on the candle series per entry', () => {
    render(
      <CandlestickChart
        data={data}
        showToggles={false}
        defaultIndicators={[]}
        priceLines={[{ price: 201.4, title: 'Swing high' }]}
      />,
    );

    const candle = candleSeries();
    expect(candle.createPriceLine).toHaveBeenCalledTimes(1);
    expect(candle.createPriceLine).toHaveBeenCalledWith(
      expect.objectContaining({ price: 201.4, title: 'Swing high' }),
    );
  });

  it('does not call createPriceLine when the prop is absent', () => {
    render(<CandlestickChart data={data} showToggles={false} defaultIndicators={[]} />);

    expect(candleSeries().createPriceLine).not.toHaveBeenCalled();
  });

  it('does not call createPriceLine when the prop is an empty array', () => {
    render(
      <CandlestickChart data={data} showToggles={false} defaultIndicators={[]} priceLines={[]} />,
    );

    expect(candleSeries().createPriceLine).not.toHaveBeenCalled();
  });

  it('skips a non-finite price and still draws a sibling finite entry', () => {
    expect(() =>
      render(
        <CandlestickChart
          data={data}
          showToggles={false}
          defaultIndicators={[]}
          priceLines={[
            { price: NaN, title: 'Broken' },
            { price: 150.25, title: '61.8%' },
          ]}
        />,
      ),
    ).not.toThrow();

    const candle = candleSeries();
    expect(candle.createPriceLine).toHaveBeenCalledTimes(1);
    expect(candle.createPriceLine).toHaveBeenCalledWith(
      expect.objectContaining({ price: 150.25, title: '61.8%' }),
    );
  });

  it('on a re-render with different priceLines removes the old line and creates the new one', () => {
    const { rerender } = render(
      <CandlestickChart
        data={data}
        showToggles={false}
        defaultIndicators={[]}
        priceLines={[{ price: 201.4, title: 'Swing high' }]}
      />,
    );

    const candle = candleSeries();
    const oldHandle = candle.createPriceLine.mock.results[0].value;
    expect(candle.removePriceLine).not.toHaveBeenCalled();

    rerender(
      <CandlestickChart
        data={data}
        showToggles={false}
        defaultIndicators={[]}
        priceLines={[{ price: 199.8, title: 'Swing high' }]}
      />,
    );

    expect(candle.removePriceLine).toHaveBeenCalledTimes(1);
    expect(candle.removePriceLine).toHaveBeenCalledWith(oldHandle);
    expect(candle.createPriceLine).toHaveBeenCalledTimes(2);
    expect(candle.createPriceLine).toHaveBeenLastCalledWith(
      expect.objectContaining({ price: 199.8, title: 'Swing high' }),
    );
    expect(candle.createPriceLine.mock.results[1].value).not.toBe(oldHandle);
  });
});
