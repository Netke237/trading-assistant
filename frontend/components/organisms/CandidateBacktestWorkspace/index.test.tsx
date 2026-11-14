import React from 'react';
import { render, screen, fireEvent, act } from '@testing-library/react';
import CandidateBacktestWorkspace from './index';
import type { BacktestArtifact } from '@/types/backtest';
import { useThemeStore } from '@/lib/theme';
const mockCharts: any[] = [];
jest.mock('lightweight-charts', () => ({
 CandlestickSeries: 'candles', LineSeries: 'line',
 createSeriesMarkers: jest.fn(() => ({detach: jest.fn(),setMarkers:jest.fn()})),
 createChart: jest.fn((container: HTMLElement, options: any) => {
  const series: any[] = [];
  const scale = {subscribeVisibleTimeRangeChange: jest.fn(), unsubscribeVisibleTimeRangeChange: jest.fn(), setVisibleRange: jest.fn(), getVisibleLogicalRange: jest.fn(() => ({from:1,to:2})), setVisibleLogicalRange: jest.fn(), fitContent: jest.fn()};
  const chart = {container, options, series, scale, addSeries: jest.fn((type: string, opts: any) => {const s = {type, opts, setData: jest.fn(), applyOptions: jest.fn()}; series.push(s); return s;}), timeScale: () => scale, applyOptions: jest.fn(), remove: jest.fn(), subscribeClick: jest.fn(), unsubscribeClick: jest.fn(), subscribeCrosshairMove: jest.fn(), unsubscribeCrosshairMove: jest.fn(), setCrosshairPosition: jest.fn(), clearCrosshairPosition: jest.fn()};
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
 mockCharts.length=0; global.ResizeObserver = class {observe(){} disconnect(){} unobserve(){}} as any;
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
 expect(screen.getByText('Unknown (not recorded by engine)')).toBeInTheDocument();
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
