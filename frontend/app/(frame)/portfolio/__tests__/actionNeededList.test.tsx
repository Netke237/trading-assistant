import '@testing-library/jest-dom';
import { render, screen, within, fireEvent, act } from '@testing-library/react';
import PortfolioPage from '../page';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { usePortfolioUiStore } from '@/lib/portfolioUiStore';
import { usePerformanceStore } from '@/lib/performanceStore';
import { useAlertEpisodesStore } from '@/lib/alertEpisodesStore';
import { episodeKey } from '@/lib/alertEpisodes';
import type { PortfolioPosition } from '@/types/domain';
import { portfolio20261117 } from '../../../../test-utils/portfolioFixture20261117';

// PORTFOLIO-ALERT-ACTION T4 (#672): the "Action needed" list on the Portfolio page.

jest.mock('@/components/organisms/PnlChart', () => ({ PnlChart: () => null }));
jest.mock('@/components/organisms/PnlHeatmap', () => ({ PnlHeatmap: () => null }));
jest.mock('../EditDrawer', () => ({ EditDrawer: () => <div data-testid="editor-open" /> }));
jest.mock('@/components/organisms/ClosePositionDrawer', () => ({
  ClosePositionDrawer: () => <div data-testid="close-open" />,
}));

function positions(): PortfolioPosition[] {
  const [cmg, nclh, bmy] = portfolio20261117();
  return [
    cmg,
    { ...nclh, dteRemaining: 2 }, // TIME_STOP only
    { ...bmy, stop: 64.13, structuralStop: null, targets: [{ stockPrice: 70 } as never] },
  ];
}

function renderPage(refresh = jest.fn().mockResolvedValue(undefined)) {
  usePortfolioStore.setState({ positions: positions(), syncFromBackend: jest.fn().mockResolvedValue(undefined) });
  usePerformanceStore.setState({
    fetchHistory: jest.fn().mockResolvedValue(undefined),
    fetchPerformance: jest.fn().mockResolvedValue(undefined),
  });
  usePortfolioUiStore.setState({ selectedSymbol: null });
  useAlertEpisodesStore.setState({
    episodes: {
      [episodeKey('REC-BMY', 'STOP_REACHED')]: {
        recId: 'REC-BMY', symbol: 'BMY', alertType: 'STOP_REACHED',
        startedAt: new Date(Date.now() - 9 * 86_400_000 - 3_600_000).toISOString(),
        lastFiredAt: new Date(Date.now() - 3_600_000).toISOString(),
        fireCount: 40, startTruncated: false,
      },
    },
    gapHours: 72, fetchedAt: Date.now(), error: null, refresh,
  });
  return { refresh, ...render(<PortfolioPage />) };
}

afterEach(() => { jest.useRealTimers(); });

describe('Action needed list', () => {
  it('renders the section with one item per position, stop item first with role alert', () => {
    const { refresh } = renderPage();
    expect(refresh).toHaveBeenCalledTimes(1);
    const section = screen.getByRole('region', { name: 'Action needed (2)' });
    const items = Array.from(section.querySelector(':scope > ul')!.children) as HTMLElement[];
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent('BMY');
    expect(items[0]).toHaveTextContent('Stop hit');
    expect(items[0]).toHaveTextContent(/9 days, since \d{1,2} [A-Z][a-z]{2}/);
    expect(within(items[0]).getByRole('alert')).toHaveTextContent('BMY 67C · 19 Mar 27: stop breached.');
    expect(items[1]).toHaveTextContent('NCLH');
    expect(items[1]).toHaveTextContent('Time stop hit');
    expect(items[1]).toHaveTextContent('new — not yet logged');
    expect(within(items[1]).queryByRole('alert')).not.toBeInTheDocument();
    expect(within(section).queryByRole('button', { name: /dismiss/i })).not.toBeInTheDocument();
  });

  it('fetch failure shows "duration unavailable"', () => {
    renderPage();
    act(() => { useAlertEpisodesStore.setState({ error: 'API down' }); });
    const section = screen.getByRole('region', { name: 'Action needed (2)' });
    expect(within(section).getAllByText(/duration unavailable/)).toHaveLength(2);
  });

  it('Review opens the editor for that position', () => {
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Review NCLH' }));
    expect(screen.getByTestId('editor-open')).toBeInTheDocument();
    expect(usePortfolioUiStore.getState().selectedSymbol).toBe('NCLH');
  });

  it('Close position… opens the close drawer', () => {
    renderPage();
    const section = screen.getByRole('region', { name: /Action needed/ });
    fireEvent.click(within(section).getAllByRole('button', { name: 'Close position…' })[0]);
    expect(screen.getByTestId('close-open')).toBeInTheDocument();
  });

  it('Close position… from the History tab switches to the Open tab and opens the drawer', () => {
    renderPage();
    fireEvent.click(screen.getByRole('tab', { name: /^History/ }));
    expect(screen.getByRole('tab', { name: /^History/ })).toHaveAttribute('aria-selected', 'true');
    // The list stays visible on the History tab (no silent removal).
    const section = screen.getByRole('region', { name: 'Action needed (2)' });
    fireEvent.click(within(section).getAllByRole('button', { name: 'Close position…' })[0]);
    expect(screen.getByRole('tab', { name: /^Open/ })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByTestId('close-open')).toBeInTheDocument();
  });

  it('refreshes every 60 s while mounted and stops on unmount', () => {
    jest.useFakeTimers();
    const { refresh, unmount } = renderPage();
    expect(refresh).toHaveBeenCalledTimes(1);
    act(() => { jest.advanceTimersByTime(60_000); });
    expect(refresh).toHaveBeenCalledTimes(2);
    unmount();
    act(() => { jest.advanceTimersByTime(120_000); });
    expect(refresh).toHaveBeenCalledTimes(2);
  });

  it('renders nothing when no position needs action', () => {
    const [cmg] = portfolio20261117();
    renderPage();
    act(() => { usePortfolioStore.setState({ positions: [cmg] }); });
    expect(screen.queryByRole('region', { name: /Action needed/ })).not.toBeInTheDocument();
  });
});
