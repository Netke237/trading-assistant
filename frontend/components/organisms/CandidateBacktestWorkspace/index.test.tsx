import React from 'react';
import { render, screen, fireEvent, act, within } from '@testing-library/react';
import CandidateBacktestWorkspace from './index';
import type { BacktestArtifact } from '@/types/backtest';
import { useThemeStore } from '@/lib/theme';
const mockCharts: any[] = [];
const mockMarkers: any[] = [];
jest.mock('lightweight-charts', () => ({
 CandlestickSeries: 'candles', LineSeries: 'line', BarSeries: 'bars',
 createSeriesMarkers: jest.fn((series: any, points: any) => {const m = {series, initial: points, detach: jest.fn(), setMarkers: jest.fn()}; mockMarkers.push(m); return m;}),
 createChart: jest.fn((container: HTMLElement, options: any) => {
  const series: any[] = [];
  const scale = {subscribeVisibleTimeRangeChange: jest.fn(), unsubscribeVisibleTimeRangeChange: jest.fn(), setVisibleRange: jest.fn(), getVisibleRange: jest.fn(() => null), getVisibleLogicalRange: jest.fn(() => ({from:1,to:2})), setVisibleLogicalRange: jest.fn(), fitContent: jest.fn()};
  const chart = {container, options, series, scale, addSeries: jest.fn((type: string, opts: any) => {const s = {type, opts, setData: jest.fn(), applyOptions: jest.fn()}; series.push(s); return s;}), timeScale: () => scale, applyOptions: jest.fn(), remove: jest.fn(), removeSeries: jest.fn((s: any) => {s.removed = true;}), subscribeClick: jest.fn(), unsubscribeClick: jest.fn(), subscribeCrosshairMove: jest.fn(), unsubscribeCrosshairMove: jest.fn(), setCrosshairPosition: jest.fn(), clearCrosshairPosition: jest.fn()};
  mockCharts.push(chart); return chart;
 }),
}));
/** Panes are addressed by the labelled container each chart was created in, never by creation order. */
const pane = (label: string) => {
 const found = mockCharts.filter(c => c.container.getAttribute('aria-label') === label);
 if (found.length !== 1) throw new Error(`expected one ${label} chart, found ${found.length}`);
 return found[0];
};
const PRICE = 'Historical candles', PERFORMANCE = 'Indexed equity comparison', DRAWDOWN = 'Sampled strategy drawdown';
const lastData = (series: any) => series.setData.mock.calls.at(-1)[0];
const artifact = {
 artifact_id: 'original-a', provenance: 'original', created_at: 1700000000,
 identity: {symbol: 'AAPL', strategy: 'pullback_ema', direction: 'Bearish', horizon: 'Swing', interval: '15m', input_hash: 'hash', scan_id: 'scan', bars_basis_version: 'basis', engine_contract_version: 'v1'},
 detail: {status: 'success', candles: [{time: 1700000000, open: 40, high: 45, low: 35, close: 42, volume: 10}], equity: [{time: 1700000000, equity: 100000, strategy_index: 100, benchmark_index: 100}], trades: [{id:'a', direction:'Bearish', entry_time:1700000000, exit_time:1700000000, entry_price:43.125, exit_price:39.875, net_return_pct:7.123, exit_reason:'unknown', size:-2, commission:1.25}], open_positions: [], summary: {n_trades: 1, total_return_pct: 0}, configuration: {commission: 0.001, initial_cash:100000, sizing:'equity', order_size:0.99}, effective_params:{ema_period:20}, time_basis:'UTC epoch seconds', initial_equity:100000},
} as unknown as BacktestArtifact;
const at = (iso: string) => Date.parse(iso) / 1000;
const T1 = at('2023-01-03T00:00:00Z'), T2 = at('2024-06-03T00:00:00Z'), T3 = at('2024-09-03T00:00:00Z'), T4 = at('2025-01-06T00:00:00Z');
/** First equity sample is below starting equity; candles (T1,T3) and equity (T1,T2,T4) have different timestamps. */
const timed = {
 ...artifact, artifact_id: 'timed',
 detail: {...artifact.detail, initial_equity: 1000, trades: [],
  candles: [{time:T1,open:20,high:21,low:19,close:20,volume:2},{time:T3,open:22,high:23,low:21,close:22,volume:2}],
  equity: [{time:T1,equity:850,strategy_index:85,benchmark_index:101},{time:T2,equity:1200,strategy_index:120,benchmark_index:105},{time:T4,equity:1080,strategy_index:108,benchmark_index:110.25}],
  summary: {n_trades: 4, win_rate: 0.5, total_return_pct: 7.123, max_drawdown_pct: -16.5}},
} as unknown as BacktestArtifact;
const withEquity = (equity: any[], summary: any = {}) => ({...timed, detail: {...timed.detail, equity, summary: {...timed.detail.summary, ...summary}}}) as unknown as BacktestArtifact;
const cards = () => screen.getByLabelText('Full-period performance summary').textContent;
let fetchSpy: jest.Mock;
beforeEach(() => {
 mockCharts.length=0; mockMarkers.length=0; global.ResizeObserver = class {observe(){} disconnect(){} unobserve(){}} as any;
 fetchSpy = jest.fn(); (global as any).fetch = fetchSpy;
});
afterEach(() => expect(fetchSpy).not.toHaveBeenCalled());
it('renders separate price/equity panes and keyboard-accessible exact trade fills', () => {
 render(<CandidateBacktestWorkspace artifact={artifact}/>);
 expect(screen.getByLabelText('Historical candles')).toBeInTheDocument();
 expect(screen.getByLabelText('Indexed equity comparison')).toBeInTheDocument();
 fireEvent.click(screen.getByRole('button', {name:/Inspect trade a/}));
 expect(screen.getByText('43.125')).toBeInTheDocument();
 expect(screen.getByText('39.875')).toBeInTheDocument();
 expect(within(screen.getByLabelText('Trade inspector')).getByText('Unknown (not recorded by engine)')).toBeInTheDocument();
 expect(screen.getByText(/Long buy-and-hold \(gross; excludes fees\)/)).toBeInTheDocument();
 expect(screen.getByText(/ema_period/)).toBeInTheDocument();
});
it('retains real zero-trade curves and discloses open equity without a fabricated exit', () => {
 render(<CandidateBacktestWorkspace artifact={{...artifact,detail:{...artifact.detail,trades:[],open_positions:[{id:'o',direction:'Bullish',entry_time:1700000000,entry_price:40.5,size:3,unrealized_pnl:4}],summary:{...artifact.detail.summary,n_trades:0}}}}/>);
 expect(screen.getByText(/Successful result: zero closed trades/)).toBeInTheDocument();
 expect(screen.getByText(/mark-to-market/)).toBeInTheDocument();
 expect(screen.getByText(/40.5/)).toBeInTheDocument();
 // Return % is the recorded index minus 100; Index 100 is the raw recorded index.
 expect(pane(PERFORMANCE).series[0].setData).toHaveBeenLastCalledWith([{time:1700000000,value:0}]);
 fireEvent.click(screen.getByRole('button',{name:'Index 100'}));
 expect(pane(PERFORMANCE).series[0].setData).toHaveBeenLastCalledWith([{time:1700000000,value:100}]);
});
it('guards synchronized ranges/crosshairs and cleans subscriptions/markers on unmount', () => {
 const {unmount}=render(<CandidateBacktestWorkspace artifact={artifact}/>);
 const price=pane(PRICE),equity=pane(PERFORMANCE);
 fireEvent.pointerEnter(screen.getByLabelText(PRICE));
 const sync=price.scale.subscribeVisibleTimeRangeChange.mock.calls[0][0];
 equity.scale.setVisibleRange.mockClear();price.scale.setVisibleRange.mockClear();
 equity.scale.setVisibleRange.mockImplementation((range:any) => equity.scale.subscribeVisibleTimeRangeChange.mock.calls[0][0](range));
 sync({from:1700000000,to:1700000000});
 expect(equity.scale.setVisibleRange).toHaveBeenCalledTimes(1);
 expect(equity.scale.setVisibleRange).toHaveBeenCalledWith({from:1700000000,to:1700000000});
 // A queued callback from the following pane cannot bounce back.
 equity.scale.subscribeVisibleTimeRangeChange.mock.calls[0][0]({from:1700000000,to:1700000000});
 expect(price.scale.setVisibleRange).not.toHaveBeenCalled();
 const cross=price.subscribeCrosshairMove.mock.calls[0][0];
 act(()=>cross({time:1700000000}));
 expect(equity.setCrosshairPosition).toHaveBeenCalledWith(0,1700000000,equity.series[0]);
 fireEvent.click(screen.getByRole('button',{name:'Index 100'}));
 act(()=>{cross({time:undefined});cross({time:1700000000});});
 expect(equity.setCrosshairPosition).toHaveBeenLastCalledWith(100,1700000000,equity.series[0]);
 act(()=>useThemeStore.getState().toggle());
 expect(price.applyOptions).toHaveBeenCalled();
 unmount();
 for(const chart of mockCharts){
  expect(chart.unsubscribeCrosshairMove).toHaveBeenCalledWith(chart.subscribeCrosshairMove.mock.calls[0][0]);
  expect(chart.scale.unsubscribeVisibleTimeRangeChange).toHaveBeenCalledWith(chart.scale.subscribeVisibleTimeRangeChange.mock.calls[0][0]);
  expect(chart.remove).toHaveBeenCalled();
 }
 expect(price.unsubscribeClick).toHaveBeenCalled();
});

