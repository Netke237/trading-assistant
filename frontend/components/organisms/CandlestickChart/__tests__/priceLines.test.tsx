import { act, render } from '@testing-library/react';
import { createChart } from 'lightweight-charts';
import { CandlestickChart } from '..';
import { useThemeStore } from '@/lib/theme';

// Enforce the actual live-series lifecycle: removing from a disposed chart throws.
jest.mock('lightweight-charts', () => ({
  ...jest.requireActual('../../../../__mocks__/lightweight-charts.js'),
  LineStyle: {Dashed: 2},
}));
const empty: [] = [];
const original = (createChart as jest.Mock).getMockImplementation()!;
beforeEach(() => {
  (createChart as jest.Mock).mockClear();
  jest.spyOn(window, 'getComputedStyle').mockReturnValue({getPropertyValue: (name: string) => name === '--accent' ? '#abcdef' : ''} as CSSStyleDeclaration);
  useThemeStore.setState({theme: 'dark'});
  (createChart as jest.Mock).mockImplementation((...args: unknown[]) => {
    const chart = original(...args);
    const add = chart.addSeries.getMockImplementation();
    let disposed = false;
    chart.addSeries.mockImplementation((...seriesArgs: unknown[]) => {
      const series = add(...seriesArgs);
      series.createPriceLine.mockImplementation((options: unknown) => ({options}));
      series.removePriceLine = jest.fn(() => {if (disposed) throw new Error('disposed chart');});
      return series;
    });
    chart.remove.mockImplementation(() => {disposed = true;});
    return chart;
  });
});

test('finite lines resolve token color and are replaced/removed before chart disposal', () => {
  const view = render(<CandlestickChart data={empty} defaultIndicators={[]} priceLines={[{price: 0, title: 'Scan low'}, {price: Infinity, title: 'invalid'}]}/>);
  const chart = (createChart as jest.Mock).mock.results[0].value;
  const series = chart.addSeries.mock.results[0].value;
  expect(series.createPriceLine).toHaveBeenCalledTimes(1);
  expect(series.createPriceLine).toHaveBeenCalledWith(expect.objectContaining({price: 0, title: 'Scan low', color: '#abcdef'}));
  const first = series.createPriceLine.mock.results[0].value;
  view.rerender(<CandlestickChart data={empty} defaultIndicators={[]} priceLines={[{price: 50, title: 'Scan level'}]}/>);
  expect(series.removePriceLine).toHaveBeenCalledWith(first);
  expect(series.createPriceLine).toHaveBeenCalledTimes(2);
  view.unmount();
  expect(series.removePriceLine).toHaveBeenCalledTimes(2);
  expect(series.removePriceLine.mock.invocationCallOrder[1]).toBeLessThan(chart.remove.mock.invocationCallOrder[0]);
});
test('theme rebuild cleans the old series then applies lines to the new series', () => {
  const view = render(<CandlestickChart data={empty} defaultIndicators={[]} priceLines={[{price: 75, title: 'Scan swing high'}]}/>);
  const old = (createChart as jest.Mock).mock.results[0].value;
  const oldSeries = old.addSeries.mock.results[0].value;
  act(() => useThemeStore.setState({theme: 'light'}));
  expect(oldSeries.removePriceLine).toHaveBeenCalledTimes(1);
  expect(oldSeries.removePriceLine.mock.invocationCallOrder[0]).toBeLessThan(old.remove.mock.invocationCallOrder[0]);
  const latest = (createChart as jest.Mock).mock.results.at(-1)!.value;
  expect(latest.addSeries.mock.results[0].value.createPriceLine).toHaveBeenCalledWith(expect.objectContaining({price: 75}));
  view.unmount();
});
test('empty/omitted priceLines preserve existing callers and equivalent literals do not churn lines', () => {
  const view = render(<CandlestickChart data={empty} defaultIndicators={[]}/>);
  const chart = (createChart as jest.Mock).mock.results[0].value;
  const series = chart.addSeries.mock.results[0].value;
  expect(series.createPriceLine).not.toHaveBeenCalled();
  view.rerender(<CandlestickChart data={empty} defaultIndicators={[]} priceLines={[{price: 10, title: 'Scan low'}]}/>);
  view.rerender(<CandlestickChart data={empty} defaultIndicators={[]} priceLines={[{price: 10, title: 'Scan low'}]}/>);
  expect(series.createPriceLine).toHaveBeenCalledTimes(1);
  view.rerender(<CandlestickChart data={empty} defaultIndicators={[]} priceLines={[]}/>);
  expect(series.removePriceLine).toHaveBeenCalledTimes(1);
  expect(createChart).toHaveBeenCalledTimes(1);
});
