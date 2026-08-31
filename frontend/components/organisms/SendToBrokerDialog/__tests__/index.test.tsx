import '@testing-library/jest-dom';
import { render, screen, act } from '@testing-library/react';
import { SendToBrokerDialog } from '@/components/organisms/SendToBrokerDialog';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useRiskStore } from '@/lib/riskStore';
import type { TradeCardData } from '@/types/domain';

// Reset the real (unmocked) stores this dialog reads from — same convention
// as StockSendDialog.test.tsx — so an empty portfolio and the account
// default risk limits are guaranteed regardless of test run order or what
// another suite may have left in them.
beforeEach(() => {
  act(() => {
    usePortfolioStore.setState({ positions: [] });
    useRiskStore.setState({
      limits: {
        maxSingleTradeExposurePct: 0.05,
        maxTotalExposurePct: 0.25,
        maxConcurrentPositions: 10,
        maxDailyRecommendations: 5,
        portfolioValue: 100000,
        maxLossPerTradePct: 0.0375,
      },
      dailyRecommendations: 0,
    });
  });
});

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
          structuralPrice: 90, atrFloorPrice: 85, distanceDollar: 5,
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
    // Both cards share the same mid (50) and 1 contract, so
    // capitalAtRisk/exposure is identical and at the maxSingleTradeExposurePct
    // boundary (5000/100000 = 5%, not > 0.05) for both — the only gate either
    // trips is max_loss_per_trade_exceeded, isolating exactly the behavior
    // under test. They differ only in the exit-plan stop's contract price,
    // which is what makes AAA's and BBB's loss at stop differ. AAA is pinned
    // first in the basket — the detail line must still name BBB, the worse
    // of the two, not the first match in insertion order.
    const aaa = makeCard({
      symbol: 'AAA',
      exit: {
        invalidation: 90, premiumStop: 40, timeStopDays: 10, target: 130, targets: [],
        exitPlan: {
          computedAt: '2026-08-27T00:00:00.000Z',
          stop: {
            price: 90, source: 'structural', contractPrice: 10,
            rrModel: 'BS repriced (IV-derived)', structuralSource: 'swing_low', structuralConfidence: 0.8,
            structuralPrice: 90, atrFloorPrice: 85, distanceDollar: 5,
          },
          targets: [],
          atr: 3,
        },
      },
      // lossAtStop = (50 - 10) * 100 * 1 = $4,000
    });
    const bbb = makeCard({
      symbol: 'BBB',
      // exit.exitPlan.stop.contractPrice: 1 (from makeCard's default)
      // lossAtStop = (50 - 1) * 100 * 1 = $4,900
    });

    render(<SendToBrokerDialog cards={[aaa, bbb]} contractsBySymbol={{}} overridesBySymbol={{}} onClose={noop} onSubmit={noop} />);

    expect(screen.queryByText('Single trade exposure too high')).not.toBeInTheDocument();
    expect(screen.getByText(/Max loss at stop \(BBB\) ≈ \$4,900 \(limit \$3,750\)/)).toBeInTheDocument();
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
            structuralPrice: 90, atrFloorPrice: 85, distanceDollar: 5,
          },
          targets: [],
          atr: 3,
        },
      },
      // lossAtStop = (2 - 1.5) * 100 * 1 = $50, well within the $3,750 limit.
    });

    render(<SendToBrokerDialog cards={[aaa]} contractsBySymbol={{}} overridesBySymbol={{}} onClose={noop} onSubmit={noop} />);

    expect(screen.getByText('Within risk limits.')).toBeInTheDocument();
  });

  it('Feature 5 — an active pre-trade max-loss override avoids a spurious extra-confirmation click', () => {
    // Same shape as the worst-offender BBB case above: lossAtStop =
    // (50 - 1) * 100 * 1 = $4,900, which exceeds the $3,750 ACCOUNT-DEFAULT
    // limit — without the override this would show a warning and force a
    // second "Submit" click. A $5,000 override raises the limit above the
    // $4,900 loss, so the dialog must read straight through as clean.
    const bbb = makeCard({ symbol: 'BBB' });

    const { rerender } = render(
      <SendToBrokerDialog cards={[bbb]} contractsBySymbol={{}} overridesBySymbol={{}} onClose={noop} onSubmit={noop} />,
    );
    expect(screen.getByText(/Max loss at stop \(BBB\)/)).toBeInTheDocument();

    rerender(
      <SendToBrokerDialog
        cards={[bbb]}
        contractsBySymbol={{}}
        overridesBySymbol={{ BBB: { mode: 'dollar', value: 5000 } }}
        onClose={noop}
        onSubmit={noop}
      />,
    );
    expect(screen.getByText('Within risk limits.')).toBeInTheDocument();
    expect(screen.queryByText(/Max loss at stop \(BBB\)/)).not.toBeInTheDocument();
  });
});
