/**
 * Page-level review: the real original-artifact hook, the real frozen report and the real
 * fresh-run controls, with only the network boundary (api) and the chart library mocked.
 */
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { useSearchParams } from 'next/navigation';
import { api } from '@/lib/api';
import type { BacktestArtifact, FreshBacktestRequest } from '@/types/backtest';
import CandidateChartWorkspace from '..';

jest.mock('next/navigation', () => ({useSearchParams: jest.fn()}));
jest.mock('@/lib/api', () => ({
 BacktestArtifactError: jest.requireActual('@/lib/api').BacktestArtifactError,
 api: {getOriginalBacktest: jest.fn(), getFreshBacktestConfiguration: jest.fn(), runFreshBacktest: jest.fn()},
}));
jest.mock('@/components/organisms/ChartWorkspace', () => ({__esModule: true, default: () => <div data-testid="live-chart">Live chart</div>}));
jest.mock('lightweight-charts', () => ({
 CandlestickSeries: 'candles', LineSeries: 'line', BarSeries: 'bars',
 createSeriesMarkers: jest.fn(() => ({detach: jest.fn(), setMarkers: jest.fn()})),
 createChart: jest.fn(() => {
  const scale = {subscribeVisibleTimeRangeChange: jest.fn(), unsubscribeVisibleTimeRangeChange: jest.fn(), setVisibleRange: jest.fn(), getVisibleRange: jest.fn(() => null), getVisibleLogicalRange: jest.fn(() => null), setVisibleLogicalRange: jest.fn(), fitContent: jest.fn()};
  return {addSeries: jest.fn(() => ({setData: jest.fn(), applyOptions: jest.fn()})), timeScale: () => scale, applyOptions: jest.fn(), remove: jest.fn(), removeSeries: jest.fn(), subscribeClick: jest.fn(), unsubscribeClick: jest.fn(), subscribeCrosshairMove: jest.fn(), unsubscribeCrosshairMove: jest.fn(), setCrosshairPosition: jest.fn(), clearCrosshairPosition: jest.fn()};
 }),
}));

