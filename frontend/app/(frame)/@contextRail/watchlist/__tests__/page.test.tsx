import '@testing-library/jest-dom';
import { act, render, screen } from '@testing-library/react';
import WatchlistContextRail from '../page';
import { useWatchlistUiStore } from '@/lib/watchlistUiStore';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useNotesStore } from '@/lib/notesStore';

jest.mock('@/lib/api', () => ({
  api: {
    getWatchlist: jest.fn().mockResolvedValue([]),
    getSymbolNote: jest.fn().mockResolvedValue({ symbol: 'AAPL', body: '', updatedAt: null }),
    putSymbolNote: jest.fn().mockResolvedValue({ symbol: 'AAPL', body: '', updatedAt: null }),
    getDataSources: jest.fn().mockResolvedValue([]),
  },
}));

// RailQuickLook does its own fetching and isn't under test here.
jest.mock('@/components/organisms/ContextRail/QuickLook', () => ({
  RailQuickLook: () => <div data-testid="rail-quick-look" />,
}));

describe('WatchlistContextRail', () => {
  beforeEach(() => {
    // watchlistUiStore's default (selectedSymbol: null) is the real "no row
    // clicked yet" state the app starts in — unlike chartStore, it isn't
    // persisted and doesn't default to a real symbol, so this reset actually
    // matches a fresh page load rather than an unreachable fictional state.
    useWatchlistUiStore.setState({ selectedSymbol: null });
    useWatchlistStore.setState({ added: [] });
    usePortfolioStore.setState({ positions: [] });
    useNotesStore.setState({ notes: {} });
  });

  it('renders no Notes section on a fresh page load, before any row is clicked', async () => {
    render(<WatchlistContextRail />);
    // Let the component's own getWatchlist() effect resolve before asserting,
    // so its state update lands inside act() instead of logging a warning.
    await act(async () => {});
    expect(screen.queryByText(/^Notes/)).not.toBeInTheDocument();
  });

  it('gates the note editor on the real held/watchlist state, not on "a row is selected"', async () => {
    useWatchlistUiStore.setState({ selectedSymbol: 'MSFT' });
    render(<WatchlistContextRail />);

    expect(await screen.findByText(/star this symbol or open a position/i)).toBeInTheDocument();
    expect(screen.queryByLabelText('Note for MSFT')).not.toBeInTheDocument();
  });

  it('shows an editable note for the selected row when it is watchlisted', async () => {
    useWatchlistUiStore.setState({ selectedSymbol: 'AAPL' });
    useWatchlistStore.setState({ added: ['AAPL'] });
    render(<WatchlistContextRail />);

    expect(await screen.findByLabelText('Note for AAPL')).toBeInTheDocument();
  });

  it('hides the Notes section again once the row is deselected', async () => {
    useWatchlistUiStore.setState({ selectedSymbol: 'AAPL' });
    useWatchlistStore.setState({ added: ['AAPL'] });
    const { rerender } = render(<WatchlistContextRail />);
    expect(await screen.findByLabelText('Note for AAPL')).toBeInTheDocument();

    act(() => { useWatchlistUiStore.setState({ selectedSymbol: null }); });
    rerender(<WatchlistContextRail />);
    expect(screen.queryByText(/^Notes/)).not.toBeInTheDocument();
  });
});
