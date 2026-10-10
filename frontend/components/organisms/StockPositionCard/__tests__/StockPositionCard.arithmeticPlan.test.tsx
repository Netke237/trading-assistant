import { useStockOrderOwnershipStore } from '@/lib/stockExecutionSession';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { StockPositionCard } from '@/components/organisms/StockPositionCard';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { api } from '@/lib/api';
import type { PositionCardData, StockExitPlan } from '@/types/stockDomain';

jest.mock('@/lib/api', () => ({
  api: {
    getBrokerStatus: jest.fn().mockResolvedValue({}),
    getStockFirstPassage: jest.fn(),
    getStructuralStop: jest.fn(),
    getStockExitPlan: jest.fn(),
  },
}));
jest.mock('@/components/organisms/StockAutoTradeArm', () => ({ StockAutoTradeArm: () => null }));
jest.mock('@/components/molecules/MarketSentiment', () => ({ MarketSentiment: () => null }));
jest.mock('@/components/molecules/FundamentalHealthCard', () => ({ FundamentalHealthCard: () => null }));

/** entry 150, stop 145 -> the CARD's risk is 5. The PLAN below deliberately
 *  resolves a different stop (144.00, risk 6.00) so every test that cares about
 *  the two disagreeing has something to see. */
function makeCard(direction: 'Bullish' | 'Bearish' = 'Bullish'): PositionCardData {
  return {
    symbol: 'AAPL', company: 'Apple Inc.', price: 150, direction,
    strategy: {
      strategy: 'pullback_ema', entry_price: 150, stop_price: 145,
      target_price: 160, rr_ratio: 2, atr: 3, detail: {}, targets: [160, 165, 170],
    },
    backtest: {
      n_trades: 20, win_rate: 0.6, total_return_pct: 12, max_drawdown_pct: 5,
      expectancy: 0.4, sharpe: 1.2, confidence: 0.7, passes_gate: true, summary_text: 'ok',
    },
    stock_score: 80, stock_status: 'PASS',
    shares: 30, dollar_risk: 150, dollar_size: 4500,
    confidence: 0.7, confidence_text: 'High',
    sentiment: null, fundamentals: null,
  };
}

/** entry 150, stop 144 -> riskPerShare 6.00; 2R = 162.00, 3R = 168.00. Every
 *  expectation below is derived from exactly these. */
function makePlan(overrides: Partial<StockExitPlan> = {}): StockExitPlan {
  return {
    stop: {
      price: 144.0,
      source: 'atr_widened',
      structuralSource: 'swing_low',
      structuralConfidence: 60,
      structuralPrice: 147.0,
      atrFloorPrice: 144.0,
      distanceDollar: 3.0,
      riskPerShare: 6.0,
      probability: 0.34,
      expectedDays: 6,
    },
    targets: [
      {
        rrRatio: 2, arithmeticPrice: 162.0, price: 162.0, tpSource: 'arithmetic',
        structuralPrice: 170.0, distanceDollar: 8.0, toleranceDollar: 0.9,
        rewardPerShare: 12.0, probability: 0.41, expectedDays: 7,
        qualityGood: false, qualityReasons: ['stop_widened'],
      },
      {
        rrRatio: 3, arithmeticPrice: 168.0, price: 170.0, tpSource: 'structural_snap',
        structuralPrice: 170.0, distanceDollar: 2.0, toleranceDollar: 2.5,
        rewardPerShare: 20.0, probability: 0.19, expectedDays: 9,
        qualityGood: false, qualityReasons: ['stop_widened'],
      },
    ],
    atr: 3.0,
    recommendedShares: 625,
    riskBudget: 3750.0,
    daysBasis: 'trading',
    horizonDays: 10,
    modelCaveat: null,
    race: {
      outcomes: [
        {
          targetPrice: 162.0, pTargetFirst: 0.4, pStopFirst: 0.34, pNeither: 0.26,
          daysTarget: 7, daysStop: 6,
          weightTarget: 0.4, weightStop: 0.34, weightNeither: 0.26,
          terminalMean: 152.4,
        },
        {
          targetPrice: 170.0, pTargetFirst: 0.19, pStopFirst: 0.34, pNeither: 0.47,
          daysTarget: 9, daysStop: 6,
          weightTarget: 0.19, weightStop: 0.34, weightNeither: 0.47,
          terminalMean: 154.1,
        },
      ],
      stopPrice: 144.0,
      nPaths: 2000,
    },
    ...overrides,
  };
}

