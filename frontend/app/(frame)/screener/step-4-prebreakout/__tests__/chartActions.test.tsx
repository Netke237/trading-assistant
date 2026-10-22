import { act, fireEvent, render, screen, within } from '@testing-library/react';
import Page from '../page';
import { api } from '@/lib/api';
import { useScanStore } from '@/lib/scanStore';
import { useUniverseStore } from '@/lib/universeStore';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { WATCHLIST_STORAGE_KEY } from '@/lib/watchlistStore';

jest.mock('@/lib/api', () => ({ api: {
  getCandles: jest.fn(), prebreakoutScan: jest.fn(), fibPullbackScan: jest.fn(), postStockScan: jest.fn(),
  addWatchlist: jest.fn(), removeWatchlist: jest.fn(), getCompositeWatchDefaults: jest.fn(),
  getSymbolRegimeSnapshot: jest.fn(), addCompositeWatch: jest.fn(), addCompositeAlertRule: jest.fn(),
} }));
jest.mock('@/components/organisms/SavedScanReportInspector', () => ({ SavedScanReportInspector: () => null }));
jest.mock('@/components/organisms/CandlestickChart', () => ({ CandlestickChart: (props: {data: {close: number}[]; priceLines?: {price: number; title: string}[]}) =>
  <div data-testid="candles">{JSON.stringify(props)}</div> }));

const row = (symbol: string, direction = 'Bearish') => ({symbol, direction, confidence: 80, metrics: {swing_level: 120}});
const fib = (symbol: string) => ({symbol, direction: 'Bearish', confidence: 80, fib_level_hit: '38.2', fib_dist_pct: 0, at_level: true, fib_swing: {low: 100, high: 200}});
const candles = (close: number) => [{time: '2026-10-01', open: close, high: close, low: close, close, volume: 100}];
beforeEach(() => {
  jest.clearAllMocks();
  useScanStore.setState({context: {direction: 'Bullish', horizon: 'Swing'} as never, preBreakoutResults: [], fibPullbackResults: []});
  useUniverseStore.setState({pick: 'SP500'});
  useWatchlistStore.setState({added: []});
  (api.getCandles as jest.Mock).mockResolvedValue(candles(100));
  (api.addWatchlist as jest.Mock).mockResolvedValue({});
  (api.removeWatchlist as jest.Mock).mockResolvedValue({});
  (api.getCompositeWatchDefaults as jest.Mock).mockResolvedValue({conviction_min: 50, p_stay_min: .5, min_confirmations: 1});
  (api.getSymbolRegimeSnapshot as jest.Mock).mockResolvedValue({state: 'Bear', p_stay: .7});
  (api.addCompositeWatch as jest.Mock).mockResolvedValue({});
  (api.addCompositeAlertRule as jest.Mock).mockResolvedValue({});
});

test.each(['prebreakout', 'fib', 'pullback'])('%s alert saves clicked symbol and row direction despite ambient context, then dismisses/reset', async mode => {
  useScanStore.setState({preBreakoutResults: [row('OTHER'), row('CLICK')], fibPullbackResults: [fib('OTHER'), fib('CLICK')]});
  (api.postStockScan as jest.Mock).mockResolvedValue({candidates: ['OTHER', 'CLICK'].map(symbol => ({...row(symbol), stock_score: 70, price: 100}))});
  const view = render(<Page/>);
  if (mode === 'prebreakout') {
    // Existing rows survive remount even if the inherited direction has changed.
    view.unmount(); useScanStore.setState({context: {direction: 'Bullish', horizon: 'Position'} as never}); render(<Page/>);
  } else {
    fireEvent.click(screen.getByRole('button', {name: mode === 'fib' ? 'Fib Pullback' : 'Pullback to EMA 50'}));
    if (mode === 'pullback') await act(async () => fireEvent.click(screen.getByRole('button', {name: 'Run Scan'})));
  }
  fireEvent.click(screen.getByRole('button', {name: 'Select OTHER'}));
  fireEvent.click(within(screen.getByRole('button', {name: 'Select CLICK'})).getByRole('button', {name: 'Alert'}));
  expect(screen.getByLabelText('Selected setup')).toHaveTextContent('OTHER');
  expect(await screen.findByRole('dialog', {name: 'Set regime alert for CLICK'})).toBeInTheDocument();
  await act(async () => fireEvent.click(screen.getByRole('button', {name: 'Create Alert'})));
  expect(api.addCompositeWatch).toHaveBeenCalledWith('CLICK', expect.objectContaining({direction: 'Bearish'}), 'Bearish', '1D');
  fireEvent.click(screen.getByRole('button', {name: 'Close'}));
  fireEvent.click(within(screen.getByRole('button', {name: 'Select CLICK'})).getByRole('button', {name: 'Alert'}));
  expect(screen.getByRole('button', {name: 'Create Alert'})).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', {name: 'Rule (live)'}));
  await act(async () => fireEvent.click(screen.getByRole('button', {name: 'Create Alert'})));
  expect(api.addCompositeAlertRule).toHaveBeenCalledWith('CLICK composite', 'CLICK', '1D', expect.objectContaining({direction: 'Bearish'}));
});