it('resets incompatible symbol or interval without making a new run', () => {
 render(<CandidateBacktestWorkspace artifact={artifact}/>);
 const price=pane(PRICE);
 fireEvent.change(screen.getByLabelText('Evidence interval'),{target:{value:'1d'}});
 expect(screen.getByText(/Original evidence hidden/)).toBeInTheDocument();
 expect(screen.queryByLabelText('Historical candles')).not.toBeInTheDocument();
 expect(price.remove).toHaveBeenCalled();
});


it('labels the distinct fresh result and keeps fresh provenance after interval changes', () => {
 render(<CandidateBacktestWorkspace artifact={{...artifact,artifact_id:'fresh-b',provenance:'fresh'}}/>);
 expect(screen.getByRole('heading',{name:'AAPL — Fresh backtest (separate result)'})).toBeInTheDocument();
 expect(screen.getByLabelText('Fresh backtest evidence')).toBeInTheDocument();
 fireEvent.change(screen.getByLabelText('Evidence interval'),{target:{value:'1d'}});
 expect(screen.getByText(/Fresh evidence hidden/)).toBeInTheDocument();
});

it('keeps the run identity below the page title and states the calculation basis from recorded values', () => {
 render(<CandidateBacktestWorkspace artifact={timed}/>);
 // The page header owns the single h1; the report keeps its own labelled run identity.
 expect(screen.queryByRole('heading', {level: 1})).not.toBeInTheDocument();
 expect(screen.getByRole('heading', {level: 2, name: 'AAPL — Original backtest'})).toBeInTheDocument();
 const basis = screen.getByText('Calculation basis & comparison limits').closest('details') as HTMLElement;
 expect(basis).toHaveTextContent('Strategy equity is the recorded engine equity, including the recorded unrealized value of open positions and the recorded strategy commission of 0.001. It is not a cumulative sum of closed-trade returns.');
 expect(basis).toHaveTextContent('Buy-and-hold is the recorded long benchmark of the same underlying, gross and excluding fees, for either strategy direction.');
 expect(basis).toHaveTextContent('No dividend, reinvestment, cash-interest or allocation assumption is added by this view, and no currency was recorded.');
 expect(basis).toHaveTextContent('Sampled drawdown is 100 × (equity ÷ running peak − 1) over every recorded equity sample, with the peak starting at the recorded initial equity of 1000.');
 expect(basis).toHaveTextContent('The engine max drawdown of -16.5% is the engine\'s own metric and is shown unchanged.');
 expect(basis).toHaveTextContent('Last year, All history and trade selection change only the visible dates, never the test period, baseline or starting capital.');
 // The complete provenance stays in its own disclosure.
 expect(screen.getByText('Recorded configuration and provenance')).toBeInTheDocument();
});

