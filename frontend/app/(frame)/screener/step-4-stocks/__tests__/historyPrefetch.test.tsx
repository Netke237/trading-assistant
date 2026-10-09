import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { HistoryPrefetchRow } from '../HistoryPrefetchRow';
import { useScanStore } from '@/lib/scanStore';
import { api, getLastDataRefresh } from '@/lib/api';

jest.mock('@/lib/api', () => ({
  api: { startHistoryPrefetch: jest.fn(() => Promise.resolve()), getHistoryPrefetchStatus: jest.fn() },
  getLastDataRefresh: jest.fn(() => Promise.resolve({ last_refresh: '2026-10-03T22:00:00Z' })),
  API_BASE_URL: 'http://localhost:8000',
}));

beforeEach(() => {
  // No clearMocks in the jest config: without this, test 1's two status polls
  // are still recorded when test 2 asserts none happened.
  jest.clearAllMocks();
  jest.useFakeTimers();
  useScanStore.setState({ context: { universe: 'NDX100', direction: 'Bullish', horizon: 'Swing (5–15d)' } } as never);
});
afterEach(() => jest.useRealTimers());

it('shows not pre-warmed and the last refresh, then warms the context universe and polls to ready', async () => {
  (api.getHistoryPrefetchStatus as jest.Mock)
    .mockResolvedValueOnce({ status: 'running', done: 3, total: 100 })
    .mockResolvedValueOnce({ status: 'completed', done: 100, total: 100 });
  render(<HistoryPrefetchRow />);
  expect(screen.getByText(/not pre-warmed/)).toBeInTheDocument();
  await waitFor(() => expect(screen.getByText(/Last refresh:/)).toBeInTheDocument());
  expect(getLastDataRefresh).toHaveBeenCalledTimes(1);

  fireEvent.click(screen.getByRole('button', { name: 'Pre-warm history' }));
  await waitFor(() => expect(api.startHistoryPrefetch).toHaveBeenCalledWith({ universe: ['NDX100'] }));
  await act(async () => { jest.advanceTimersByTime(5_000); });
  expect(await screen.findByText(/warming up 3\/100/)).toBeInTheDocument();
  await act(async () => { jest.advanceTimersByTime(5_000); });
  expect(await screen.findByText(/Historical data:.*ready/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Re-warm' })).toBeInTheDocument();
});

it('stops polling on unmount', async () => {
  (api.getHistoryPrefetchStatus as jest.Mock).mockResolvedValue({ status: 'running', done: 1, total: 9 });
  const { unmount } = render(<HistoryPrefetchRow />);
  fireEvent.click(screen.getByRole('button', { name: 'Pre-warm history' }));
  await waitFor(() => expect(api.startHistoryPrefetch).toHaveBeenCalled());
  unmount();
  await act(async () => { jest.advanceTimersByTime(20_000); });
  expect(api.getHistoryPrefetchStatus).not.toHaveBeenCalled();
});
