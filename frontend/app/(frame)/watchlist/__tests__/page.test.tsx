import '@testing-library/jest-dom';
import React from 'react';
import { act, render, screen } from '@testing-library/react';
import WatchlistPage from '../page';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { useWatchedContractsStore } from '@/lib/watchedContractsStore';
import { useWatchlistUiStore } from '@/lib/watchlistUiStore';
import { useChartStore } from '@/lib/chartStore';
import type { WatchlistRow } from '@/types/domain';

const row: WatchlistRow = {
  symbol: 'AAPL', company: 'Apple Inc.', price: 190, direction: 'Bullish', horizon: 'Swing',
  score: 80, rankDelta: 0, status: 'PASS',
  breakdown: { trend: 0, pullback: 0, trigger: 0, event: 0, volatility: 0 },
  nextEventDays: null, nextEventLabel: null,
};

jest.mock('@/lib/api', () => ({
  api: {
    getWatchlist: jest.fn().mockResolvedValue([]),
    listCompositeWatches: jest.fn().mockResolvedValue([]),
    getContracts: jest.fn().mockResolvedValue([]),
  },
}));
import { api } from '@/lib/api';

// Selecting a row opens InlineChartPanel, which renders the real
// CandlestickChart/IndicatorPanel — not under test here. Stub it out; row
// selection is exercised via the store, not the chart it happens to open.
jest.mock('@/components/organisms/InlineChartPanel', () => ({
  InlineChartPanel: () => null,
}));

describe('WatchlistPage — row selection drives the shared UI stores end to end', () => {
  beforeEach(() => {
    useWatchlistStore.setState({ added: [] } as any);
    useWatchedContractsStore.setState({ ids: [] } as any);
    useWatchlistUiStore.setState({ selectedSymbol: null });
    useChartStore.setState({ symbol: '', symbolName: '' } as any);
    (api.getWatchlist as jest.Mock).mockResolvedValue([row]);
  });

  it('clicking a row sets watchlistUiStore.selectedSymbol, and clicking it again clears it', async () => {
    render(<WatchlistPage />);
    const symbolCell = await screen.findByText('AAPL');
    const rowEl = symbolCell.closest('[role="button"]') as HTMLElement;
    expect(rowEl).toBeTruthy();

    await act(async () => { rowEl.click(); });
    expect(useWatchlistUiStore.getState().selectedSymbol).toBe('AAPL');

    await act(async () => { rowEl.click(); });
    expect(useWatchlistUiStore.getState().selectedSymbol).toBeNull();
  });

  it('never logs React\'s cross-component update warning on click (regression: setState-in-updater side effect)', async () => {
    // The warning only fires when another mounted component actually
    // subscribes to watchlistUiStore — verified empirically: rendering
    // WatchlistPage alone (even under StrictMode) never triggers it,
    // because nothing re-renders in response to the store update. In the
    // real app, @contextRail/watchlist/page.tsx is that subscriber, mounted
    // alongside this page via a parallel route. This minimal stand-in
    // mirrors just its subscription, not its full implementation.
    //
    // Also requires StrictMode — verified empirically: reverting onSelect to
    // the old setState-in-updater form still passed this test without it.
    // Next actually runs with reactStrictMode: true in dev (see
    // next.config), so wrapping here is what makes this test able to catch
    // that regression.
    function RailSubscriberStandIn() {
      const symbol = useWatchlistUiStore((s) => s.selectedSymbol);
      return <div data-testid="rail-stand-in">{symbol ?? 'none'}</div>;
    }

    const errorSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
    render(
      <React.StrictMode>
        <WatchlistPage />
        <RailSubscriberStandIn />
      </React.StrictMode>,
    );
    const symbolCell = await screen.findByText('AAPL');
    const rowEl = symbolCell.closest('[role="button"]') as HTMLElement;
    expect(rowEl).toBeTruthy();

    await act(async () => { rowEl.click(); });
    expect(screen.getByTestId('rail-stand-in')).toHaveTextContent('AAPL');

    const badWarning = errorSpy.mock.calls.some((c) =>
      String(c[0]).includes('Cannot update a component')
    );
    expect(badWarning).toBe(false);
    errorSpy.mockRestore();
  });
});
