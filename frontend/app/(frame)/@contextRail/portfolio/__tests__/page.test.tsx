import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import PortfolioContextRail from '../page';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { usePortfolioUiStore } from '@/lib/portfolioUiStore';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { useNotesStore } from '@/lib/notesStore';
import type { PortfolioPosition } from '@/types/domain';

jest.mock('@/lib/api', () => ({
  api: {
    getSymbolNote: jest.fn().mockResolvedValue({ symbol: 'AAPL', body: '', updatedAt: null }),
    putSymbolNote: jest.fn().mockResolvedValue({ symbol: 'AAPL', body: '', updatedAt: null }),
  },
}));

// RailQuickLook fetches watchlist/data-sources on its own and isn't the
// thing under test here — stub it so this suite stays focused on
// PortfolioContextRail's own gating logic, and so the `showPortfolio` prop
// it's called with is directly observable.
jest.mock('@/components/organisms/ContextRail/QuickLook', () => ({
  RailQuickLook: (props: { showPortfolio?: boolean }) => (
    <div data-testid="rail-quick-look" data-show-portfolio={String(props.showPortfolio)} />
  ),
}));

function makePosition(overrides: Partial<PortfolioPosition> = {}): PortfolioPosition {
  return {
    symbol: 'AAPL', contract: 'AAPL|STOCK', direction: 'Bullish',
    entryDate: '2026-08-01', expiry: '', dteRemaining: 0, dteTotal: 0,
    entryPrice: 190, currentPrice: 195, pnlDollar: 50, pnlPct: 2.6,
    stop: 182, targets: [], status: 'PASS', contracts: 10, recId: 'REC-1',
    ...overrides,
  };
}

describe('PortfolioContextRail', () => {
  beforeEach(() => {
    usePortfolioStore.setState({ positions: [] });
    usePortfolioUiStore.setState({ selectedSymbol: null });
    useWatchlistStore.setState({ added: [] });
    useNotesStore.setState({ notes: {} });
  });

  it('passes showPortfolio={false} to RailQuickLook, so the Portfolio totals never render twice', () => {
    render(<PortfolioContextRail />);
    expect(screen.getByTestId('rail-quick-look')).toHaveAttribute('data-show-portfolio', 'false');
  });

  it('renders no Notes section when nothing is selected', () => {
    render(<PortfolioContextRail />);
    expect(screen.queryByText(/^Notes/)).not.toBeInTheDocument();
  });

  it('gates the note editor on the real held/watchlist state, not on "a symbol is selected"', async () => {
    // Regression: selectedSymbol used to be trusted at face value, with no
    // check against whether the symbol is actually still held or
    // watchlisted — an out-of-band position close (another tab, a
    // stop-triggered close reconciled by the 30s portfolio poll) could leave
    // selectedSymbol pointing at a symbol the note should no longer be
    // editable for.
    usePortfolioUiStore.setState({ selectedSymbol: 'MSFT' });
    // Not in positions, not watchlisted.
    render(<PortfolioContextRail />);

    expect(await screen.findByText(/star this symbol or open a position/i)).toBeInTheDocument();
    expect(screen.queryByLabelText('Note for MSFT')).not.toBeInTheDocument();
  });

  it('shows an editable note for a selected symbol that is genuinely held', async () => {
    usePortfolioStore.setState({ positions: [makePosition({ symbol: 'AAPL' })] });
    usePortfolioUiStore.setState({ selectedSymbol: 'AAPL' });
    render(<PortfolioContextRail />);

    expect(await screen.findByLabelText('Note for AAPL')).toBeInTheDocument();
  });

  it('shows an editable note for a selected symbol that is only watchlisted (not held)', async () => {
    useWatchlistStore.setState({ added: ['TSLA'] });
    usePortfolioUiStore.setState({ selectedSymbol: 'TSLA' });
    render(<PortfolioContextRail />);

    expect(await screen.findByLabelText('Note for TSLA')).toBeInTheDocument();
  });
});