const ID = '0f15f060-4602-4254-a113-2076894eb97c';
const T1 = Date.parse('2024-01-02T14:30:00Z') / 1000, T2 = Date.parse('2024-06-03T19:45:00Z') / 1000;
const original = {
 schema_version: 1, artifact_id: ID, provenance: 'original', created_at: T2, expires_at: T2 + 86400, currency: null,
 identity: {symbol: 'AAA', strategy: 'pullback_ema', direction: 'Bearish', horizon: 'Swing', interval: '15m', scan_id: 'scan-7', report_run_id: null, input_hash: 'hash', bars_basis_version: 'basis', engine_contract_version: 'v1'},
 detail: {
  status: 'success', reason: null, time_basis: 'UTC epoch seconds', initial_equity: 100000, engine_contract_version: 'v1',
  input_candles: [], candles: [{time: T1, open: 40, high: 45, low: 35, close: 42, volume: 10}, {time: T2, open: 42, high: 46, low: 41, close: 44, volume: 10}],
  equity: [{time: T1, equity: 100000, strategy_index: 100, benchmark_index: 100}, {time: T2, equity: 112000, strategy_index: 112, benchmark_index: 104}],
  trades: [{id: 'a', direction: 'Bearish', entry_time: T1, exit_time: T2, entry_price: 43.125, exit_price: 39.875, net_return_pct: 7.123, exit_reason: 'unknown', size: -2, commission: 1.25}],
  open_positions: [{id: 'op-1', direction: 'Bearish', entry_time: T2, entry_price: 44.0625, size: -3, unrealized_pnl: -1.5}],
  summary: {strategy: 'pullback_ema', direction: 'Bearish', n_trades: 1, win_rate: 1, total_return_pct: 12, max_drawdown_pct: -3.25, expectancy: 7.123, sharpe: 1.1, confidence: null, passes_gate: false, summary_text: 'original', n_time_exits: 0},
  configuration: {initial_cash: 100000, commission: 0.001, commission_basis: 'fraction per leg', order_size: 0.9999999999999998, sizing: 'fraction of available equity; whole units', margin: 1, spread: 0, exclusive_orders: true, trade_on_close: false, finalize_trades: false, hold_max_days: 10, entry_start: '2024-01-02', entry_end: '2024-06-04', min_trades: 5, min_win_rate: 0.5},
  effective_params: {ema_period: 20},
 },
} as unknown as BacktestArtifact;
const D1 = Date.parse('2024-04-22T00:00:00Z') / 1000, D2 = Date.parse('2024-05-29T00:00:00Z') / 1000;
/** A fresh artifact that satisfies FreshBacktestControls' request match, with its own values and interval. */
const freshFor = (request: FreshBacktestRequest): BacktestArtifact => ({
 schema_version: 1, artifact_id: 'fresh-b', provenance: 'fresh', created_at: D2, expires_at: D2 + 86400, currency: null,
 identity: {symbol: request.symbol, strategy: request.strategy, direction: request.direction, horizon: 'Swing', interval: '1d', scan_id: 'fresh-run', report_run_id: null, input_hash: 'hash-f', bars_basis_version: 'basis', engine_contract_version: 'v1'},
 detail: {
  ...original.detail,
  candles: [{time: D1, open: 50, high: 51, low: 49, close: 50, volume: 1}, {time: D2, open: 50, high: 52, low: 48, close: 49, volume: 1}],
  equity: [{time: D1, equity: 100000, strategy_index: 100, benchmark_index: 100}, {time: D2, equity: 95000, strategy_index: 95, benchmark_index: 98}],
  trades: [], open_positions: [],
  summary: {...original.detail.summary, n_trades: 0, win_rate: 0, total_return_pct: -5, summary_text: 'fresh'},
  effective_params: request.params,
  configuration: {...original.detail.configuration, commission: request.commission, hold_max_days: request.hold_max_days, entry_start: request.start, entry_end: request.end, min_trades: request.min_trades, min_win_rate: request.min_win_rate},
 },
} as unknown as BacktestArtifact);

const route = (query: string) => (useSearchParams as jest.Mock).mockReturnValue(new URLSearchParams(query));
const ORIGINAL_ROUTE = `symbol=AAA&source=stocks&backtest_artifact_status=available&backtest_artifact_id=${ID}`;
const freshToggle = () => screen.getByRole('button', {name: 'Separate fresh run'});
const cards = () => screen.getByLabelText('Full-period performance summary').textContent;
const header = () => screen.getByRole('region', {name: 'Backtest review'});

async function openAndFill() {
 fireEvent.click(freshToggle());
 await act(async () => {});
 fireEvent.change(screen.getByLabelText('Evaluation start'), {target: {value: '2024-04-20'}});
 fireEvent.change(screen.getByLabelText('Evaluation end (exclusive)'), {target: {value: '2024-05-30'}});
 fireEvent.change(screen.getByLabelText('Commission per leg (fraction)'), {target: {value: '0.002'}});
}

beforeEach(() => {
 jest.clearAllMocks();
 global.ResizeObserver = class {observe() {} disconnect() {} unobserve() {}} as any;
 (api.getOriginalBacktest as jest.Mock).mockResolvedValue(original);
 (api.getFreshBacktestConfiguration as jest.Mock).mockResolvedValue({strategies: ['pullback_ema'], parameters: {pullback_ema: {ema_period: 'int'}}, multi_fields: []});
 (api.runFreshBacktest as jest.Mock).mockImplementation(async (request: FreshBacktestRequest) => ({status: 'success', artifact: freshFor(request)}));
});

