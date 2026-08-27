import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import { SendToBrokerDialog } from '@/components/organisms/SendToBrokerDialog';
import type { TradeCardData } from '@/types/domain';

function makeCard(overrides: Partial<TradeCardData> & { symbol: string }): TradeCardData {
  return {
    company: `${overrides.symbol} Inc.`,
    price: 100,
    direction: 'Bullish',
    status: 'PASS',
    stockScore: 80,
    stockConfidence: 'PASS',
    stockBreakdown: { trend: 80, pullback: 80, trigger: 80, event: 80, volatility: 80 },
    contract: `${overrides.symbol} 100C 05/15`,
    contractScore: 70,
    contractConfidence: 'PASS',
    contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 60 },
    contractDetails: { strike: 100, expiry: '2026-05-15', right: 'C', mid: 50, delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 },
    entry: { limit: 50, maxFill: 51, orderType: 'Limit' },
    exit: {
      // A positive invalidation avoids the 'missing_invalidation' early return,
      // which renders a different message entirely and would short-circuit
      // before the worst-offender max-loss block is ever reached.
      invalidation: 90, premiumStop: 40, timeStopDays: 10, target: 130, targets: [],
      exitPlan: {
        computedAt: '2026-08-27T00:00:00.000Z',
        stop: {
          price: 90, source: 'structural', contractPrice: 1,
          rrModel: 'BS repriced (IV-derived)', structuralSource: 'swing_low', structuralConfidence: 0.8,
        },
        targets: [],
        atr: 3,
      },
    },
    rrRatio: 2.0,
    rrModel: 'BS repriced (IV-derived)',
    finalStatus: 'PASS',
    ...overrides,
  };
}

describe('SendToBrokerDialog risk summary — max-loss worst offender', () => {
  const noop = () => {};

  it('names the symbol with the largest loss at stop across the basket, not the first one pinned', () => {
    // Both exceed the $3,750 default limit (portfolioValue 100000 *
    // maxLossPerTradePct 0.0375), but BBB's is far worse. AAA is pinned
    // first in the basket — the detail line must still name BBB.
    const aaa = makeCard({
      symbol: 'AAA',
      contractDetails: { strike: 100, expiry: '2026-05-15', right: 'C', mid: 50, delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 },
      // lossAtStop = (50 - 1) * 100 * 1 = $4,900
    });
    const bbb = makeCard({
      symbol: 'BBB',
      contractDetails: { strike: 100, expiry: '2026-05-15', right: 'C', mid: 100, delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 },
      // lossAtStop = (100 - 1) * 100 * 1 = $9,900
    });

    render(<SendToBrokerDialog cards={[aaa, bbb]} onClose={noop} onSubmit={noop} />);

    expect(screen.getByText(/Max loss at stop \(BBB\) ≈ \$9,900 \(limit \$3,750\)/)).toBeInTheDocument();
    expect(screen.queryByText(/Max loss at stop \(AAA\)/)).not.toBeInTheDocument();
  });

  it('shows "Within risk limits" when neither position exceeds the max-loss limit', () => {
    const aaa = makeCard({
      symbol: 'AAA',
      contractDetails: { strike: 100, expiry: '2026-05-15', right: 'C', mid: 2, delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 },
      exit: {
        invalidation: 90, premiumStop: 1.5, timeStopDays: 10, target: 130, targets: [],
        exitPlan: {
          computedAt: '2026-08-27T00:00:00.000Z',
          stop: {
            price: 90, source: 'structural', contractPrice: 1.5,
            rrModel: 'BS repriced (IV-derived)', structuralSource: 'swing_low', structuralConfidence: 0.8,
          },
          targets: [],
          atr: 3,
        },
      },
      // lossAtStop = (2 - 1.5) * 100 * 1 = $50, well within the $3,750 limit.
    });

    render(<SendToBrokerDialog cards={[aaa]} onClose={noop} onSubmit={noop} />);

    expect(screen.getByText('Within risk limits.')).toBeInTheDocument();
  });
});