describe('performance comparison', () => {
 it('states the comparison from final recorded indices and keeps the engine return separately disclosed', () => {
  render(<CandidateBacktestWorkspace artifact={timed}/>);
  expect(screen.getByText('Long buy-and-hold finished ahead of recorded strategy equity.')).toBeInTheDocument();
  expect(screen.getByText(/Recorded strategy equity returned \+8\.00%; long buy-and-hold returned \+10\.25%; difference -2\.25 percentage points over the full recorded period\./)).toBeInTheDocument();
  const summary = cards();
  expect(summary).toContain('Strategy return (engine)+7.12%');
  expect(summary).toContain('Buy & hold return+10.25%');
  expect(summary).toContain('Strategy minus holding-2.25');
  expect(summary).toContain('Percentage points of equity-index return');
  expect(summary).toContain('Winning closed trades50.00%');
  expect(summary).toContain('Closed trades4');
  expect(summary).not.toMatch(/profit factor/i);
  expect(screen.getByText(/Engine total return \(summary definition\): \+7\.12%\. Indexed ending change of recorded strategy equity: \+8\.00%\./)).toBeInTheDocument();
  expect(screen.getByText(/These differ/)).toBeInTheDocument();
 });
 it('discloses an engine/index difference that only exists beyond the displayed decimals without calling it equal', () => {
  render(<CandidateBacktestWorkspace artifact={withEquity([{time:T1,equity:1000,strategy_index:80.36103999999999,benchmark_index:105}],{total_return_pct:-19.638960000000004})}/>);
  expect(screen.getByText(/Engine total return \(summary definition\): -19\.64%\. Indexed ending change of recorded strategy equity: -19\.64%\. These differ only beyond the two displayed decimals\./)).toBeInTheDocument();
  expect(screen.queryByText(/These differ:/)).not.toBeInTheDocument();
 });
 it('handles strategy ahead, level and missing results truthfully', () => {
  const {unmount}=render(<CandidateBacktestWorkspace artifact={withEquity([{time:T1,equity:1000,strategy_index:112,benchmark_index:104}])}/>);
  expect(screen.getByText('Recorded strategy equity finished ahead of long buy-and-hold.')).toBeInTheDocument();
  expect(cards()).toContain('Strategy minus holding+8.00');
  unmount();
  const level=render(<CandidateBacktestWorkspace artifact={withEquity([{time:T1,equity:1000,strategy_index:100,benchmark_index:100}],{total_return_pct:0})}/>);
  expect(screen.getByText('Recorded strategy equity and long buy-and-hold finished level.')).toBeInTheDocument();
  expect(screen.queryByText(/These differ/)).not.toBeInTheDocument();
  level.unmount();
  render(<CandidateBacktestWorkspace artifact={withEquity([])}/>);
  expect(screen.getByText('Comparison unavailable.')).toBeInTheDocument();
  expect(cards()).toContain('Buy & hold returnUnavailable');
  expect(cards()).toContain('Strategy minus holdingUnavailable');
  expect(cards()).toContain('Strategy return (engine)+7.12%');
  expect(screen.getByText(/Indexed equity is unavailable/)).toBeInTheDocument();
 });
 it('shows final legend values by default and exact hovered values without nearest-session substitution', () => {
  render(<CandidateBacktestWorkspace artifact={timed}/>);
  expect(screen.getByRole('checkbox',{name:'Strategy equity +8.00%'})).toBeChecked();
  expect(screen.getByRole('checkbox',{name:'Long buy-and-hold (gross; excludes fees) +10.25%'})).toBeChecked();
  expect(screen.getByText(`Period end · ${new Date(T4*1000).toISOString()}`)).toBeInTheDocument();
  const price=pane(PRICE),perf=pane(PERFORMANCE),drawdown=pane(DRAWDOWN);
  fireEvent.pointerEnter(screen.getByLabelText(PERFORMANCE));
  act(()=>perf.subscribeCrosshairMove.mock.calls[0][0]({time:T2}));
  expect(screen.getByRole('checkbox',{name:'Strategy equity +20.00%'})).toBeInTheDocument();
  expect(screen.getByRole('checkbox',{name:'Long buy-and-hold (gross; excludes fees) +5.00%'})).toBeInTheDocument();
  expect(screen.getByText(new Date(T2*1000).toISOString())).toBeInTheDocument();
  expect(price.clearCrosshairPosition).toHaveBeenCalled();
  expect(price.setCrosshairPosition).not.toHaveBeenCalled();
  expect(drawdown.setCrosshairPosition).toHaveBeenCalledWith(0,T2,drawdown.series[0]);
  fireEvent.pointerLeave(screen.getByLabelText(PERFORMANCE));
  fireEvent.pointerEnter(screen.getByLabelText(PRICE));
  perf.clearCrosshairPosition.mockClear();
  act(()=>price.subscribeCrosshairMove.mock.calls[0][0]({time:T3}));
  expect(perf.clearCrosshairPosition).toHaveBeenCalled();
  expect(screen.getByRole('checkbox',{name:'Strategy equity Unavailable'})).toBeInTheDocument();
  expect(screen.getByText(`${new Date(T3*1000).toISOString()} · no recorded equity sample`)).toBeInTheDocument();
  fireEvent.pointerLeave(screen.getByLabelText(PRICE));
  expect(screen.getByRole('checkbox',{name:'Strategy equity +8.00%'})).toBeInTheDocument();
 });
 it('switches Return % and Index 100 by subtracting 100 only, without rebasing or recreating panes', () => {
  render(<CandidateBacktestWorkspace artifact={timed}/>);
  const perf=pane(PERFORMANCE);
  expect(screen.getByRole('button',{name:'Return %'})).toHaveAttribute('aria-pressed','true');
  expect(lastData(perf.series[0])).toEqual([{time:T1,value:-15},{time:T2,value:20},{time:T4,value:8}]);
  expect(lastData(perf.series[1])).toEqual([{time:T1,value:1},{time:T2,value:5},{time:T4,value:10.25}]);
  expect(perf.series[0].opts.priceScaleId).toBe(perf.series[1].opts.priceScaleId);
  fireEvent.click(screen.getByRole('button',{name:'Index 100'}));
  expect(lastData(perf.series[0])).toEqual([{time:T1,value:85},{time:T2,value:120},{time:T4,value:108}]);
  expect(lastData(perf.series[1])).toEqual([{time:T1,value:101},{time:T2,value:105},{time:T4,value:110.25}]);
  expect(perf.scale.setVisibleLogicalRange).toHaveBeenLastCalledWith({from:1,to:2});
  expect(screen.getByRole('checkbox',{name:'Strategy equity 108.00'})).toBeInTheDocument();
  expect(screen.getByText(/Equity index · recorded baseline is 100/)).toBeInTheDocument();
  // Zooming to the last year never rebases: values remain the recorded index.
  fireEvent.click(screen.getByRole('button',{name:'Last year'}));
  expect(lastData(perf.series[0])).toEqual([{time:T1,value:85},{time:T2,value:120},{time:T4,value:108}]);
  expect(mockCharts).toHaveLength(3);
 });
 it('hides series individually and guides when both are hidden', () => {
  render(<CandidateBacktestWorkspace artifact={timed}/>);
  const perf=pane(PERFORMANCE);
  const calls=perf.series[0].setData.mock.calls.length;
  fireEvent.click(screen.getByRole('checkbox',{name:/^Strategy equity/}));
  expect(perf.series[0].applyOptions).toHaveBeenLastCalledWith({visible:false});
  expect(screen.queryByText(/Both curves are hidden/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('checkbox',{name:/^Long buy-and-hold/}));
  expect(perf.series[1].applyOptions).toHaveBeenLastCalledWith({visible:false});
  expect(screen.getByText('Both curves are hidden. Select a series above to display it.')).toBeInTheDocument();
  expect(perf.series[0].setData).toHaveBeenCalledTimes(calls);
  fireEvent.click(screen.getByRole('checkbox',{name:/^Strategy equity/}));
  expect(perf.series[0].applyOptions).toHaveBeenLastCalledWith({visible:true});
  expect(screen.queryByText(/Both curves are hidden/)).not.toBeInTheDocument();
 });
 it('expands the performance chart in place, preserving the view', () => {
  render(<CandidateBacktestWorkspace artifact={timed}/>);
  const perf=pane(PERFORMANCE);
  expect(perf.options.height).toBe(320);
  fireEvent.click(screen.getByRole('button',{name:'Expand chart'}));
  expect(screen.getByRole('button',{name:'Reduce chart'})).toHaveAttribute('aria-pressed','true');
  expect(perf.applyOptions).toHaveBeenLastCalledWith({height:520});
  fireEvent.click(screen.getByRole('button',{name:'Reduce chart'}));
  expect(perf.applyOptions).toHaveBeenLastCalledWith({height:320});
  expect(mockCharts).toHaveLength(3);
  expect(perf.scale.subscribeVisibleTimeRangeChange).toHaveBeenCalledTimes(1);
 });
 it('Last year changes only the display bounds of every pane; full-period cards are unchanged', () => {
  render(<CandidateBacktestWorkspace artifact={timed}/>);
  const before=cards();
  const all={from:T1,to:T4},year={from:at('2024-01-06T00:00:00Z'),to:T4};
  for(const label of [PRICE,PERFORMANCE,DRAWDOWN])expect(pane(label).scale.setVisibleRange).toHaveBeenLastCalledWith(all);
  expect(screen.getByText(/Showing all recorded history\. Baseline is unchanged; summary cards describe the full period\./)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Last year'}));
  expect(screen.getByRole('button',{name:'Last year'})).toHaveAttribute('aria-pressed','true');
  for(const label of [PRICE,PERFORMANCE,DRAWDOWN])expect(pane(label).scale.setVisibleRange).toHaveBeenLastCalledWith(year);
  expect(cards()).toBe(before);
  expect(screen.getByText(/Showing the last UTC calendar year to/)).toBeInTheDocument();
  expect(screen.getByText('Long buy-and-hold finished ahead of recorded strategy equity.')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'All history'}));
  for(const label of [PRICE,PERFORMANCE,DRAWDOWN])expect(pane(label).scale.setVisibleRange).toHaveBeenLastCalledWith(all);
  expect(cards()).toBe(before);
 });
 it('labels the engine max drawdown separately from the sampled drawdown pane', () => {
  render(<CandidateBacktestWorkspace artifact={timed}/>);
  expect(cards()).toContain('Engine max drawdown-16.50%');
  expect(screen.getByText('Sampled strategy drawdown · decline from its previous equity peak')).toBeInTheDocument();
  expect(screen.getByText('Latest -10.00% · deepest sampled -15.00%')).toBeInTheDocument();
  const values=lastData(pane(DRAWDOWN).series[0]);
  expect(values.map((r:any)=>r.time)).toEqual([T1,T2,T4]);
  expect(values[0].value).toBeCloseTo(-15,12);expect(values[1].value).toBe(0);expect(values[2].value).toBeCloseTo(-10,12);
 });
 it('discloses an unavailable sampled drawdown while keeping the engine metric', () => {
  render(<CandidateBacktestWorkspace artifact={{...timed,detail:{...timed.detail,initial_equity:0}}}/>);
  expect(screen.getByText(/Sampled drawdown unavailable/)).toBeInTheDocument();
  expect(screen.queryByLabelText(DRAWDOWN)).not.toBeInTheDocument();
  expect(cards()).toContain('Engine max drawdown-16.50%');
  expect(mockCharts).toHaveLength(2);
 });
 it('synchronizes ranges by timestamp from the pane in use only, and preserves the view on theme change', () => {
  render(<CandidateBacktestWorkspace artifact={timed}/>);
  const price=pane(PRICE),perf=pane(PERFORMANCE),drawdown=pane(DRAWDOWN);
  for(const chart of mockCharts)chart.scale.setVisibleRange.mockClear();
  // An emission from a pane the pointer is not in is a programmatic echo and is ignored.
  perf.scale.subscribeVisibleTimeRangeChange.mock.calls[0][0]({from:T2,to:T4});
  for(const chart of mockCharts)expect(chart.scale.setVisibleRange).not.toHaveBeenCalled();
  fireEvent.pointerEnter(screen.getByLabelText(PRICE));
  price.scale.subscribeVisibleTimeRangeChange.mock.calls[0][0]({from:T1,to:T3});
  expect(perf.scale.setVisibleRange).toHaveBeenCalledWith({from:T1,to:T3});
  expect(drawdown.scale.setVisibleRange).toHaveBeenCalledWith({from:T1,to:T3});
  expect(price.scale.setVisibleRange).not.toHaveBeenCalled();
  expect(price.scale.setVisibleLogicalRange).not.toHaveBeenCalled();
  price.scale.subscribeVisibleTimeRangeChange.mock.calls[0][0](null);
  expect(perf.scale.setVisibleRange).toHaveBeenCalledTimes(1);
  for(const chart of mockCharts)chart.scale.setVisibleRange.mockClear();
  act(()=>useThemeStore.getState().toggle());
  for(const chart of mockCharts){expect(chart.scale.setVisibleRange).not.toHaveBeenCalled();expect(chart.subscribeCrosshairMove).toHaveBeenCalledTimes(1);}
  expect(mockCharts).toHaveLength(3);
 });
});

