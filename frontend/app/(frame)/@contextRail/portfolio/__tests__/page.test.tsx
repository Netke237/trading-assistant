import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import PortfolioContextRail from '../page';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { usePortfolioUiStore } from '@/lib/portfolioUiStore';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { useNotesStore } from '@/lib/notesStore';
import type { PortfolioPosition } from '@/types/domain';
import { portfolio20261117 } from '../../../../../test-utils/portfolioFixture20261117';

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

// PORTFOLIO-NUMBERS T2 (#657): the rail's money and greeks in consistent
// units. Fixture: the three live positions of 2026-11-17 (plan §2).
describe('PortfolioContextRail — numbers (PORTFOLIO-NUMBERS)', () => {
  // The value cell sits beside its label inside the same row <div>.
  function rowValue(label: string): string {
    const row = screen.getByText(label).parentElement as HTMLElement;
    return (row.textContent ?? '').slice(label.length);
  }

  beforeEach(() => {
    usePortfolioStore.setState({ positions: portfolio20261117() });
    usePortfolioUiStore.setState({ selectedSymbol: null });
    useWatchlistStore.setState({ added: [] });
    useNotesStore.setState({ notes: {} });
  });

  it('labels delta as share-equivalent and keeps its number', () => {
    render(<PortfolioContextRail />);
    expect(rowValue('Δ Delta (share-equiv.)')).toBe('92.32');
  });

  it('shows delta in dollars, with a note for the position it leaves out', () => {
    render(<PortfolioContextRail />);
    expect(rowValue('Δ in dollars')).toBe('$2,451');
    expect(screen.getByText('Δ in dollars excludes 1 position without delta or underlying price')).toBeInTheDocument();
  });

  it('shows theta in dollars per day (× 100 per contract), not per share', () => {
    render(<PortfolioContextRail />);
    expect(rowValue('Θ Theta / day')).toBe('−$1.81');
  });

  it('formats Deployed and Open P&L as money, and keeps the unquoted note', () => {
    render(<PortfolioContextRail />);
    expect(rowValue('Deployed')).toBe('$494');
    expect(rowValue('Open P&L')).toBe('−$37');
    expect(screen.getByText('Excludes 1 position without a quote')).toBeInTheDocument();
  });

  it('shows — for all three greeks and no delta-dollars note when no position has greeks', () => {
    usePortfolioStore.setState({
      positions: portfolio20261117().map((p) => ({ ...p, delta: undefined, theta: undefined })),
    });
    render(<PortfolioContextRail />);
    expect(rowValue('Δ Delta (share-equiv.)')).toBe('—');
    expect(rowValue('Δ in dollars')).toBe('—');
    expect(rowValue('Θ Theta / day')).toBe('—');
    expect(screen.queryByText(/^Δ in dollars excludes/)).not.toBeInTheDocument();
  });
});