test('recorded run identity and period come first and the original frozen report is the default', async () => {
 route(ORIGINAL_ROUTE);
 render(<CandidateChartWorkspace/>);
 await act(async () => {});
 expect(within(header()).getByRole('heading', {level: 1, name: 'AAA / Backtest review'})).toBeInTheDocument();
 expect(header()).toHaveTextContent('Did the strategy beat buying and holding?');
 expect(header()).toHaveTextContent('pullback_ema · Bearish · Interval 15m · Recorded period 2024-01-02 14:30 → 2024-06-03 19:45 UTC');
 expect(header()).toHaveTextContent('Stocks screener / Backtest review / AAA');
 expect(within(header()).getByText('Original scan')).toBeInTheDocument();
 // The header precedes the report in document order.
 const report = screen.getByLabelText('Original backtest evidence');
 expect(header().compareDocumentPosition(report) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
 expect(screen.getByRole('heading', {name: 'AAA — Original backtest'})).toBeInTheDocument();
 expect(cards()).toContain('+12.00%');
 // Fresh configuration is a secondary, collapsed disclosure; nothing about it is fetched or run.
 expect(freshToggle()).toHaveAttribute('aria-expanded', 'false');
 expect(screen.queryByLabelText('Fresh strategy')).not.toBeInTheDocument();
 expect(screen.queryByRole('group', {name: 'Backtest result selection'})).not.toBeInTheDocument();
 expect(api.getFreshBacktestConfiguration).not.toHaveBeenCalled();
 expect(api.runFreshBacktest).not.toHaveBeenCalled();
 expect(api.getOriginalBacktest).toHaveBeenCalledTimes(1);
});

test('opening and closing the configuration keeps every entered field and never runs or replaces evidence', async () => {
 route(ORIGINAL_ROUTE);
 render(<CandidateChartWorkspace/>);
 await act(async () => {});
 await openAndFill();
 expect(freshToggle()).toHaveAttribute('aria-expanded', 'true');
 expect(screen.getByLabelText('Fresh strategy')).toHaveValue('pullback_ema');
 fireEvent.click(screen.getByLabelText(/I reviewed the strategy/));
 fireEvent.click(freshToggle());
 expect(freshToggle()).toHaveAttribute('aria-expanded', 'false');
 expect(screen.queryByLabelText('Evaluation start')).not.toBeInTheDocument();
 expect(screen.getByRole('heading', {name: 'AAA — Original backtest'})).toBeInTheDocument();
 fireEvent.click(freshToggle());
 await act(async () => {});
 expect(screen.getByLabelText('Evaluation start')).toHaveValue('2024-04-20');
 expect(screen.getByLabelText('Evaluation end (exclusive)')).toHaveValue('2024-05-30');
 expect(screen.getByLabelText('Commission per leg (fraction)')).toHaveValue(0.002);
 expect(screen.getByLabelText(/I reviewed the strategy/)).toBeChecked();
 // The in-panel close behaves the same as the header disclosure.
 fireEvent.click(screen.getByRole('button', {name: 'Close configuration'}));
 expect(freshToggle()).toHaveAttribute('aria-expanded', 'false');
 expect(api.runFreshBacktest).not.toHaveBeenCalled();
 expect(api.getOriginalBacktest).toHaveBeenCalledTimes(1);
 expect(screen.getByLabelText('Original backtest evidence')).toBeInTheDocument();
 expect(cards()).toContain('+12.00%');
});

test('only an explicit, confirmed run calls the run API; switching keeps each result identity, values and interval', async () => {
 route(ORIGINAL_ROUTE);
 render(<CandidateChartWorkspace/>);
 await act(async () => {});
 await openAndFill();
 const run = screen.getByRole('button', {name: 'Run fresh backtest'});
 expect(run).toBeDisabled();
 fireEvent.click(run);
 expect(api.runFreshBacktest).not.toHaveBeenCalled();
 fireEvent.click(screen.getByLabelText(/I reviewed the strategy/));
 fireEvent.click(screen.getByRole('button', {name: 'Run fresh backtest'}));
 await act(async () => {});
 expect(api.runFreshBacktest).toHaveBeenCalledTimes(1);
 expect(api.runFreshBacktest).toHaveBeenCalledWith(expect.objectContaining({symbol: 'AAA', strategy: 'pullback_ema', direction: 'Bearish', start: '2024-04-20', end: '2024-05-30', commission: 0.002, confirmed: true}), expect.any(AbortSignal));
 const showOriginal = screen.getByRole('button', {name: 'Show original backtest'});
 const showFresh = screen.getByRole('button', {name: 'Show fresh backtest'});
 expect(within(screen.getByRole('group', {name: 'Backtest result selection'})).getAllByRole('button')).toHaveLength(2);
 expect(showFresh).toHaveAttribute('aria-pressed', 'true');
 expect(showOriginal).toHaveAttribute('aria-pressed', 'false');
 expect(screen.getByRole('heading', {name: 'AAA — Fresh backtest (separate result)'})).toBeInTheDocument();
 expect(within(header()).getByText('Fresh run')).toBeInTheDocument();
 expect(header()).toHaveTextContent('Interval 1d · Recorded period 2024-04-22 00:00 → 2024-05-29 00:00 UTC');
 expect(screen.getByText(/Fresh interval: 1d/)).toBeInTheDocument();
 expect(cards()).toContain('-5.00%');
 expect(cards()).not.toContain('+12.00%');

 fireEvent.click(showOriginal);
 expect(showOriginal).toHaveAttribute('aria-pressed', 'true');
 expect(showFresh).toHaveAttribute('aria-pressed', 'false');
 expect(screen.getByRole('heading', {name: 'AAA — Original backtest'})).toBeInTheDocument();
 expect(within(header()).getByText('Original scan')).toBeInTheDocument();
 expect(header()).toHaveTextContent('Interval 15m · Recorded period 2024-01-02 14:30 → 2024-06-03 19:45 UTC');
 expect(screen.getByText(/Original interval: 15m/)).toBeInTheDocument();
 expect(cards()).toContain('+12.00%');
 // Original provenance and open positions remain discoverable after the round trip.
 expect(screen.getByText(`Provenance: original · Artifact ${ID} · Run scan-7`, {exact: false})).toBeInTheDocument();
 expect(screen.getByText(/op-1 · Bearish · Entry .* @ 44\.0625 · Size -3 · Unrealized P&L -1\.5/)).toBeInTheDocument();
 expect(screen.getByText('Calculation basis & comparison limits')).toBeInTheDocument();

 fireEvent.click(showFresh);
 expect(screen.getByText('Provenance: fresh · Artifact fresh-b', {exact: false})).toBeInTheDocument();
 expect(api.runFreshBacktest).toHaveBeenCalledTimes(1);
 expect(api.getOriginalBacktest).toHaveBeenCalledTimes(1);
});

test('closing the disclosure during a run cancels it; the original report is unchanged', async () => {
 let resolve!: (value: unknown) => void;
 (api.runFreshBacktest as jest.Mock).mockImplementation(() => new Promise(r => {resolve = r;}));
 route(ORIGINAL_ROUTE);
 render(<CandidateChartWorkspace/>);
 await act(async () => {});
 await openAndFill();
 fireEvent.click(screen.getByLabelText(/I reviewed the strategy/));
 fireEvent.click(screen.getByRole('button', {name: 'Run fresh backtest'}));
 const signal: AbortSignal = (api.runFreshBacktest as jest.Mock).mock.calls[0][1];
 fireEvent.click(freshToggle());
 expect(signal.aborted).toBe(true);
 expect(screen.getByRole('status')).toHaveTextContent('Fresh run cancelled. Original evidence is unchanged.');
 const request = (api.runFreshBacktest as jest.Mock).mock.calls[0][0];
 await act(async () => resolve({status: 'success', artifact: freshFor(request)}));
 expect(screen.queryByRole('button', {name: 'Show fresh backtest'})).not.toBeInTheDocument();
 expect(screen.getByRole('heading', {name: 'AAA — Original backtest'})).toBeInTheDocument();
});

test('a fresh-run error stays visible with the disclosure closed and the original report unchanged', async () => {
 (api.runFreshBacktest as jest.Mock).mockResolvedValue({status: 'insufficient_history', artifact: null});
 route(ORIGINAL_ROUTE);
 render(<CandidateChartWorkspace/>);
 await act(async () => {});
 await openAndFill();
 fireEvent.click(screen.getByLabelText(/I reviewed the strategy/));
 fireEvent.click(screen.getByRole('button', {name: 'Run fresh backtest'}));
 await act(async () => {});
 fireEvent.click(freshToggle());
 expect(screen.getByRole('status')).toHaveTextContent('Fresh run unavailable: insufficient_history. Original evidence is unchanged.');
 expect(screen.queryByRole('group', {name: 'Backtest result selection'})).not.toBeInTheDocument();
 expect(cards()).toContain('+12.00%');
});

test('a late fresh result after a candidate change cannot render on the new candidate', async () => {
 let resolve!: (value: unknown) => void;
 (api.runFreshBacktest as jest.Mock).mockImplementation(() => new Promise(r => {resolve = r;}));
 route(ORIGINAL_ROUTE);
 const view = render(<CandidateChartWorkspace/>);
 await act(async () => {});
 await openAndFill();
 fireEvent.click(screen.getByLabelText(/I reviewed the strategy/));
 fireEvent.click(screen.getByRole('button', {name: 'Run fresh backtest'}));
 const [request, signal] = (api.runFreshBacktest as jest.Mock).mock.calls[0];
 route('symbol=BBB&source=stocks&backtest_artifact_status=original_unavailable');
 view.rerender(<CandidateChartWorkspace/>);
 expect(signal.aborted).toBe(true);
 await act(async () => resolve({status: 'success', artifact: freshFor(request)}));
 expect(within(header()).getByRole('heading', {level: 1, name: 'BBB / Backtest review'})).toBeInTheDocument();
 expect(screen.queryByLabelText('Fresh backtest evidence')).not.toBeInTheDocument();
 expect(screen.queryByRole('button', {name: 'Show fresh backtest'})).not.toBeInTheDocument();
 expect(screen.queryByText(/AAA/)).not.toBeInTheDocument();
 expect(freshToggle()).toHaveAttribute('aria-expanded', 'false');
 expect(screen.getByTestId('live-chart')).toBeInTheDocument();
});

test('a fresh result offered without an original never fabricates an original report', async () => {
 route('symbol=AAA&source=pullback&backtest_artifact_status=original_unavailable');
 render(<CandidateChartWorkspace/>);
 await openAndFill();
 fireEvent.change(screen.getByLabelText('Fresh strategy'), {target: {value: 'pullback_ema'}});
 fireEvent.change(screen.getByLabelText('Fresh direction'), {target: {value: 'Bullish'}});
 fireEvent.change(screen.getByLabelText('Maximum hold days (null for none)'), {target: {value: '10'}});
 fireEvent.change(screen.getByLabelText('Minimum closed trades'), {target: {value: '5'}});
 fireEvent.change(screen.getByLabelText('Minimum win rate (fraction)'), {target: {value: '0.5'}});
 fireEvent.change(screen.getByLabelText('Complete strategy parameters (JSON)'), {target: {value: '{"ema_period":50}'}});
 fireEvent.click(screen.getByLabelText(/I reviewed the strategy/));
 fireEvent.click(screen.getByRole('button', {name: 'Run fresh backtest'}));
 await act(async () => {});
 expect(screen.getByRole('heading', {name: 'AAA — Fresh backtest (separate result)'})).toBeInTheDocument();
 fireEvent.click(screen.getByRole('button', {name: 'Show original backtest'}));
 expect(screen.queryByLabelText('Original backtest evidence')).not.toBeInTheDocument();
 expect(screen.queryByLabelText('Fresh backtest evidence')).not.toBeInTheDocument();
 expect(screen.getByText(/Original backtest unavailable: original_unavailable .*no historical result has been substituted/)).toBeInTheDocument();
 expect(screen.getByTestId('live-chart')).toBeInTheDocument();
 expect(within(header()).getByText('No original result')).toBeInTheDocument();
 expect(api.getOriginalBacktest).not.toHaveBeenCalled();
});
