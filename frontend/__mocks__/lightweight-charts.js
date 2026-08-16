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
