import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { StockPositionCard } from '@/components/organisms/StockPositionCard';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useRiskStore } from '@/lib/riskStore';
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

/** The decision's own worked example, to the cent: AAPL entry 211.59, stop
 *  195.90, a $3,750 budget (3.75% of $100k) over a $15.69 risk/share -> 239
 *  shares -> a $50,570 position against a $5,000 cap. */
function makeCard(): PositionCardData {
  return {
    symbol: 'AAPL', company: 'Apple Inc.', price: 211.59, direction: 'Bullish',
    strategy: {
      strategy: 'pullback_ema', entry_price: 211.59, stop_price: 195.90,
      target_price: 242.97, rr_ratio: 2, atr: 5, detail: {}, targets: [242.97],
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

function makePlan(overrides: Partial<StockExitPlan> = {}): StockExitPlan {
  return {
    stop: {
      price: 195.90, source: 'structural', structuralSource: 'swing_low',
      structuralConfidence: 60, structuralPrice: 195.90, atrFloorPrice: 194.0,
      distanceDollar: 15.69, riskPerShare: 15.69, probability: 0.34, expectedDays: 6,
    },
    targets: [{
      rrRatio: 2, arithmeticPrice: 242.97, price: 242.97, tpSource: 'arithmetic',
      structuralPrice: null, distanceDollar: null, toleranceDollar: 0.9,
      rewardPerShare: 31.38, probability: 0.41, expectedDays: 7,
      qualityGood: true, qualityReasons: [],
    }],
    atr: 5.0,
    recommendedShares: 239,
    riskBudget: 3750.0,
    daysBasis: 'trading',
    horizonDays: 10,
    modelCaveat: null,
    race: null,
    ...overrides,
  };
}

const mockedApi = api as jest.Mocked<typeof api>;

async function renderAndCompute(plan: StockExitPlan = makePlan()) {
  (mockedApi.getStockExitPlan as jest.Mock).mockResolvedValue(plan);
  render(<StockPositionCard card={makeCard()} strategyKey="pullback_ema" />);
  fireEvent.click(screen.getByText('Arithmetic plan'));
  await waitFor(() => expect(screen.getByText('RISK/SHARE')).toBeTruthy());
}

/** The flag renders as one <Text> whose children are interpolated fragments, so
 *  match on the element's whole textContent rather than on a single text node. */
/** An EditableField renders its value in a role="button" span until clicked. */
function editableValue(label: string): HTMLElement {
  return screen.getByText(label).parentElement!.querySelector('[role="button"]') as HTMLElement;
}

/** The card's own SHARES field (the editable one above the fold), not the
 *  plan's read-only recommendation row. */
function sharesFieldValue(): string {
  // 'SHARES' labels two things: this editable field and the plan's read-only
  // recommendation row. The editable one is the first in document order.
  const label = screen.getAllByText('SHARES')[0];
  return label.parentElement!.querySelector('[role="button"]')!.textContent!.trim();
}

function flagText(): string | null {
  const el = screen.queryByText(/^Concentration:/);
  return el ? el.textContent!.replace(/\s+/g, ' ').trim() : null;
}

describe('StockPositionCard — single-position concentration flag', () => {
  beforeEach(() => {
    usePortfolioStore.setState({ positions: [], lastSyncError: null });
    useRiskStore.setState({
      limits: {
        maxSingleTradeExposurePct: 0.05,
        maxTotalExposurePct: 0.25,
        maxConcurrentPositions: 10,
        maxDailyRecommendations: 5,
        portfolioValue: 100000,
        maxLossPerTradePct: 0.0375,
      },
    });
  });
  afterEach(() => jest.clearAllMocks());

  it('fires on the decision\'s worked example, with every number checkable', async () => {
    await renderAndCompute();
    // 239 x 211.59 = 50,570.01 -> "50570"; 50.6% of 100k; cap 5% = $5,000;
    // floor(5000 / 211.59) = 23 shares.
    expect(flagText()).toBe(
      'Concentration: ≈$50570 is 50.6% of your $100000 account — over the 5% '
      + 'single-position cap ($5000, ≈23 shares). Sized by risk budget, as the '
      + 'plan intends. Nothing is blocked — your call.',
    );
  });

  it('does NOT block Apply — the whole point of flagging over capping', async () => {
    await renderAndCompute();
    expect(flagText()).not.toBeNull();
    const apply = screen.getByText('Apply 239 shares').closest('button')!;
    expect(apply.hasAttribute('disabled')).toBe(false);
    // And it still applies the spec-mandated number, unclamped: the SHARES
    // field takes 239, and the Apply button retires because there is nothing
    // left to apply.
    fireEvent.click(apply);
    await waitFor(() => expect(screen.queryByText('Apply 239 shares')).toBeNull());
    expect(sharesFieldValue()).toBe('239');
  });

  it('stays silent when the recommendation is inside the cap', async () => {
    // 20 x 211.59 = $4,231.80, under the $5,000 cap.
    await renderAndCompute(makePlan({ recommendedShares: 20 }));
    expect(flagText()).toBeNull();
  });

  it('reads riskStore, not a second copy of 0.05 — a wider cap silences it', async () => {
    // 60% of $100k = $60,000, above the $50,570 position.
    useRiskStore.setState({
      limits: { ...useRiskStore.getState().limits, maxSingleTradeExposurePct: 0.6 },
    });
    await renderAndCompute();
    expect(flagText()).toBeNull();
  });

  it('reads riskStore portfolioValue too — a bigger account silences it', async () => {
    // 5% of $2,000,000 = $100,000, above the $50,570 position.
    useRiskStore.setState({
      limits: { ...useRiskStore.getState().limits, portfolioValue: 2_000_000 },
    });
    await renderAndCompute();
    expect(flagText()).toBeNull();
  });

  it('cannot outlive the entry it was computed at — an entry edit clears it', async () => {
    // The flag multiplies the plan's share count by `overlay.entry`, exactly as
    // the ≈$ line above it does. That is only truthful because an entry edit
    // tears the whole plan down (patch() aborts and nulls it, since the plan
    // derives its stop from the entry alone). Pin that: without it, the flag
    // would keep printing a position built from the OLD entry.
    await renderAndCompute();
    expect(flagText()).not.toBeNull();

    fireEvent.click(editableValue('ENTRY'));
    const input = screen.getByDisplayValue('211.59');
    fireEvent.change(input, { target: { value: '105.79' } });
    fireEvent.blur(input);

    await waitFor(() => expect(screen.queryByText('RISK/SHARE')).toBeNull());
    expect(flagText()).toBeNull();

    // Re-running the fetch brings back a plan for the NEW entry, and the flag
    // returns with figures built from it: 239 x 105.79 = $25,283.81, still over
    // the $5,000 cap, which now allows floor(5000 / 105.79) = 47 shares.
    fireEvent.click(screen.getByText('Arithmetic plan'));
    await waitFor(() => expect(screen.getByText('RISK/SHARE')).toBeTruthy());
    expect(flagText()).toContain('≈$25284 is 25.3% of your $100000 account');
    expect(flagText()).toContain('≈47 shares');
  });

  it('says nothing when there is no recommendation to flag', async () => {
    await renderAndCompute(makePlan({ recommendedShares: null }));
    expect(flagText()).toBeNull();
  });

  it('never fires at a 100% cap — legal in Settings, and not a concentration limit', async () => {
    useRiskStore.setState({
      limits: { ...useRiskStore.getState().limits, maxSingleTradeExposurePct: 1 },
    });
    await renderAndCompute();
    expect(flagText()).toBeNull();
  });
});
