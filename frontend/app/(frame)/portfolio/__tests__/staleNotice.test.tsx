import '@testing-library/jest-dom';
import { render, screen, act, fireEvent } from '@testing-library/react';
import PortfolioPage from '../page';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { usePerformanceStore, type Performance } from '@/lib/performanceStore';
import { portfolio20261117 } from '../../../../test-utils/portfolioFixture20261117';

// The chart is replaced by a probe that prints the notice for its default curve, so the
// page's wiring (what it computes and passes) is what is asserted.
jest.mock('@/components/organisms/PnlChart', () => ({
  PnlChart: ({ defaultKind, staleNotices }: { defaultKind: 'open' | 'equity' | 'realized'; staleNotices?: Record<string, { text: string } | null> }) => {
    const n = defaultKind === 'realized' ? null : staleNotices?.[defaultKind] ?? null;
    return <p data-testid={`probe-${defaultKind}`}>{n ? n.text : 'no notice'}</p>;
  },
}));
jest.mock('@/components/organisms/PnlHeatmap', () => ({ PnlHeatmap: () => null }));
jest.mock('@/lib/alertEngine', () => ({ scanPortfolio: jest.fn().mockReturnValue([]) }));

const NOW = new Date('2026-11-21T15:00:00Z'); // Saturday: reference day Fri 2026-11-20
const FIRST = NOW.getTime() - 60_000;

const PERF: Performance = {
  realizedToday: 0, realizedWeek: 0, realizedMonth: 0, realizedYear: 0,
  realizedCurve: [{ date: '2026-10-23', value: 3 }],
  equityCurve: [{ date: '2026-10-22', value: 10000 }, { date: '2026-10-23', value: 11530 }],
  openPnlCurve: [{ date: '2026-10-22', value: 900 }, { date: '2026-10-23', value: 1530 }],
  lastSnapshotDate: '2026-10-23',
  snapshotSkippedOn: '2026-11-17',
  snapshotSkippedContracts: ['BMY|67|2027-03-19|C'],
};

function setup(over: { positions?: ReturnType<typeof portfolio20261117>; perf?: Partial<Performance>; fetchedAt?: number | null; firstSyncAt?: number | null } = {}) {
  usePortfolioStore.setState({
    positions: over.positions ?? portfolio20261117(),
    syncFromBackend: jest.fn().mockResolvedValue(undefined),
    lastSyncAt: FIRST, lastSyncFailedAt: null,
    firstSyncAt: over.firstSyncAt === undefined ? FIRST : over.firstSyncAt,
  } as never);
  usePerformanceStore.setState({
    performance: { ...PERF, ...over.perf },
    fetchedAt: over.fetchedAt === undefined ? FIRST + 1000 : over.fetchedAt,
    history: [],
    fetchHistory: jest.fn().mockResolvedValue(undefined),
    fetchPerformance: jest.fn().mockResolvedValue(undefined),
  } as never);
  return render(<PortfolioPage />);
}

describe('Portfolio stale-curve notice wiring (T4)', () => {
  beforeEach(() => { jest.useFakeTimers(); jest.setSystemTime(NOW); });
  afterEach(() => { jest.useRealTimers(); });

  it('2026-11-17 fixture gives the sample sentence verbatim, and its "today" equals the footer Open P&L', async () => {
    setup();
    await act(async () => { await Promise.resolve(); });
    const text = screen.getByTestId('probe-open').textContent!;
    expect(text).toBe('Last point: 23 Oct, +$1,530. Open P&L today is −$37. No daily snapshot is written while a position has no quote (BMY now), so the line has stopped.');
    const footer = screen.getByText('Open P&L').parentElement!;
    expect(footer).toHaveTextContent('−$37');
  });

  it('with no skipped contracts the unquoted symbols of the table are named', async () => {
    setup({ perf: { snapshotSkippedContracts: [] } });
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByTestId('probe-open').textContent).toContain('(BMY now)');
  });

  it('not ready: performance issued before the first sync, or no first sync, shows no notice', async () => {
    const { unmount } = setup({ fetchedAt: FIRST - 1 });
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByTestId('probe-open')).toHaveTextContent('no notice');
    unmount();
    setup({ firstSyncAt: null });
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByTestId('probe-open')).toHaveTextContent('no notice');
  });

  it('no open positions: no notice', async () => {
    setup({ positions: [] });
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByTestId('probe-open')).toHaveTextContent('no notice');
  });

  it('a snapshot on the reference day: no notice', async () => {
    setup({ perf: { lastSnapshotDate: '2026-11-20', openPnlCurve: [{ date: '2026-11-20', value: 5 }] } });
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByTestId('probe-open')).toHaveTextContent('no notice');
  });

  it('the History tab chart (realized) never gets a notice', async () => {
    setup();
    await act(async () => { await Promise.resolve(); });
    fireEvent.click(screen.getByRole('tab', { name: /History/ }));
    expect(screen.getByTestId('probe-realized')).toHaveTextContent('no notice');
  });
});
