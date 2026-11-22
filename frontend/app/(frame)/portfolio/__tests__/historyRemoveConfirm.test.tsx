import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import PortfolioPage from '../page';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { usePerformanceStore, type ClosedPosition } from '@/lib/performanceStore';
import { useSettingsStore } from '@/lib/settingsStore';

jest.mock('@/components/organisms/PnlChart', () => ({ PnlChart: () => <div data-testid="chart" /> }));
jest.mock('@/components/organisms/PnlHeatmap', () => ({ PnlHeatmap: () => <div data-testid="heatmap" /> }));
jest.mock('@/components/organisms/BrokerAttemptPanel', () => ({ BrokerAttemptPanel: () => null }));
jest.mock('@/lib/alertEngine', () => ({ scanPortfolio: jest.fn().mockReturnValue([]) }));

function row(i: number, symbol: string, contract: string): ClosedPosition {
  return {
    id: `id-${i}`, recId: `rec-${i}`, symbol, contract, direction: 'Bullish',
    entryPrice: 1, entryDate: '2026-06-01', exitPrice: 1, exitDate: '2026-06-30',
    qtyClosed: 1, realizedPnlDollar: -100, realizedPnlPct: -10, closedAt: '2026-06-30T10:00:00Z',
  };
}

const HISTORY = [
  row(0, 'NFLX', 'NFLX|82|2027-01-15|C'),
  row(1, 'NFLX', 'NFLX|STOCK'),
  row(2, 'BRK.B', 'BRK.B|STOCK'),
  row(3, 'A&B', 'A&B|STOCK'),
];

const fetchMock = jest.fn();
const calls = (method?: string) =>
  fetchMock.mock.calls.filter(([, init]) => (method ? init?.method === method : true));

function setup(deleteStatus = 204) {
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (_url: string, init?: { method?: string }) => {
    if (init?.method === 'DELETE') return { ok: deleteStatus < 300, status: deleteStatus, json: async () => ({}) };
    return { ok: true, status: 200, json: async () => ({}) };
  });
  (global as unknown as { fetch: unknown }).fetch = fetchMock;
  useSettingsStore.setState({ premiumStopPct: 0.6 } as never);
  usePortfolioStore.setState({
    positions: [], syncFromBackend: jest.fn().mockResolvedValue(undefined),
    lastSyncAt: 1, lastSyncFailedAt: null, firstSyncAt: 1,
  } as never);
  usePerformanceStore.setState({
    history: HISTORY,
    fetchHistory: jest.fn().mockResolvedValue(undefined),
  } as never);
  render(<PortfolioPage />);
  fireEvent.click(screen.getByRole('tab', { name: /^History/ }));
  fetchMock.mockClear();
}

const removeBtn = (label: string) => screen.getByRole('button', { name: `Remove ${label} from history` });

describe('History remove confirm', () => {
  it('x alone and Cancel issue no request', () => {
    setup();
    fireEvent.click(screen.getAllByRole('button', { name: 'Remove NFLX from history' })[0]);
    expect(screen.getByText('Remove NFLX 82C from history? This changes realized totals.')).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByText(/This changes realized totals/)).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getAllByTestId('history-row')).toHaveLength(4);
  });

  it('shows the stock label', () => {
    setup();
    fireEvent.click(screen.getAllByRole('button', { name: 'Remove NFLX from history' })[1]);
    expect(screen.getByText('Remove NFLX stock from history? This changes realized totals.')).toBeInTheDocument();
  });

  it('Confirm issues one DELETE for that id, then a performance refetch', async () => {
    setup();
    fireEvent.click(screen.getAllByRole('button', { name: 'Remove NFLX from history' })[0]);
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(calls('DELETE')).toHaveLength(1));
    expect(String(calls('DELETE')[0][0])).toMatch(/\/api\/portfolio\/history\/id-0$/);
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => /\/api\/portfolio\/performance/.test(String(u)))).toBe(true));
    const urls = fetchMock.mock.calls.map(([u]) => String(u));
    expect(urls.findIndex((u) => /history\/id-0/.test(u))).toBeLessThan(urls.findIndex((u) => /performance/.test(u)));
    await waitFor(() => expect(screen.getAllByTestId('history-row')).toHaveLength(3));
    expect(screen.queryByText(/This changes realized totals/)).toBeNull();
  });

  it('a failed delete keeps the row, shows the error and does not claim removal', async () => {
    setup(500);
    fireEvent.click(screen.getAllByRole('button', { name: 'Remove NFLX from history' })[0]);
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    expect(await screen.findByText('Could not remove the trade — it is still in your history.')).toBeInTheDocument();
    expect(screen.getAllByTestId('history-row')).toHaveLength(4);
    expect(calls('DELETE')).toHaveLength(1);
  });

  it('only one confirm is open at a time', () => {
    setup();
    fireEvent.click(removeBtn('BRK.B'));
    fireEvent.click(removeBtn('A&B'));
    const dialogs = screen.getAllByText(/This changes realized totals/);
    expect(dialogs).toHaveLength(1);
    expect(dialogs[0]).toHaveTextContent('Remove A&B stock from history?');
  });

  it('closes the confirm when its row leaves the visible list', () => {
    setup();
    fireEvent.click(removeBtn('BRK.B'));
    fireEvent.change(screen.getByRole('textbox', { name: 'Search symbol' }), { target: { value: 'NFLX' } });
    expect(screen.queryByText(/This changes realized totals/)).toBeNull();
  });

  it('links each trade to the journal with an encoded symbol', () => {
    setup();
    const nflx = screen.getAllByRole('link', { name: 'Open journal for NFLX' })[0];
    expect(nflx).toHaveAttribute('href', '/journal?symbol=NFLX');
    expect(nflx).toHaveAttribute('title', 'Open journal for this symbol');
    expect(screen.getByRole('link', { name: 'Open journal for BRK.B' })).toHaveAttribute('href', '/journal?symbol=BRK.B');
    expect(screen.getByRole('link', { name: 'Open journal for A&B' })).toHaveAttribute('href', '/journal?symbol=A%26B');
  });
});