const mockedApi = api as jest.Mocked<typeof api>;

async function renderAndCompute(
  plan: StockExitPlan = makePlan(),
  direction: 'Bullish' | 'Bearish' = 'Bullish',
) {
  (mockedApi.getStockExitPlan as jest.Mock).mockResolvedValue(plan);
  render(<StockPositionCard card={makeCard(direction)} strategyKey="pullback_ema" />);
  fireEvent.click(screen.getByText('Arithmetic plan'));
  await waitFor(() => expect(screen.getByText('RISK/SHARE')).toBeTruthy());
}

/** The bearish mirror of makePlan: entry 150, stop 156 -> riskPerShare 6.00,
 *  2R = 138.00, 3R = 132.00. Every sign below is the opposite of the bullish
 *  fixture's, which is the point. */
function makeBearishPlan(): StockExitPlan {
  const base = makePlan();
  return {
    ...base,
    stop: { ...base.stop, price: 156.0, structuralPrice: 153.0, atrFloorPrice: 156.0 },
    targets: [
      { ...base.targets[0], arithmeticPrice: 138.0, price: 138.0, structuralPrice: 130.0 },
      { ...base.targets[1], arithmeticPrice: 132.0, price: 130.0, structuralPrice: 130.0 },
    ],
    race: null,
  };
}

