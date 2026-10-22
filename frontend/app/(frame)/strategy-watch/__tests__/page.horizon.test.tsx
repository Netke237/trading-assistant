// STOCKS-HORIZON-T1 H7: the add form offers the five tuned horizons plus "none";
// the request carries the choice; the list shows each watch's horizon.
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import StrategyWatchPage from '../page';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({
  api: {
    getStrategyWatches: jest.fn(),
    getStrategyWatchSchedule: jest.fn().mockResolvedValue({
      enabled: false, mode: 'eod', eod_time: '16:15', poll_hours: 4, sustain_minutes: 0,
    }),
    addStrategyWatch: jest.fn().mockResolvedValue({}),
    addStrategyWatchesBulk: jest.fn().mockResolvedValue({ added: 0, watches: [] }),
    getSymbolInfo: jest.fn().mockResolvedValue({ name: 'Apple' }),
  },
}));

const state = {
  phase: 'idle' as const, direction: null, entry_price: null, stop_price: null,
  target_price: null, last_event: null, last_event_at: null,
};

beforeEach(() => {
  jest.clearAllMocks();
  (api.getStrategyWatches as jest.Mock).mockResolvedValue([
    { id: 'w1', symbol: 'AAPL', strategy_key: 'pullback_ema', direction: 'Bullish',
      params_override: {}, params_horizon: 'Quarterly', hold_max_days: 60,
      enabled: true, created_at: '', last_state: state },
    { id: 'w2', symbol: 'MSFT', strategy_key: 'pullback_ema', direction: 'Bullish',
      params_override: {}, enabled: true, created_at: '', last_state: state },
  ]);
});

it('offers none plus the five tuned horizons and sends the pick', async () => {
  render(<StrategyWatchPage />);
  const select = screen.getByLabelText('Horizon') as HTMLSelectElement;
  expect(Array.from(select.options).map((o) => o.value))
    .toEqual(['', 'Swing', 'Position', 'Quarterly', 'SemiAnnual', 'Annual']);
  fireEvent.change(screen.getByPlaceholderText('Symbol (e.g. AAPL)'), { target: { value: 'NVDA' } });
  fireEvent.change(select, { target: { value: 'Position' } });
  fireEvent.click(screen.getByText('Add'));
  await waitFor(() =>
    expect(api.addStrategyWatch).toHaveBeenCalledWith('NVDA', 'pullback_ema', 'Bullish', 'Position'));
});

it('sends null when the horizon is none', async () => {
  render(<StrategyWatchPage />);
  fireEvent.change(screen.getByPlaceholderText('Symbol (e.g. AAPL)'), { target: { value: 'NVDA' } });
  fireEvent.click(screen.getByText('Add'));
  await waitFor(() =>
    expect(api.addStrategyWatch).toHaveBeenCalledWith('NVDA', 'pullback_ema', 'Bullish', null));
});

it('bulk add sends the bulk horizon pick', async () => {
  render(<StrategyWatchPage />);
  fireEvent.change(screen.getByPlaceholderText('Bulk: AAPL, MSFT, GOOG'), { target: { value: 'AAPL, MSFT' } });
  fireEvent.change(screen.getByLabelText('Bulk horizon'), { target: { value: 'Annual' } });
  fireEvent.click(screen.getByText('Bulk add'));
  await waitFor(() =>
    expect(api.addStrategyWatchesBulk).toHaveBeenCalledWith(['AAPL', 'MSFT'], 'pullback_ema', 'Bullish', 'Annual'));
});

it('the list shows each watch horizon and hold, or none', async () => {
  render(<StrategyWatchPage />);
  expect(await screen.findByText('Quarterly (60d)')).toBeInTheDocument();
  const msftRow = (await screen.findAllByText('MSFT'))[0].closest('tr')!;
  expect(msftRow.textContent).toContain('None');
});