test.each(['prebreakout', 'fib', 'pullback'])('%s actions keep selection and persist symmetric clicked-row watch changes and chart URL', async mode => {
  useScanStore.setState({preBreakoutResults: [row('OTHER'), row('CLICK')], fibPullbackResults: [fib('OTHER'), fib('CLICK')]});
  (api.postStockScan as jest.Mock).mockResolvedValue({candidates: ['OTHER', 'CLICK'].map(symbol => ({...row(symbol), stock_score: 70, price: 100}))});
  const open = jest.spyOn(window, 'open').mockImplementation(() => null);
  render(<Page/>);
  if (mode !== 'prebreakout') fireEvent.click(screen.getByRole('button', {name: mode === 'fib' ? 'Fib Pullback' : 'Pullback to EMA 50'}));
  if (mode === 'pullback') await act(async () => fireEvent.click(screen.getByRole('button', {name: 'Run Scan'})));
  fireEvent.click(screen.getByRole('button', {name: 'Select OTHER'}));
  await act(async () => fireEvent.click(screen.getByRole('button', {name: 'Add CLICK to watchlist'})));
  expect(api.addWatchlist).toHaveBeenCalledWith('CLICK');
  expect(useWatchlistStore.getState().added).toContain('CLICK');
  expect(JSON.parse(localStorage.getItem(WATCHLIST_STORAGE_KEY)!).state.added).toContain('CLICK');
  await act(async () => fireEvent.click(screen.getByRole('button', {name: 'Remove CLICK from watchlist'})));
  expect(api.removeWatchlist).toHaveBeenCalledWith('CLICK');
  expect(useWatchlistStore.getState().added).not.toContain('CLICK');
  fireEvent.click(screen.getByRole('button', {name: 'Open CLICK chart in a new tab'}));
  expect(open).toHaveBeenCalledWith(`/chart?symbol=CLICK&source=${mode}&backtest_artifact_status=original_unavailable`, '_blank');
  expect(screen.getByLabelText('Selected setup')).toHaveTextContent('OTHER');
  expect(within(screen.getByRole('region', {name: 'Selected setup chart'})).queryByRole('button', {name: /Alert|watchlist|new tab/})).toBeNull();
  open.mockRestore();
});

