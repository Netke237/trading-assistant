// Minimal fake of the lightweight-charts v5 surface ChartPane/CandlestickChart use.
// createChart is a jest.fn so tests can inspect the options it was called with
// (mock.calls) and the fake chart instance it returned (mock.results).

const CandlestickSeries = { __brand: 'CandlestickSeries' };
const BarSeries = { __brand: 'BarSeries' };
const LineSeries = { __brand: 'LineSeries' };
const HistogramSeries = { __brand: 'HistogramSeries' };

// priceToCoordinate returns a fixed non-null coordinate while the series is
// live, and null once removed — mirroring the real library (a series with no
// price scale, because it's been detached from every pane, can't resolve a
// coordinate). This is what let a real-browser repro of the volume-profile
// bug prove mainSeries had been silently hijacked to a since-removed
// indicator series: VolumeProfilePrimitive's draw() calls priceToCoordinate
// on whatever series it was attached to, and got null for every bin.
function makeSeriesApi(seriesOptions) {
  const api = {
    __options: seriesOptions,
    __removed: false,
    setData: jest.fn(),
    applyOptions: jest.fn(),
    createPriceLine: jest.fn(),
    priceToCoordinate: jest.fn(() => (api.__removed ? null : 100)),
  };
  return api;
}

// Backed by a live array (not a fixed jest.fn(() => [])) so a test can
// render, add/remove series across a rerender, and then assert on which
// series a given pane *actually* still holds — the mechanism the real
// volume-profile bug hinged on (mainSeries pointing at a series no pane
// holds any more). A static empty-array stub can't distinguish that from
// the correct case.
function makePaneApi(seriesList) {
  return {
    setHeight: jest.fn(),
    getSeries: jest.fn(() => seriesList),
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
  const paneSeriesLists = [[]]; // paneSeriesLists[i] backs panes[i].getSeries()
  const panes = [makePaneApi(paneSeriesLists[0])];
  let nextPaneIndex = 1; // pane 0 is the main chart pane, never created via addPane

  function ensurePane(index) {
    while (paneSeriesLists.length <= index) paneSeriesLists.push([]);
    while (panes.length <= index) panes.push(makePaneApi(paneSeriesLists[panes.length]));
  }

  return {
    __options: options,
    addSeries: jest.fn((_type, seriesOptions, paneIndex = 0) => {
      ensurePane(paneIndex);
      const s = makeSeriesApi(seriesOptions);
      paneSeriesLists[paneIndex].push(s);
      return s;
    }),
    addPane: jest.fn(() => makeIndicatorPaneApi(nextPaneIndex++)),
    removeSeries: jest.fn((s) => {
      s.__removed = true;
      for (const list of paneSeriesLists) {
        const i = list.indexOf(s);
        if (i !== -1) list.splice(i, 1);
      }
    }),
    removePane: jest.fn((index) => {
      // Real lightweight-charts destroys a pane's series along with the
      // pane itself — mark them removed too, not just drop the pane's
      // tracking arrays, so a series held by a removed-but-nonempty pane
      // can't be mistaken for still-live by a test (ChartPane itself only
      // ever calls removePane on an already-empty pane, but the mock
      // shouldn't rely on that to stay faithful to the real API's contract).
      for (const s of paneSeriesLists[index] ?? []) s.__removed = true;
      paneSeriesLists.splice(index, 1);
      panes.splice(index, 1);
    }),
    panes: jest.fn(() => panes),
    subscribeCrosshairMove: jest.fn(),
    applyOptions: jest.fn(),
    remove: jest.fn(),
    timeScale: jest.fn(() => ({ fitContent: jest.fn() })),
  };
});

module.exports = { createChart, CandlestickSeries, BarSeries, LineSeries, HistogramSeries };
