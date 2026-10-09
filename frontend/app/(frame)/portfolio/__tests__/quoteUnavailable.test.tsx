import '@testing-library/jest-dom';
import { render, screen, within } from '@testing-library/react';
import PortfolioPage from '../page';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { usePerformanceStore } from '@/lib/performanceStore';
import type { PortfolioPosition } from '@/types/domain';

// NO-LIVE-QUOTE NLQ-1 (round-1 F2): GET /api/portfolio flags a position it got
// no quote for. Its 0 currentPrice / P&L are defaults, not a price, so the row
// shows "—" and the footer totals leave it out instead of adding a silent 0.

jest.mock('@/components/organisms/PnlChart', () => ({ PnlChart: () => null }));
jest.mock('@/components/organisms/PnlHeatmap', () => ({ PnlHeatmap: () => null }));

function makePosition(overrides: Partial<PortfolioPosition> = {}): PortfolioPosition {
  return {
    symbol: 'AAPL', contract: 'AAPL|185|2027-01-15|C', direction: 'Bullish',
    entryDate: '2026-08-01', expiry: '2027-01-15', dteRemaining: 98, dteTotal: 140,
    entryPrice: 1.0, currentPrice: 1.2, pnlDollar: 20, pnlPct: 20,
    stop: null, targets: [], status: 'PASS', contracts: 1, recId: 'REC-1',
    ...overrides,
  };
}

function rowOf(contract: string): HTMLElement {
  return screen.getByText(contract).closest('[role="row"]') as HTMLElement;
}

function renderWith(positions: PortfolioPosition[]) {
  usePortfolioStore.setState({ positions, syncFromBackend: jest.fn().mockResolvedValue(undefined) });
  usePerformanceStore.setState({
    fetchHistory: jest.fn().mockResolvedValue(undefined),
    fetchPerformance: jest.fn().mockResolvedValue(undefined),
  });
  return render(<PortfolioPage />);
}

describe('Portfolio open positions without a quote', () => {
  it('renders "—" for price and P&L, not $0.00', () => {
    renderWith([makePosition({
      recId: 'REC-NQ', symbol: 'MSFT', contract: 'MSFT|STOCK',
      currentPrice: 0, pnlDollar: 0, pnlPct: 0, quoteUnavailable: true,
    })]);
    const row = rowOf('MSFT|STOCK');
    expect(within(row).queryByText('$0.00')).not.toBeInTheDocument();
    expect(within(row).queryByText('$0')).not.toBeInTheDocument();
    expect(within(row).queryByText('0.0%')).not.toBeInTheDocument();
    const dashes = within(row).getAllByText('—').filter((el) => el.closest('[title="Quote unavailable"]'));
    expect(dashes).toHaveLength(3);
  });

  it('a quoted row still shows its price and P&L', () => {
    renderWith([makePosition()]);
    const row = rowOf('AAPL|185|2027-01-15|C');
    expect(within(row).getByText('$1.20')).toBeInTheDocument();
    expect(within(row).getByText('+$20')).toBeInTheDocument();
    expect(within(row).getByText('+20.0%')).toBeInTheDocument();
    expect(screen.queryByText(/without a quote/)).not.toBeInTheDocument();
  });

  it('footer totals leave an unquoted row out and say so', () => {
    renderWith([
      makePosition(),
      // A stale client-side mark on the unquoted row (e.g. withServerEntry's
      // reset to the entry) must not reach the totals either.
      makePosition({ recId: 'REC-NQ', symbol: 'MSFT', contract: 'MSFT|STOCK', entryPrice: 400,
                     currentPrice: 400, pnlDollar: -50, pnlPct: -1, quoteUnavailable: true }),
    ]);
    // CSS modules are stubbed in Jest, so the footer is found by its label.
    const footer = screen.getByText('Deployed').parentElement!.parentElement!;
    expect(within(footer).getByText('$120')).toBeInTheDocument();     // 1.20 x 100 only
    expect(within(footer).getByText('+$20')).toBeInTheDocument();
    expect(within(footer).getByText('Excludes 1 position without a quote')).toBeInTheDocument();
  });
});
