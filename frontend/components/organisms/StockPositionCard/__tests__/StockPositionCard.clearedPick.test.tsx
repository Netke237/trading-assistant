import { useStockOrderOwnershipStore } from '@/lib/stockExecutionSession';
import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { StockPositionCard, clearedPickMessage } from '@/components/organisms/StockPositionCard';
import { useScanStore } from '@/lib/scanStore';
import { stockExecutionIdentity } from '@/lib/stockExecutionSession';
import { selectCardEdits } from '@/lib/cardEdits';
import { MISSING_METHOD_PICK_MESSAGE } from '@/lib/risk';
import { api } from '@/lib/api';
import type { PositionCardData, StockExitPlan } from '@/types/stockDomain';

// P6 (G4-1; decision P6-SCOPE-2026-09-30) -- collapsing and reopening a Step-4
// row unmounts the card, the remount has no plan/estimate, and the clear rule
// removes the pick. The refusal must say THAT, not the generic "choose a
// method". The clear rule itself is unchanged, so the pick is still gone and
// the send buttons still refuse.

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

function makeCard(symbol = 'AAPL'): PositionCardData {
  return {
    symbol, company: 'Apple Inc.', price: 150, direction: 'Bullish',
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

function makePlan(): StockExitPlan {
  return {
    stop: {
      price: 144.0, source: 'atr_widened', structuralSource: 'swing_low',
      structuralConfidence: 60, structuralPrice: 147.0, atrFloorPrice: 144.0,
      distanceDollar: 3.0, riskPerShare: 6.0, probability: 0.34, expectedDays: 6,
    },
    targets: [
      {
        rrRatio: 2, arithmeticPrice: 162.0, price: 162.0, tpSource: 'arithmetic',
        structuralPrice: null, distanceDollar: null, toleranceDollar: 0.9,
        rewardPerShare: 12.0, probability: 0.41, expectedDays: 7,
        qualityGood: true, qualityReasons: [],
      },
    ],
    atr: 3.0, recommendedShares: 625, riskBudget: 3750.0,
    daysBasis: 'trading', horizonDays: 10, modelCaveat: null, race: null,
  };
}

const stocksPicks = () => selectCardEdits(useScanStore.getState(), 'stocks').picks;
const radio = (name: string) => screen.getByRole('radio', { name });
const ARITH_CLEARED = clearedPickMessage('arithmetic')!;

beforeEach(() => {
  jest.clearAllMocks();
  (api.getBrokerStatus as jest.Mock).mockResolvedValue({});
  (api.getStockExitPlan as jest.Mock).mockResolvedValue(makePlan());
  useScanStore.setState({
    stocksCardEdits: {
      scanId: null, picks: {}, invalidation: {}, premiumStop: {},
      entryLimit: {}, maxLossOverride: {},
    },
    stockScanResult: { scan_id: 'stk-1', timestamp: '2026-09-30T09:00:00Z' } as never,
  });
});

async function pickArithmeticThenRemount() {
  const first = render(<StockPositionCard card={makeCard()} strategyKey="pullback_ema" />);
  fireEvent.click(await screen.findByRole('button', { name: /arithmetic plan/i }));
  await waitFor(() => expect(radio('Arithmetic')).toBeEnabled());
  fireEvent.click(radio('Arithmetic'));
  expect(stocksPicks().AAPL).toEqual(expect.objectContaining({ method: 'arithmetic' }));
  first.unmount();
  // Simulate unavailable evidence (e.g. reload). Ordinary S2 remounts keep
  // completed evidence and are covered by the shared-session tests.
  useScanStore.setState({ stockExecution: {} });
  render(<StockPositionCard card={makeCard()} strategyKey="pullback_ema" />);   // ...and reopens
}

describe('StockPositionCard — a pick whose evidence is missing says so', () => {
  it('names the cleared method instead of the generic refusal, and still refuses', async () => {
    await pickArithmeticThenRemount();
    await waitFor(() => expect(screen.getByText(ARITH_CLEARED)).toBeInTheDocument());
    expect(screen.queryByText(MISSING_METHOD_PICK_MESSAGE)).not.toBeInTheDocument();
    // The clear rule is unchanged: the pick is gone and the gate still holds.
    expect('AAPL' in stocksPicks()).toBe(false);
    expect(screen.getByRole('button', { name: /add to portfolio/i })).toBeDisabled();
  });

  it('a card that was never picked shows the generic refusal', async () => {
    render(<StockPositionCard card={makeCard()} strategyKey="pullback_ema" />);
    await waitFor(() => expect(radio('Ladder')).toBeInTheDocument());
    expect(screen.getByText(MISSING_METHOD_PICK_MESSAGE)).toBeInTheDocument();
    expect(screen.queryByText(ARITH_CLEARED)).not.toBeInTheDocument();
  });

  it('a new pick retires the note', async () => {
    await pickArithmeticThenRemount();
    await waitFor(() => expect(screen.getByText(ARITH_CLEARED)).toBeInTheDocument());
    fireEvent.click(radio('Ladder'));
    expect(screen.queryByText(ARITH_CLEARED)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /clear/i }));
    // Cleared by the USER this time: the generic line, not the lost-pick one.
    expect(screen.getByText(MISSING_METHOD_PICK_MESSAGE)).toBeInTheDocument();
    expect(screen.queryByText(ARITH_CLEARED)).not.toBeInTheDocument();
  });

  it('the note does not follow the card to another symbol', async () => {
    // ONE instance throughout (a caller that does not remount per symbol).
    const { rerender } = render(<StockPositionCard card={makeCard('AAPL')} strategyKey="pullback_ema" />);
    fireEvent.click(await screen.findByRole('button', { name: /arithmetic plan/i }));
    await waitFor(() => expect(radio('Arithmetic')).toBeEnabled());
    fireEvent.click(radio('Arithmetic'));
    // Away and back: the symbol reset drops AAPL's plan, so on return its pick
    // is cleared in this instance and the note appears.
    rerender(<StockPositionCard card={makeCard('MSFT')} strategyKey="pullback_ema" />);
    useScanStore.setState({ stockExecution: {} });
    rerender(<StockPositionCard card={makeCard('AAPL')} strategyKey="pullback_ema" />);
    await waitFor(() => expect(screen.getByText(ARITH_CLEARED)).toBeInTheDocument());
    // On to a symbol that was never picked: the generic line, not AAPL's note.
    rerender(<StockPositionCard card={makeCard('MSFT')} strategyKey="pullback_ema" />);
    await waitFor(() => expect(screen.queryByText(ARITH_CLEARED)).not.toBeInTheDocument());
    expect(screen.getByText(MISSING_METHOD_PICK_MESSAGE)).toBeInTheDocument();
  });
});

describe('clearedPickMessage', () => {
  it('has a line for the two methods the clear rule can remove, none otherwise', () => {
    expect(clearedPickMessage('monte_carlo')).toMatch(/Monte Carlo pick was cleared.*run Estimate again/);
    expect(clearedPickMessage('arithmetic')).toMatch(/Arithmetic pick was cleared.*Arithmetic plan again/);
    expect(clearedPickMessage('ladder')).toBeNull();
    expect(clearedPickMessage(null)).toBeNull();
  });
});

// New ephemeral execution records must not leak between independent test scans.
beforeEach(() => useScanStore.setState({ stockExecution: {}, stockExecutionGeneration: 0 }));

// Mutation ownership is session-wide; each test begins a fresh session.
beforeEach(() => useStockOrderOwnershipStore.setState({ bySymbol: {} }));