describe('StockPositionCard — arithmetic profit target (piece 6)', () => {
  beforeEach(() => {
    usePortfolioStore.setState({ positions: [], lastSyncError: null });
  });
  afterEach(() => jest.clearAllMocks());

  it('renders nothing until the button is clicked — this is not scan work', () => {
    render(<StockPositionCard card={makeCard()} strategyKey="pullback_ema" />);
    expect(screen.getByText('ARITHMETIC PROFIT TARGET')).toBeTruthy();
    expect(screen.queryByText('RISK/SHARE')).toBeNull();
    expect(mockedApi.getStockExitPlan).not.toHaveBeenCalled();
  });

  it('sends the EDITED entry price and no stop — the plan derives its own', async () => {
    await renderAndCompute();
    const req = (mockedApi.getStockExitPlan as jest.Mock).mock.calls[0][0];
    expect(req).toMatchObject({
      symbol: 'AAPL', direction: 'Bullish', entry_price: 150,
      trend_score: 80, strategy: 'pullback_ema',
    });
    // Feeding it the card's stop would make it echo the number it exists to
    // offer a second opinion on.
    expect(req).not.toHaveProperty('stop_price');
    expect(req).not.toHaveProperty('targets');
  });

  it('prints the stop, its risk per share, and its probability', async () => {
    await renderAndCompute();
    expect(screen.getByText('144.00')).toBeTruthy();
    expect(screen.getByText('6.00')).toBeTruthy();
    expect(screen.getByText('34% reached')).toBeTruthy();
  });

  it('says TRADING days, never a bare "d", on every expected-time readout', async () => {
    await renderAndCompute();
    // Spec 3.2: the options card counts CALENDAR days. "~6d" on both cards would
    // silently mean two different things.
    expect(screen.getByText('~6 trading days')).toBeTruthy();
    expect(screen.getByText('~7 trading days')).toBeTruthy();
    expect(screen.getByText('~9 trading days')).toBeTruthy();
  });

  it('prints the R:R arithmetic as a chain the user can check', async () => {
    await renderAndCompute();
    expect(screen.getByText('150.00 + 2 × 6.00 = 162.00')).toBeTruthy();
    expect(screen.getByText('150.00 + 3 × 6.00 = 168.00')).toBeTruthy();
  });

  it('prints a MINUS in the chain on a bearish candidate', async () => {
    // Round 1 of the adversarial audit: the sign was hardcoded '+', so every
    // row of every bearish scan rendered a false equation —
    // "150.00 + 2 × 6.00 = 138.00" — on the one readout whose entire purpose
    // is being checkable in the head. The backend was always correct; only the
    // render was direction-blind, and no bearish case existed here to catch it.
    await renderAndCompute(makeBearishPlan(), 'Bearish');
    expect(screen.getByText('150.00 − 2 × 6.00 = 138.00')).toBeTruthy();
    expect(screen.getByText('150.00 − 3 × 6.00 = 132.00')).toBeTruthy();
    expect(screen.queryByText(/150\.00 \+ 2 ×/)).toBeNull();
  });

  it('sends the bearish direction through to the endpoint', async () => {
    await renderAndCompute(makeBearishPlan(), 'Bearish');
    expect((mockedApi.getStockExitPlan as jest.Mock).mock.calls[0][0])
      .toMatchObject({ direction: 'Bearish' });
  });

  it('never offers an Apply button for a zero share count', async () => {
    // Round 1: a risk budget too small for one share returned 0, not null, so
    // the card printed "SHARES 0" and offered "Apply 0 shares" — which wrote
    // shares: 0 past the SHARES field's own clamp, onto the order quantity and
    // into the persisted position. The backend now returns null; this is the
    // client half of the same guard.
    await renderAndCompute(makePlan({ recommendedShares: 0, riskBudget: 2 }));
    expect(screen.queryByText(/^Apply /)).toBeNull();
  });

  it('shows the sizing division, not just its answer', async () => {
    await renderAndCompute();
    expect(screen.getByText('625')).toBeTruthy();
    expect(screen.getByText('risk budget $3750.00 ÷ $6.00')).toBeTruthy();
    // The notional the share count implies. 625 x 150 = 93,750 — far past the
    // 5%-of-portfolio single-position cap, which is exactly why it is shown
    // rather than left for the user to multiply out.
    expect(screen.getByText('≈ $93750 position')).toBeTruthy();
  });

  it('Apply writes the recommended share count into the overlay', async () => {
    await renderAndCompute();
    fireEvent.click(screen.getByText('Apply 625 shares'));
    await waitFor(() => expect(screen.queryByText('Apply 625 shares')).toBeNull());
  });

  it('warns that the applied size is for the PLAN stop when the card stop differs', async () => {
    await renderAndCompute();
    expect(
      screen.getByText(/Sized for the \$144\.00 stop above, not the card's \$145\.00/),
    ).toBeTruthy();
  });

  it("says the plan's stop does not replace the card's", async () => {
    await renderAndCompute();
    // Arming a stop per trade is piece 5 and does not exist yet — two stop
    // prices on one card must never sit there unexplained.
    expect(screen.getByText(/second opinion and does not change it/)).toBeTruthy();
  });

  it('stays silent about the two stops when they agree', async () => {
    await renderAndCompute(makePlan({
      stop: { ...makePlan().stop, price: 145.0, riskPerShare: 5.0 },
    }));
    expect(screen.queryByText(/second opinion and does not change it/)).toBeNull();
  });

  it('renders the race off the ALLOCATED weights so each row sums to 100%', async () => {
    await renderAndCompute();
    expect(screen.getByText(/target 40%/)).toBeTruthy();
    expect(screen.getByText(/neither 26%/)).toBeTruthy();
    // Both race rows share one stop, so its share is identical on both — that
    // is a property of the stop, not of the target it is raced against.
    expect(screen.getAllByText(/stop 34%/)).toHaveLength(2);
  });

  it('explains why the race percentages differ from the ones above them', async () => {
    await renderAndCompute();
    expect(screen.getByText(/add to 100% because every path is counted once/)).toBeTruthy();
  });

  it('labels the neither bucket with its terminal price', async () => {
    await renderAndCompute();
    // A stock that reached no barrier is an open position at a knowable price,
    // not a write-off the way an expired option is.
    expect(screen.getByText(/neither 26% \(~\$152\.40\)/)).toBeTruthy();
  });

  it('keeps the "they can disagree" line verbatim', async () => {
    await renderAndCompute();
    expect(screen.getByText(
      'Independent of the other profit-target methods on this page; they can disagree.',
    )).toBeTruthy();
  });

  it('renders the model caveat verbatim when the backend sets one', async () => {
    await renderAndCompute(makePlan({ modelCaveat: 'Approximate for mean-reversion strategies.' }));
    expect(screen.getByText('Approximate for mean-reversion strategies.')).toBeTruthy();
  });

  it('shows no options fields anywhere — no premium, IV, delta or stop-cost badge', async () => {
    // The UI half of the backend's key-set assertion. Scoped to this section so
    // it pins THIS card's content rather than passing by accident on whatever
    // the rest of the page happens not to say today.
    await renderAndCompute();
    const heading = screen.getByText('ARITHMETIC PROFIT TARGET');
    const section = heading.closest('div')?.parentElement;
    const text = section?.textContent ?? '';
    expect(text).toContain('RISK/SHARE');
    for (const word of ['premium', 'Premium', 'IV', 'delta', 'Delta', 'Stop cost', 'stop cost']) {
      expect(text.includes(word)).toBe(false);
    }
  });

  it('clears the plan when the ENTRY is edited — its only overlay input', async () => {
    await renderAndCompute();
    const entryCell = screen.getByText('150.00');
    fireEvent.click(entryCell);
    const input = document.querySelector('input[type="number"]') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '152' } });
    fireEvent.blur(input);
    await waitFor(() => expect(screen.queryByText('RISK/SHARE')).toBeNull());
  });

  it('surfaces a fetch failure instead of leaving the button looking idle', async () => {
    (mockedApi.getStockExitPlan as jest.Mock).mockRejectedValue(new Error('boom'));
    render(<StockPositionCard card={makeCard()} strategyKey="pullback_ema" />);
    fireEvent.click(screen.getByText('Arithmetic plan'));
    await waitFor(() => expect(screen.getByText(/boom/)).toBeTruthy());
  });

  it('renders an em dash rather than a number when sizing is not computable', async () => {
    await renderAndCompute(makePlan({ recommendedShares: null, riskBudget: 0 }));
    expect(screen.queryByText(/^Apply /)).toBeNull();
    expect(screen.getByText('risk budget $0.00 ÷ $6.00')).toBeTruthy();
  });

  it('renders without a race block when the backend refused to simulate one', async () => {
    await renderAndCompute(makePlan({ race: null }));
    expect(screen.queryByText(/add to 100% because every path is counted once/)).toBeNull();
    // The rest of the plan still stands — the race is an addition, not a
    // precondition.
    expect(screen.getByText('RISK/SHARE')).toBeTruthy();
  });
});

