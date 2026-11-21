import '@testing-library/jest-dom';
import { render, screen, act } from '@testing-library/react';
import PortfolioPage from '../page';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { usePerformanceStore } from '@/lib/performanceStore';
import { hhmmss } from '@/lib/configHealth';
import type { PortfolioPosition } from '@/types/domain';

jest.mock('@/components/organisms/PnlChart', () => ({ PnlChart: () => null }));
jest.mock('@/components/organisms/PnlHeatmap', () => ({ PnlHeatmap: () => null }));
jest.mock('@/lib/alertEngine', () => ({ scanPortfolio: jest.fn().mockReturnValue([]) }));

function pos(): PortfolioPosition {
  return {
    symbol: 'AAPL', contract: 'AAPL|185|2027-01-15|C', direction: 'Bullish',
    entryDate: '2026-08-01', expiry: '2027-01-15', dteRemaining: 98, dteTotal: 140,
    entryPrice: 1.0, currentPrice: 1.2, pnlDollar: 20, pnlPct: 20,
    stop: null, targets: [], status: 'PASS', contracts: 1, recId: 'REC-1',
  };
}

const T1 = new Date(2026, 10, 21, 17, 42, 10).getTime();
const T2 = new Date(2026, 10, 21, 17, 42, 40).getTime();

let releaseSync: (v: boolean) => void;
function setup(positions: PortfolioPosition[], stamps: Record<string, number | null> = {}, pending = false) {
  const sync = jest.fn().mockImplementation(() =>
    pending ? new Promise<boolean>((r) => { releaseSync = r; }) : Promise.resolve(undefined));
  usePortfolioStore.setState({
    positions, syncFromBackend: sync,
    lastSyncAt: null, lastSyncFailedAt: null, firstSyncAt: null, ...stamps,
  } as never);
  usePerformanceStore.setState({
    fetchHistory: jest.fn().mockResolvedValue(undefined),
    fetchPerformance: jest.fn().mockResolvedValue(undefined),
  } as never);
  return render(<PortfolioPage />);
}

describe('Portfolio sync state', () => {
  it('shows "Syncing positions…" until the first sync lands, then the real empty text', async () => {
    setup([], {}, true);
    expect(screen.getByText('Syncing positions…')).toBeInTheDocument();
    expect(screen.queryByText('No open positions.')).not.toBeInTheDocument();
    expect(screen.getByText('Syncing…')).toBeInTheDocument();
    await act(async () => {
      usePortfolioStore.setState({ lastSyncAt: T1, firstSyncAt: T1 } as never);
      releaseSync(true);
    });
    expect(screen.queryByText('Syncing positions…')).not.toBeInTheDocument();
    expect(screen.getByText('No open positions.')).toBeInTheDocument();
  });

  it('an empty list with a failed first sync says so and not "No open positions."', () => {
    setup([], { lastSyncFailedAt: T2 });
    expect(screen.getByText(`Could not load positions. Last sync failed ${hhmmss(T2)}.`)).toBeInTheDocument();
    expect(screen.queryByText('No open positions.')).not.toBeInTheDocument();
    expect(screen.queryByText('Syncing positions…')).not.toBeInTheDocument();
  });

  it('rows restored from localStorage render during the first sync', () => {
    setup([pos()], {}, true);
    expect(screen.getByTitle('AAPL|185|2027-01-15|C')).toBeInTheDocument();
    expect(screen.queryByText('Syncing positions…')).not.toBeInTheDocument();
  });

  it('status line: ok', () => {
    setup([pos()], { lastSyncAt: T1, firstSyncAt: T1 });
    expect(screen.getByText(`Synced ${hhmmss(T1)} · refreshes every 30 s, paused while this tab is hidden`))
      .toBeInTheDocument();
    expect(screen.queryByRole('status', { name: /Last sync failed/ })).not.toBeInTheDocument();
  });

  it('status line: failed with a prior success names the last success, role=status', () => {
    setup([pos()], { lastSyncAt: T1, firstSyncAt: T1, lastSyncFailedAt: T2 });
    const el = screen.getByText(`Last sync failed ${hhmmss(T2)}, showing ${hhmmss(T1)}`);
    expect(el.closest('[role="status"]')).not.toBeNull();
  });

  it('status line: failed with no prior success', () => {
    setup([pos()], { lastSyncFailedAt: T2 });
    expect(screen.getByText(`Last sync failed ${hhmmss(T2)}, showing positions saved in this browser`))
      .toBeInTheDocument();
  });

  it('the failure line clears after a later success', () => {
    setup([pos()], { lastSyncAt: T1, firstSyncAt: T1, lastSyncFailedAt: T2 });
    act(() => { usePortfolioStore.setState({ lastSyncAt: T2 + 30_000 } as never); });
    expect(screen.queryByText(/Last sync failed/)).not.toBeInTheDocument();
    expect(screen.getByText(`Synced ${hhmmss(T2 + 30_000)} · refreshes every 30 s, paused while this tab is hidden`))
      .toBeInTheDocument();
  });
});
