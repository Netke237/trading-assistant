import '@testing-library/jest-dom';
import { act, render, screen } from '@testing-library/react';
import WatchlistContextRail from '../page';
import { useChartStore } from '@/lib/chartStore';
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
    useChartStore.setState({ symbol: '' });
    useWatchlistStore.setState({ added: [] });
    usePortfolioStore.setState({ positions: [] });
    useNotesStore.setState({ notes: {} });
  });

  it('renders no Notes section when no symbol has been selected on the page', async () => {
    render(<WatchlistContextRail />);
    // Let the component's own getWatchlist() effect resolve before asserting,
    // so its state update lands inside act() instead of logging a warning.
    await act(async () => {});
    expect(screen.queryByText(/^Notes/)).not.toBeInTheDocument();
  });

  it('gates the note editor on the real held/watchlist state, not on "a symbol is in the chart store"', async () => {
    // A symbol left over in chartStore from an earlier chart visit that is
    // neither watchlisted nor held must not render an editable note.
    useChartStore.setState({ symbol: 'MSFT' });
    render(<WatchlistContextRail />);

    expect(await screen.findByText(/star this symbol or open a position/i)).toBeInTheDocument();
    expect(screen.queryByLabelText('Note for MSFT')).not.toBeInTheDocument();
  });

  it('shows an editable note for the selected symbol when it is watchlisted', async () => {
    useChartStore.setState({ symbol: 'AAPL' });
    useWatchlistStore.setState({ added: ['AAPL'] });
    render(<WatchlistContextRail />);

    expect(await screen.findByLabelText('Note for AAPL')).toBeInTheDocument();
  });
});