test('late candle success/error never draws for another symbol or same-symbol replacement scan scope', async () => {
  const pending: {resolve: (value: unknown) => void; reject: (value: unknown) => void}[] = [];
  (api.getCandles as jest.Mock).mockImplementation(() => new Promise((resolve, reject) => pending.push({resolve, reject})));
  useScanStore.setState({preBreakoutResults: [row('AAA'), row('BBB')]}); render(<Page/>);
  fireEvent.click(screen.getByRole('button', {name: 'Select AAA'}));
  expect(screen.getByText('Loading chart…')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', {name: 'Select BBB'}));
  await act(async () => pending[0].resolve(candles(111)));
  expect(screen.queryByTestId('candles')).toBeNull();
  // Retain selected symbol, replace exact result row/run scope.
  act(() => useScanStore.setState({preBreakoutResults: [row('BBB')]}));
  expect(api.getCandles).toHaveBeenCalledTimes(3);
  await act(async () => pending[2].resolve(candles(333)));
  expect(screen.getByTestId('candles')).toHaveTextContent('333');
  await act(async () => pending[1].reject(new Error('late failure')));
  expect(screen.getByTestId('candles')).toHaveTextContent('333');
  expect(screen.queryByText(/Chart unavailable/)).toBeNull();
});

test('chart failure and empty candles remain local while table and evidence stay available', async () => {
  (api.getCandles as jest.Mock).mockRejectedValue(new Error('feed failed'));
  useScanStore.setState({preBreakoutResults: [row('AAA'), row('BBB')]}); render(<Page/>);
  fireEvent.click(screen.getByRole('button', {name: 'Select AAA'}));
  expect(await screen.findByText(/Chart unavailable/)).toBeInTheDocument();
  expect(screen.getByRole('button', {name: 'Select BBB'})).toBeInTheDocument();
  expect(screen.getByRole('region', {name: 'Evidence for AAA'})).toBeInTheDocument();
  (api.getCandles as jest.Mock).mockResolvedValue([]);
  fireEvent.click(screen.getByRole('button', {name: 'Select BBB'}));
  expect(await screen.findByText(/No daily candles available/)).toBeInTheDocument();
  expect(screen.getByRole('button', {name: 'Select AAA'})).toBeInTheDocument();
});

test('nested action keyboard events retain default activation and do not select their row', async () => {
  useScanStore.setState({preBreakoutResults: [row('OTHER'), row('CLICK')]});
  render(<Page/>);
  fireEvent.keyDown(screen.getByRole('button', {name: 'Select OTHER'}), {key: 'Enter'});
  const actions = within(screen.getByRole('button', {name: 'Select CLICK'}));
  for (const action of [
    actions.getByRole('button', {name: 'Add CLICK to watchlist'}),
    actions.getByRole('button', {name: 'Open CLICK chart in a new tab'}),
    actions.getByRole('button', {name: 'Alert'}),
  ]) {
    action.focus();
    // DOM dispatch reports false if the row cancelled a native button's keydown.
    expect(fireEvent.keyDown(action, {key: 'Enter'})).toBe(true);
    expect(fireEvent.keyDown(action, {key: ' '})).toBe(true);
    expect(screen.getByLabelText('Selected setup')).toHaveTextContent('OTHER');
  }
  await act(async () => {});
});


test.each(['Bullish','Bearish'])('pullback %s chart takes clicked original ID even after same-symbol scan replacement', async direction => {
  const id = '0f15f060-4602-4254-a113-2076894eb97c';
  const replacement = '1f15f060-4602-4254-a113-2076894eb97c';
  const candidate = (symbol: string, artifactId: string) => ({...row(symbol,direction),stock_score:70,price:100,backtest_artifact_id:artifactId,backtest_artifact_status:'available'});
  (api.postStockScan as jest.Mock).mockResolvedValue({candidates:[candidate('OTHER',replacement),candidate('CLICK',id)]});
  const open = jest.spyOn(window,'open').mockImplementation(() => null);
  render(<Page/>);
  fireEvent.click(screen.getByRole('button',{name:'Pullback to EMA 50'}));
  await act(async () => fireEvent.click(screen.getByRole('button',{name:'Run Scan'})));
  fireEvent.click(screen.getByRole('button',{name:'Select OTHER'}));
  fireEvent.click(screen.getByRole('button',{name:'Open CLICK chart in a new tab'}));
  expect(open).toHaveBeenLastCalledWith(`/chart?symbol=CLICK&source=pullback&backtest_artifact_status=available&backtest_artifact_id=${id}`,'_blank');
  (api.postStockScan as jest.Mock).mockResolvedValue({candidates:[candidate('CLICK',replacement)]});
  await act(async () => fireEvent.click(screen.getByRole('button',{name:'Run Scan'})));
  fireEvent.click(screen.getByRole('button',{name:'Open CLICK chart in a new tab'}));
  expect(open).toHaveBeenLastCalledWith(`/chart?symbol=CLICK&source=pullback&backtest_artifact_status=available&backtest_artifact_id=${replacement}`,'_blank');
  open.mockRestore();
});