describe('StockPositionCard — target-row structure labels', () => {
  beforeEach(() => {
    usePortfolioStore.setState({ positions: [], lastSyncError: null });
  });
  afterEach(() => jest.clearAllMocks());

  it('labels a snapped row as within tolerance and an unsnapped one as outside', async () => {
    await renderAndCompute();
    expect(screen.getByText(/Within tolerance — snapped onto the structural level\./)).toBeTruthy();
    expect(screen.getByText(/Outside tolerance/)).toBeTruthy();
  });

  it('prints the structural level, its distance and the snap band per row', async () => {
    await renderAndCompute();
    expect(screen.getByText('structure 170.00 · 8.00 away · tol 0.90')).toBeTruthy();
    expect(screen.getByText('structure 170.00 · 2.00 away · tol 2.50')).toBeTruthy();
  });

  it('measures reward to the price ACTUALLY used, not the arithmetic one', async () => {
    await renderAndCompute();
    // The snapped row: arithmetic 168.00, actually used 170.00 -> reward 20.00,
    // not 18.00. Measuring to the arithmetic price would print an R:R for a
    // trade the card is not proposing.
    const rows = screen.getAllByText('20.00');
    expect(rows.length).toBeGreaterThan(0);
  });

  it('explains a widened stop in prose built from the raw numbers', async () => {
    await renderAndCompute();
    expect(screen.getByText(
      'Structural stop $147.00 was inside the ATR floor — widened to $144.00 for a minimum-distance stop',
    )).toBeTruthy();
  });
});

// Mutation ownership is session-wide; each test begins a fresh session.
beforeEach(() => useStockOrderOwnershipStore.setState({ bySymbol: {} }));
