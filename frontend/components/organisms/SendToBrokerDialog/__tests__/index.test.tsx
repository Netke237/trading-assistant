import '@testing-library/jest-dom';
import { render, screen, act, fireEvent } from '@testing-library/react';
import { SendToBrokerDialog } from '@/components/organisms/SendToBrokerDialog';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useRiskStore } from '@/lib/riskStore';
import type { TradeCardData, MethodPick } from '@/types/domain';

// Phase G piece 5, build step 4 — every render below must supply a pick for
// each symbol in the basket, or the new `missing_method_pick` gate
// short-circuits RiskSummary before the max-loss worst-offender block this
// suite exists to test is ever reached (see the dialog's own `hasMissingMethodPick`
// check, which renders ahead of `allClean`/the reasons stack).
const pick = (): MethodPick => ({
  method: 'monte_carlo',
  rowStockPrice: 197.5,
  rowOptionPrice: 6.24,
  stopBasis: 'stock',
  pickedAt: '2026-09-14T10:00:00.000Z',
});

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
        maxLossPerTradePct: 0.0375, maxSingleStockPositionPct: 0.2, maxTotalStockExposurePct: 1,
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
    // capitalAtRisk/exposure is identical for both: 5000/100000 = 5%. That is
    // within maxSingleTradeExposurePct but above the 3.75% option premium cap
    // (min with maxLossPerTradePct, review fix #4 / D5), so BOTH cards also
    // trip single_trade_exposure_too_high; that is asserted below and is not
    // what is under test. They differ only in the exit-plan stop's contract price,
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

    render(<SendToBrokerDialog cards={[aaa, bbb]} contractsBySymbol={{}} overridesBySymbol={{}} invalidationBySymbol={{}} methodPickBySymbol={{ AAA: pick(), BBB: pick() }} onClose={noop} onSubmit={noop} />);

    expect(screen.getByText('Single trade exposure too high')).toBeInTheDocument();
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

    render(<SendToBrokerDialog cards={[aaa]} contractsBySymbol={{}} overridesBySymbol={{}} invalidationBySymbol={{}} methodPickBySymbol={{ AAA: pick() }} onClose={noop} onSubmit={noop} />);

    expect(screen.getByText('Within risk limits.')).toBeInTheDocument();
  });

  it('Feature 5 — an active pre-trade max-loss override avoids a spurious extra-confirmation click', () => {
    // Same shape as the worst-offender BBB case above: lossAtStop =
    // (50 - 1) * 100 * 1 = $4,900, which exceeds the $3,750 ACCOUNT-DEFAULT
    // limit — without the override this would show a warning and force a
    // second "Submit" click. A $5,000 override raises the limit above the
    // $4,900 loss, so the stop warning must go away.
    const bbb = makeCard({ symbol: 'BBB' });

    const { rerender } = render(
      <SendToBrokerDialog cards={[bbb]} contractsBySymbol={{}} overridesBySymbol={{}} invalidationBySymbol={{}} methodPickBySymbol={{ BBB: pick() }} onClose={noop} onSubmit={noop} />,
    );
    expect(screen.getByText(/Max loss at stop \(BBB\)/)).toBeInTheDocument();

    rerender(
      <SendToBrokerDialog
        cards={[bbb]}
        contractsBySymbol={{}}
        overridesBySymbol={{ BBB: { mode: 'dollar', value: 5000 } }}
        invalidationBySymbol={{}}
        methodPickBySymbol={{ BBB: pick() }}
        onClose={noop}
        onSubmit={noop}
      />,
    );
    // The $5,000 premium (5%) still exceeds the 3.75% option premium cap
    // (review fix #4 / D5), so the dialog is not "clean" any more; what the
    // override must still do is clear the stop-based warning.
    expect(screen.getByText('Single trade exposure too high')).toBeInTheDocument();
    expect(screen.queryByText(/Max loss at stop \(BBB\)/)).not.toBeInTheDocument();
  });
});

describe('SendToBrokerDialog — the method-pick gate (Phase G piece 5, build step 4, spec test 10)', () => {
  const noop = () => {};

  it('blocks submit when one basket card has no method pick, even though the other does', () => {
    const aaa = makeCard({ symbol: 'AAA' });
    const bbb = makeCard({ symbol: 'BBB' });

    render(
      <SendToBrokerDialog
        cards={[aaa, bbb]}
        contractsBySymbol={{}}
        overridesBySymbol={{}}
        invalidationBySymbol={{}}
        methodPickBySymbol={{ AAA: pick() }}
        onClose={noop}
        onSubmit={noop}
      />,
    );

    expect(screen.getByText(/Method pick required/)).toBeInTheDocument();
    const submitBtn = screen.getByRole('button', { name: /Add 2 to Portfolio/ });
    expect(submitBtn).toBeDisabled();
  });

  it('does not block when every basket card carries a pick', () => {
    const aaa = makeCard({ symbol: 'AAA' });
    const bbb = makeCard({ symbol: 'BBB' });

    render(
      <SendToBrokerDialog
        cards={[aaa, bbb]}
        contractsBySymbol={{}}
        overridesBySymbol={{}}
        invalidationBySymbol={{}}
        methodPickBySymbol={{ AAA: pick(), BBB: pick() }}
        onClose={noop}
        onSubmit={noop}
      />,
    );

    expect(screen.queryByText(/Method pick required/)).not.toBeInTheDocument();
  });
});

describe('SendToBrokerDialog — tracks the basket, places no broker order (review #5, D6)', () => {
  const noop = () => {};
  // Within every risk limit, so one click submits (no override step).
  const cleanCard = () => makeCard({
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
  });

  it('renders no Auto-send control and says no broker order is placed', () => {
    render(<SendToBrokerDialog cards={[cleanCard()]} contractsBySymbol={{}} overridesBySymbol={{}} invalidationBySymbol={{}} methodPickBySymbol={{ AAA: pick() }} onClose={noop} onSubmit={noop} />);
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(screen.queryByText(/auto-send/i)).not.toBeInTheDocument();
    expect(screen.getByText(/no broker order is placed/)).toBeInTheDocument();
    // A tracked row reserves its contract and symbol, so the card cannot also be sent.
    expect(screen.getByText(/reserves its contract and symbol/)).toBeInTheDocument();
    expect(screen.queryByText(/send it from its own card/i)).not.toBeInTheDocument();
  });

  it('submits drafts that carry no autoSend field', () => {
    const onSubmit = jest.fn();
    render(<SendToBrokerDialog cards={[cleanCard()]} contractsBySymbol={{}} overridesBySymbol={{}} invalidationBySymbol={{}} methodPickBySymbol={{ AAA: pick() }} onClose={noop} onSubmit={onSubmit} />);
    fireEvent.click(screen.getByRole('button', { name: 'Add 1 to Portfolio' }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(Object.keys(onSubmit.mock.calls[0][0][0]).sort()).toEqual(['card', 'contracts']);
  });
});


test('T11 non-active basket item warns without requiring a quote confirmation tick', () => {
  const card = makeCard({ symbol: 'BBB', noLiveQuote: false });
  render(<SendToBrokerDialog cards={[card]} contractsBySymbol={{}} overridesBySymbol={{}} invalidationBySymbol={{}} methodPickBySymbol={{ BBB: pick() }} onClose={() => {}} onSubmit={() => {}} />);
  expect(screen.getByText(/Live quote unavailable — the entry premium is the scan-time mid/)).toBeInTheDocument();
  expect(screen.queryByLabelText('Confirm sending without a live quote')).not.toBeInTheDocument();
});
