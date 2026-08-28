import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import ChartContextRail from '../page';
import { useChartStore } from '@/lib/chartStore';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useNotesStore } from '@/lib/notesStore';

jest.mock('@/lib/api', () => ({
  api: {
    getWatchlist: jest.fn().mockResolvedValue([]),
    getDataSources: jest.fn().mockResolvedValue([]),
    getSymbolNote: jest.fn().mockResolvedValue({ symbol: 'AAPL', body: '', updatedAt: null }),
    putSymbolNote: jest.fn().mockResolvedValue({ symbol: 'AAPL', body: '', updatedAt: null }),
  },
}));

// RailQuickLook does its own fetching and isn't under test here.
jest.mock('@/components/organisms/ContextRail/QuickLook', () => ({
  RailQuickLook: () => <div data-testid="rail-quick-look" />,
}));

describe('ChartContextRail', () => {
  beforeEach(() => {
    useChartStore.setState({ symbol: '' });
    useWatchlistStore.setState({ added: [] });
    usePortfolioStore.setState({ positions: [] });
    useNotesStore.setState({ notes: {} });
  });

  // Regression: this segment must be a page.tsx, not a default.tsx — Next's
  // parallel-route router only reliably resolves default.tsx on a hard
  // load, and silently kept rendering the origin page's own rail content
  // when navigating here client-side from Dashboard. This module-resolution
  // test can't catch the routing bug itself, but pins the component's own
  // rendering contract so a future regression at least fails loudly here.
  it('renders no Notes section when no symbol is open', () => {
    render(<ChartContextRail />);
    expect(screen.queryByText(/^Notes/)).not.toBeInTheDocument();
  });

  it('shows an editable note once a symbol is open and watchlisted', async () => {
    useChartStore.setState({ symbol: 'AAPL' });
    useWatchlistStore.setState({ added: ['AAPL'] });
    render(<ChartContextRail />);

    expect(await screen.findByLabelText('Note for AAPL')).toBeInTheDocument();
  });

  it('gates the note editor on the real held/watchlist state', async () => {
    useChartStore.setState({ symbol: 'MSFT' });
    render(<ChartContextRail />);

    expect(await screen.findByText(/star this symbol or open a position/i)).toBeInTheDocument();
    expect(screen.queryByLabelText('Note for MSFT')).not.toBeInTheDocument();
  });
});
