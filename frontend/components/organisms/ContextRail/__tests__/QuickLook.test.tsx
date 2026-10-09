import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import { RailQuickLook } from '../QuickLook';
import { usePortfolioStore } from '@/lib/portfolioStore';
import type { PortfolioPosition } from '@/types/domain';

// NO-LIVE-QUOTE NLQ-1 (round-1 F2): a position GET /api/portfolio got no quote
// for carries 0 defaults, not a price. The rail's Portfolio totals leave it
// out and say so, the same way the Portfolio footer does.

jest.mock('@/lib/api', () => ({
  api: {
    getWatchlist: jest.fn().mockResolvedValue([]),
    getDataSources: jest.fn().mockResolvedValue([]),
  },
}));

function makePosition(overrides: Partial<PortfolioPosition> = {}): PortfolioPosition {
  return {
    symbol: 'AAPL', contract: 'AAPL|185|2027-01-15|C', direction: 'Bullish',
    entryDate: '2026-08-01', expiry: '2027-01-15', dteRemaining: 98, dteTotal: 140,
    entryPrice: 1.0, currentPrice: 1.2, pnlDollar: 20, pnlPct: 20,
    stop: null, targets: [], status: 'PASS', contracts: 1, recId: 'REC-1',
    ...overrides,
  };
}

function rowValue(label: string): string {
  return screen.getByText(label).parentElement!.textContent!.replace(label, '');
}

describe('RailQuickLook portfolio totals', () => {
  beforeEach(() => {
    usePortfolioStore.setState({ syncFromBackend: jest.fn().mockResolvedValue(undefined) });
  });

  it('leaves a position without a quote out of the totals and says so', () => {
    usePortfolioStore.setState({ positions: [
      makePosition(),
      // A stale client-side mark must not reach the totals either.
      makePosition({ recId: 'REC-NQ', symbol: 'MSFT', contract: 'MSFT|STOCK', entryPrice: 400,
                     currentPrice: 400, pnlDollar: -50, pnlPct: -1, quoteUnavailable: true }),
    ] });
    render(<RailQuickLook />);
    expect(rowValue('Positions')).toBe('2');
    expect(rowValue('Deployed')).toBe('$120');
    expect(rowValue('Open P&L')).toBe('+$20');
    expect(rowValue('Winners')).toBe('1 / 1');
    expect(screen.getByText('Excludes 1 position without a quote')).toBeInTheDocument();
  });

  it('shows no note when every position has a quote', () => {
    usePortfolioStore.setState({ positions: [makePosition()] });
    render(<RailQuickLook />);
    expect(rowValue('Deployed')).toBe('$120');
    expect(screen.queryByText(/without a quote/)).not.toBeInTheDocument();
  });
});
