import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import AnalysisContextRail from '../page';
import { useAnalysisStore } from '@/lib/analysisStore';
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

describe('AnalysisContextRail', () => {
  beforeEach(() => {
    useAnalysisStore.setState({ symbol: '', result: null, loading: false, error: null });
    useWatchlistStore.setState({ added: [] });
    usePortfolioStore.setState({ positions: [] });
    useNotesStore.setState({ notes: {} });
  });

  it('renders no Notes section when no symbol has been analyzed', () => {
    render(<AnalysisContextRail />);
    expect(screen.queryByText(/^Notes/)).not.toBeInTheDocument();
  });

  it('shows an editable note once a symbol is loaded and watchlisted', async () => {
    useAnalysisStore.setState({ symbol: 'AAPL' });
    useWatchlistStore.setState({ added: ['AAPL'] });
    render(<AnalysisContextRail />);

    expect(await screen.findByLabelText('Note for AAPL')).toBeInTheDocument();
  });

  it('gates the note editor on the real held/watchlist state', async () => {
    useAnalysisStore.setState({ symbol: 'MSFT' });
    render(<AnalysisContextRail />);

    expect(await screen.findByText(/star this symbol or open a position/i)).toBeInTheDocument();
    expect(screen.queryByLabelText('Note for MSFT')).not.toBeInTheDocument();
  });
});
