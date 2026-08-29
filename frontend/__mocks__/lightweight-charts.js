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
    createPriceLine: jest.fn(),
  };
}

function makePaneApi() {
  return {
    setHeight: jest.fn(),
    getSeries: jest.fn(() => []),
  };
}

// v5 sub-pane API used by IndicatorPanel (chart.addPane() → pane.addSeries()),
// distinct from the plain makePaneApi() above used for chart.panes()[0].
function makeIndicatorPaneApi(index) {
  return {
    setStretchFactor: jest.fn(),
    paneIndex: jest.fn(() => index),
    addSeries: jest.fn((_type, seriesOptions) => makeSeriesApi(seriesOptions)),
  };
}

const createChart = jest.fn((_container, options) => {
  const panes = [makePaneApi()];
  let nextPaneIndex = 1; // pane 0 is the main chart pane, never created via addPane
  return {
    __options: options,
    addSeries: jest.fn((_type, seriesOptions) => makeSeriesApi(seriesOptions)),
    addPane: jest.fn(() => makeIndicatorPaneApi(nextPaneIndex++)),
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
