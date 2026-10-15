import React from 'react';
import { render, screen, fireEvent, act } from '@testing-library/react';
import CandidateBacktestWorkspace from './index';
import type { BacktestArtifact } from '@/types/backtest';
import { useThemeStore } from '@/lib/theme';
const mockCharts: any[] = [];
jest.mock('lightweight-charts', () => ({
 CandlestickSeries: 'candles', LineSeries: 'line',
 createSeriesMarkers: jest.fn(() => ({detach: jest.fn(),setMarkers:jest.fn()})),
 createChart: jest.fn(() => {
  const series: any[] = [];
  const scale = {subscribeVisibleLogicalRangeChange: jest.fn(), unsubscribeVisibleLogicalRangeChange: jest.fn(), setVisibleLogicalRange: jest.fn(), fitContent: jest.fn()};
  const chart = {series, scale, addSeries: jest.fn(() => {const s = {setData: jest.fn(), applyOptions: jest.fn()}; series.push(s); return s;}), timeScale: () => scale, applyOptions: jest.fn(), remove: jest.fn(), subscribeClick: jest.fn(), unsubscribeClick: jest.fn(), subscribeCrosshairMove: jest.fn(), unsubscribeCrosshairMove: jest.fn(), setCrosshairPosition: jest.fn(), clearCrosshairPosition: jest.fn()};
  mockCharts.push(chart); return chart;
 }),
}));
const artifact = {
 artifact_id: 'original-a', provenance: 'original', created_at: 1700000000,
 identity: {symbol: 'AAPL', strategy: 'pullback_ema', direction: 'Bearish', horizon: 'Swing', interval: '15m', input_hash: 'hash', scan_id: 'scan', bars_basis_version: 'basis', engine_contract_version: 'v1'},
 detail: {status: 'success', candles: [{time: 1700000000, open: 40, high: 45, low: 35, close: 42, volume: 10}], equity: [{time: 1700000000, equity: 100000, strategy_index: 100, benchmark_index: 100}], trades: [{id:'a', direction:'Bearish', entry_time:1700000000, exit_time:1700000000, entry_price:43.125, exit_price:39.875, net_return_pct:7.123, exit_reason:'unknown', size:-2, commission:1.25}], open_positions: [], summary: {n_trades: 1, total_return_pct: 0}, configuration: {commission: 0.001, initial_cash:100000, sizing:'equity', order_size:0.99}, effective_params:{ema_period:20}, time_basis:'UTC epoch seconds', initial_equity:100000},
} as unknown as BacktestArtifact;
beforeEach(() => {mockCharts.length=0; global.ResizeObserver = class {observe(){} disconnect(){} unobserve(){}};});
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
 expect(mockCharts[1].series[0].setData).toHaveBeenCalledWith([{time:1700000000,value:100}]);
});
it('guards synchronized ranges/crosshairs and cleans subscriptions/markers on unmount', () => {
 const {unmount}=render(<CandidateBacktestWorkspace artifact={artifact}/>);
 const [price,equity]=mockCharts;
 const sync=price.scale.subscribeVisibleLogicalRangeChange.mock.calls[0][0];
 equity.scale.setVisibleLogicalRange.mockImplementation((range:any) => equity.scale.subscribeVisibleLogicalRangeChange.mock.calls[0][0](range));
 sync({from:0,to:5});
 expect(equity.scale.setVisibleLogicalRange).toHaveBeenCalledTimes(1);
 // A queued callback after setVisibleLogicalRange also cannot bounce back.
 equity.scale.subscribeVisibleLogicalRangeChange.mock.calls[0][0]({from:0,to:5});
 expect(price.scale.setVisibleLogicalRange).not.toHaveBeenCalled();
 const cross=price.subscribeCrosshairMove.mock.calls[0][0];
 cross({time:1700000000});
 expect(equity.setCrosshairPosition).toHaveBeenCalledWith(100,1700000000,equity.series[0]);
 act(()=>useThemeStore.getState().toggle());
 expect(price.applyOptions).toHaveBeenCalled();
 unmount();
 expect(price.unsubscribeClick).toHaveBeenCalled();
 expect(price.unsubscribeCrosshairMove).toHaveBeenCalled();
 expect(price.scale.unsubscribeVisibleLogicalRangeChange).toHaveBeenCalled();
 expect(price.remove).toHaveBeenCalled();
});

it('resets incompatible symbol or interval without making a new run', () => {
 render(<CandidateBacktestWorkspace artifact={artifact}/>);
 fireEvent.change(screen.getByLabelText('Evidence interval'),{target:{value:'1d'}});
 expect(screen.getByText(/Original evidence hidden/)).toBeInTheDocument();
 expect(screen.queryByLabelText('Historical candles')).not.toBeInTheDocument();
 expect(mockCharts[0].remove).toHaveBeenCalled();
});


it('labels the distinct fresh result and keeps fresh provenance after interval changes', () => {
 render(<CandidateBacktestWorkspace artifact={{...artifact,artifact_id:'fresh-b',provenance:'fresh'}}/>);
 expect(screen.getByRole('heading',{name:'AAPL — Fresh backtest (separate result)'})).toBeInTheDocument();
 expect(screen.getByLabelText('Fresh backtest evidence')).toBeInTheDocument();
 fireEvent.change(screen.getByLabelText('Evidence interval'),{target:{value:'1d'}});
 expect(screen.getByText(/Fresh evidence hidden/)).toBeInTheDocument();
});