describe('price styles and linked trade review', () => {
 const DAY = 86400, D = (n: number) => at('2024-01-01T00:00:00Z') + n * DAY;
 const days = [-400, ...Array.from({length: 60}, (_, n) => n)];
 const candles = days.map((n, i) => ({time: D(n), open: 100 + i, high: 102.5 + i, low: 98.25 + i, close: 101.125 + i, volume: 1000 + i}));
 const trade = (id: string, direction: string, entry: number, exit: number, net: number, extra: any = {}) => ({id, direction, entry_time: entry, exit_time: exit, entry_price: 100, exit_price: 101, size: 1, net_return_pct: net, commission: 0.5, exit_reason: 'unknown', ...extra});
 const trades = [
  trade('t1', 'Bullish', D(5), D(7), 2.5, {entry_price: 101.123456, exit_price: 103.987654, size: 10, commission: 2.0234, exit_reason: 'time'}),
  trade('t2', 'Bearish', D(10), D(12) + 3600, 1.75, {entry_price: 99.5, exit_price: 97.25, size: -5, commission: 0.75}),
  trade('t3', 'Bullish', D(14), D(16), -3), trade('t4', 'Bullish', D(18), D(20), 0),
  trade('t5', 'Bullish', D(22), D(24), 4.25), trade('t6', 'Bearish', D(26), D(28), -1.5),
  trade('t7', 'Bullish', D(32), D(34), 6), trade('t8', 'Bullish', D(50), D(52), -0.5),
 ];
 const review = {...timed, artifact_id: 'review', detail: {...timed.detail, candles, trades,
  equity: days.map(n => ({time: D(n), equity: 1000, strategy_index: 100, benchmark_index: 100})),
  open_positions: [{id: 'op', direction: 'Bullish', entry_time: D(55), entry_price: 120.5, size: 4, unrealized_pnl: 12}]}} as unknown as BacktestArtifact;
 const ohlc = candles.map(({time, open, high, low, close}) => ({time, open, high, low, close}));
 const ALL = {from: D(-400), to: D(59)}, YEAR = {from: at('2023-02-28T00:00:00Z'), to: D(59)};
 const activePrice = () => {const live = pane(PRICE).series.filter((s: any) => !s.removed); expect(live).toHaveLength(1); return live[0];};
 const liveMarkers = () => mockMarkers.at(-1);
 const markerPoints = () => {const m = liveMarkers(); return m.setMarkers.mock.calls.length ? m.setMarkers.mock.calls.at(-1)[0] : m.initial;};
 const lastRange = (label: string) => pane(label).scale.setVisibleRange.mock.calls.at(-1)[0];
 const expectRange = (range: any) => {for (const label of [PRICE, PERFORMANCE, DRAWDOWN]) expect(lastRange(label)).toEqual(range);};
 const inspector = () => screen.getByLabelText('Trade inspector');
 const row = (id: string) => screen.getByRole('button', {name: `Inspect trade ${id}`}).closest('tr');
 const clickMarker = (param: any) => act(() => pane(PRICE).subscribeClick.mock.calls[0][0](param));

 it('gives candles, OHLC bars and line the identical recorded OHLC and closes, moving markers and sync to the active series', () => {
  const {unmount} = render(<CandidateBacktestWorkspace artifact={review}/>);
  expect(screen.getByRole('button', {name: 'Candles'})).toHaveAttribute('aria-pressed', 'true');
  const candle = activePrice();
  expect(candle.type).toBe('candles');
  expect(lastData(candle)).toEqual(ohlc);
  const firstMarkers = liveMarkers();
  expect(firstMarkers.series).toBe(candle);
  const ids = markerPoints().map((m: any) => m.id);
  const scale = pane(PRICE).scale;
  scale.setVisibleLogicalRange.mockClear();
  fireEvent.click(screen.getByRole('button', {name: 'OHLC bars'}));
  expect(screen.getByRole('button', {name: 'OHLC bars'})).toHaveAttribute('aria-pressed', 'true');
  expect(pane(PRICE).removeSeries).toHaveBeenCalledWith(candle);
  const bars = activePrice();
  expect(bars.type).toBe('bars');
  expect(lastData(bars)).toEqual(ohlc);
  expect(firstMarkers.detach).toHaveBeenCalledTimes(1);
  expect(liveMarkers().series).toBe(bars);
  expect(markerPoints().map((m: any) => m.id)).toEqual(ids);
  expect(scale.setVisibleLogicalRange).toHaveBeenLastCalledWith({from: 1, to: 2});
  fireEvent.click(screen.getByRole('button', {name: 'Line'}));
  const line = activePrice();
  expect(line.type).toBe('line');
  expect(lastData(line)).toEqual(candles.map(c => ({time: c.time, value: c.close})));
  expect(liveMarkers().series).toBe(line);
  expect(mockMarkers.filter(m => m.detach.mock.calls.length === 1)).toHaveLength(2);
  expect(mockCharts).toHaveLength(3);
  // The crosshair follows the new price series.
  fireEvent.pointerEnter(screen.getByLabelText(PERFORMANCE));
  act(() => pane(PERFORMANCE).subscribeCrosshairMove.mock.calls[0][0]({time: D(5)}));
  expect(pane(PRICE).setCrosshairPosition).toHaveBeenLastCalledWith(candles[6].close, D(5), line);
  // The evidence itself is untouched.
  expect(review.detail.candles).toEqual(candles);
  unmount();
  for (const m of mockMarkers) expect(m.detach).toHaveBeenCalledTimes(1);
 });

 it('marks exact entries and exits only: direction-aware entry triangles, exit squares, no snapped or invented exits', () => {
  render(<CandidateBacktestWorkspace artifact={review}/>);
  const points = markerPoints();
  const ids = points.map((m: any) => m.id);
  expect(points.find((m: any) => m.id === 't1:entry')).toMatchObject({time: D(5), price: 101.123456, shape: 'arrowUp', position: 'atPriceMiddle'});
  expect(points.find((m: any) => m.id === 't1:exit')).toMatchObject({time: D(7), price: 103.987654, shape: 'square', position: 'atPriceMiddle'});
  expect(points.find((m: any) => m.id === 't2:entry')).toMatchObject({time: D(10), price: 99.5, shape: 'arrowDown'});
  expect(ids).not.toContain('t2:exit');
  expect(ids).toContain('op:entry');
  expect(ids).not.toContain('op:exit');
  expect(points.every((m: any) => !m.text)).toBe(true);
  // Every price style keeps visible markers on the scale (a fill above the plotted closes in Line mode would vanish otherwise); off-candle fills do not count.
  for (const style of ['Candles', 'OHLC bars', 'Line']) {
   fireEvent.click(screen.getByRole('button', {name: style}));
   const provider = activePrice().opts.autoscaleInfoProvider;
   expect(provider(() => ({priceRange: {minValue: 120, maxValue: 121}}))).toEqual({priceRange: {minValue: 99.5, maxValue: 121}});
   expect(provider(() => null)).toBeNull();
  }
  pane(PRICE).scale.getVisibleRange.mockReturnValueOnce({from: D(4), to: D(6)});
  expect(activePrice().opts.autoscaleInfoProvider(() => ({priceRange: {minValue: 100, maxValue: 101}}))).toEqual({priceRange: {minValue: 100, maxValue: 101.123456}});
  expect(screen.getByText(/Some fills have no exact original candle timestamp/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('checkbox', {name: 'Trade markers'}));
  expect(markerPoints()).toEqual([]);
  expect(activePrice().opts.autoscaleInfoProvider(() => ({priceRange: {minValue: 120, maxValue: 121}}))).toEqual({priceRange: {minValue: 120, maxValue: 121}});
  fireEvent.click(screen.getByRole('checkbox', {name: 'Trade markers'}));
  expect(markerPoints().map((m: any) => m.id)).toEqual(ids);
 });

 it('shows readable rows, keeps full recorded precision in the inspector and labels recorded exit reasons truthfully', () => {
  render(<CandidateBacktestWorkspace artifact={review}/>);
  expect(screen.getByText('Select “Inspect” in the trade table or click a chart marker to connect a trade with the price history.')).toBeInTheDocument();
  expect(within(row('t1')!).getByText('101.12 / 103.99')).toBeInTheDocument();
  expect(within(row('t1')!).getByText('+2.50%')).toBeInTheDocument();
  expect(within(row('t1')!).getByText('Time exit (holding limit)')).toBeInTheDocument();
  expect(within(row('t1')!).getByText('2024-01-06 00:00')).toBeInTheDocument();
  expect(within(row('t2')!).getByText('Unknown (not recorded by engine)')).toBeInTheDocument();
  expect(within(row('t2')!).getByText('2024-01-13 01:00')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', {name: 'Inspect trade t1'}));
  const t1 = within(inspector());
  for (const text of ['Bullish', new Date(D(5) * 1000).toISOString(), new Date(D(7) * 1000).toISOString(), '101.123456', '103.987654', '10', '2.0234', '2.5', 'Time exit (holding limit)']) expect(t1.getByText(text)).toBeInTheDocument();
  expect(screen.getByText(/Trade #t1 · Bullish · 2024-01-06 00:00 → 2024-01-08 00:00 · Recorded net return \+2\.50% · Time exit \(holding limit\)/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', {name: 'Inspect trade t2'}));
  const t2 = within(inspector());
  for (const text of ['Bearish', new Date((D(12) + 3600) * 1000).toISOString(), '99.5', '97.25', '-5', '0.75', '1.75', 'Unknown (not recorded by engine)']) expect(t2.getByText(text)).toBeInTheDocument();
  expect(t2.getByText('Not marked: no candle has this exact timestamp')).toBeInTheDocument();
  expect(t2.getByText('Marked at the exact candle')).toBeInTheDocument();
 });

 it('keeps selection by stable id across pagination and sorting, and handles the partial last page', () => {
  render(<CandidateBacktestWorkspace artifact={review}/>);
  expect(screen.getByText('1–6 of 8 trades')).toBeInTheDocument();
  expect(screen.queryByRole('button', {name: 'Inspect trade t8'})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', {name: 'Next page'}));
  expect(screen.getByText('7–8 of 8 trades')).toBeInTheDocument();
  expect(screen.getAllByRole('button', {name: /^Inspect trade/}).map(b => b.getAttribute('aria-label'))).toEqual(['Inspect trade t7', 'Inspect trade t8']);
  fireEvent.click(screen.getByRole('button', {name: 'Inspect trade t8'}));
  expect(row('t8')).toHaveAttribute('aria-current', 'true');
  fireEvent.change(screen.getByLabelText('Order'), {target: {value: 'best'}});
  // Highest return first: t7, t5, t1, t2, t4, t8 | t6, t3 — the selected trade stays selected and visible.
  expect(screen.getAllByRole('button', {name: /^Inspect trade/}).map(b => b.getAttribute('aria-label')?.slice(14))).toEqual(['t7', 't5', 't1', 't2', 't4', 't8']);
  expect(row('t8')).toHaveAttribute('aria-current', 'true');
  expect(within(inspector()).getByRole('heading', {name: 'Trade t8'})).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Order'), {target: {value: 'worst'}});
  expect(screen.getAllByRole('button', {name: /^Inspect trade/}).map(b => b.getAttribute('aria-label')?.slice(14))).toEqual(['t3', 't6', 't8', 't4', 't2', 't1']);
  fireEvent.change(screen.getByLabelText('Order'), {target: {value: 'newest'}});
  expect(screen.getAllByRole('button', {name: /^Inspect trade/})[0]).toHaveAccessibleName('Inspect trade t8');
  expect(within(inspector()).getByRole('heading', {name: 'Trade t8'})).toBeInTheDocument();
 });

 it('zooms every pane around the inspected trade, clamped to recorded bounds, and Clear returns to the last broad range', () => {
  render(<CandidateBacktestWorkspace artifact={review}/>);
  expectRange(ALL);
  fireEvent.click(screen.getByRole('button', {name: 'Inspect trade t1'}));
  expectRange({from: D(-15), to: D(27)});
  expect(screen.getByText(/Showing the selected trade and surrounding dates\./)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', {name: 'Clear selection'}));
  expectRange(ALL);
  expect(screen.queryByLabelText('Trade inspector')).not.toBeInTheDocument();
  expect(screen.getByRole('button', {name: 'Inspect trade t1'})).toHaveFocus();
  fireEvent.click(screen.getByRole('button', {name: 'Last year'}));
  expectRange(YEAR);
  fireEvent.click(screen.getByRole('button', {name: 'Next page'}));
  fireEvent.click(screen.getByRole('button', {name: 'Inspect trade t8'}));
  expectRange({from: D(30), to: D(59)});
  // Changing units, theme or price style keeps the selection and the zoom.
  for (const chart of mockCharts) chart.scale.setVisibleRange.mockClear();
  fireEvent.click(screen.getByRole('button', {name: 'Index 100'}));
  act(() => useThemeStore.getState().toggle());
  fireEvent.click(screen.getByRole('button', {name: 'Line'}));
  for (const chart of mockCharts) expect(chart.scale.setVisibleRange).not.toHaveBeenCalled();
  expect(within(inspector()).getByRole('heading', {name: 'Trade t8'})).toBeInTheDocument();
  expect(markerPoints().find((m: any) => m.id === 't8:entry').size).toBeGreaterThan(markerPoints().find((m: any) => m.id === 't1:entry').size);
  fireEvent.keyDown(screen.getByRole('button', {name: 'Inspect trade t8'}), {key: 'Escape'});
  expect(screen.queryByLabelText('Trade inspector')).not.toBeInTheDocument();
  expectRange(YEAR);
  expect(screen.getByRole('button', {name: 'Last year'})).toHaveAttribute('aria-pressed', 'true');
 });

 it('lets a broad range button override a trade zoom while keeping the selection', () => {
  render(<CandidateBacktestWorkspace artifact={review}/>);
  fireEvent.click(screen.getByRole('button', {name: 'Inspect trade t1'}));
  fireEvent.click(screen.getByRole('button', {name: 'All history'}));
  expectRange(ALL);
  expect(screen.getByText(/Showing all recorded history\./)).toBeInTheDocument();
  expect(within(inspector()).getByRole('heading', {name: 'Trade t1'})).toBeInTheDocument();
 });

 it('gives a marker click the same selection and zoom as the Inspect button, ignoring open positions and unknown ids', () => {
  render(<CandidateBacktestWorkspace artifact={review}/>);
  clickMarker({hoveredObjectId: 't8:exit', time: D(52)});
  expect(within(inspector()).getByRole('heading', {name: 'Trade t8'})).toBeInTheDocument();
  expectRange({from: D(30), to: D(59)});
  // The table follows to the page holding the selected trade.
  expect(row('t8')).toHaveAttribute('aria-current', 'true');
  expect(screen.getByText('7–8 of 8 trades')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', {name: 'Clear selection'}));
  for (const chart of mockCharts) chart.scale.setVisibleRange.mockClear();
  clickMarker({hoveredObjectId: 'op:entry', time: D(55)});
  clickMarker({hoveredObjectId: 'nope', time: undefined});
  expect(screen.queryByLabelText('Trade inspector')).not.toBeInTheDocument();
  for (const chart of mockCharts) expect(chart.scale.setVisibleRange).not.toHaveBeenCalled();
  // A click on a candle that holds a visible marker selects that trade; with markers hidden it does not.
  fireEvent.click(screen.getByRole('checkbox', {name: 'Trade markers'}));
  clickMarker({time: D(5)});
  expect(screen.queryByLabelText('Trade inspector')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('checkbox', {name: 'Trade markers'}));
  clickMarker({time: D(5)});
  expect(within(inspector()).getByRole('heading', {name: 'Trade t1'})).toBeInTheDocument();
  expectRange({from: D(-15), to: D(27)});
 });

 it('describes a hovered marker from its recorded fill, and an open position without an exit', () => {
  render(<CandidateBacktestWorkspace artifact={review}/>);
  fireEvent.pointerEnter(screen.getByLabelText(PRICE));
  const cross = pane(PRICE).subscribeCrosshairMove.mock.calls[0][0];
  act(() => cross({time: D(5), hoveredObjectId: 't1:entry'}));
  expect(screen.getByText(`Trade #t1 · Bullish entry · ${new Date(D(5) * 1000).toISOString()} · recorded fill 101.123456 · click to inspect`)).toBeInTheDocument();
  act(() => cross({time: D(55), hoveredObjectId: 'op:entry'}));
  expect(screen.getByText(`Open position #op · Bullish entry · ${new Date(D(55) * 1000).toISOString()} · recorded fill 120.5 · no exit recorded`)).toBeInTheDocument();
  act(() => cross({time: D(6)}));
  expect(screen.queryByText(/· recorded fill /)).not.toBeInTheDocument();
  expect(screen.getByText(/^▲ Long entry · ▼ Short entry · ■ Exit/)).toBeInTheDocument();
 });

 it('handles zero trades without pagination or a fabricated row', () => {
  render(<CandidateBacktestWorkspace artifact={{...review, detail: {...review.detail, trades: []}} as BacktestArtifact}/>);
  expect(screen.getByText('No closed trades recorded for this run.')).toBeInTheDocument();
  expect(screen.queryByRole('navigation', {name: 'Pagination'})).not.toBeInTheDocument();
  expect(markerPoints().map((m: any) => m.id)).toEqual(['op:entry']);
 });

 it('clears a stale selection when the artifact changes, even when trade ids repeat', () => {
  const {rerender} = render(<CandidateBacktestWorkspace artifact={review}/>);
  fireEvent.click(screen.getByRole('button', {name: 'Inspect trade t1'}));
  expect(screen.getByLabelText('Trade inspector')).toBeInTheDocument();
  rerender(<CandidateBacktestWorkspace artifact={{...review, artifact_id: 'review-2'} as BacktestArtifact}/>);
  expect(screen.queryByLabelText('Trade inspector')).not.toBeInTheDocument();
  expect(screen.getByRole('button', {name: 'Candles'})).toHaveAttribute('aria-pressed', 'true');
 });
});
