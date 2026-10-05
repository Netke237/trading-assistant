import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { StockPositionCard } from '@/components/organisms/StockPositionCard';
import { useScanStore } from '@/lib/scanStore';
import { selectCardEdits } from '@/lib/cardEdits';
import { api } from '@/lib/api';
import type { PositionCardData, StockExitPlan } from '@/types/stockDomain';

// Phase G piece 5, build step 3 — the stocks half of the control (spec §6.3).
// Spec test 14 is `offers three methods and no Barrier Race` below.

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

/** Stamp the stocks slice so `selectCardEdits` reads it. Without a matching
 *  `scan_id` on `stockScanResult` every read comes back EMPTY, which is the
 *  stamp doing its job and would make every case here vacuously pass. */
function stampStocksScan(scanId = 'stk-1') {
  useScanStore.setState({
    stockScanResult: { scan_id: scanId, timestamp: '2026-09-14T09:00:00Z' } as never,
  });
}

const stocksPicks = () => selectCardEdits(useScanStore.getState(), 'stocks').picks;
const radio = (name: string) => screen.getByRole('radio', { name });

beforeEach(() => {
  jest.clearAllMocks();
  (api.getBrokerStatus as jest.Mock).mockResolvedValue({});
  useScanStore.setState({
    stocksCardEdits: {
      scanId: null, picks: {}, invalidation: {}, premiumStop: {},
      entryLimit: {}, maxLossOverride: {},
    },
    stockScanResult: null,
  });
});

describe('StockPositionCard — the method pick (§6.3)', () => {
  it('TEST 14 — offers three methods and no Barrier Race', async () => {
    stampStocksScan();
    render(<StockPositionCard card={makeCard()} strategyKey="pullback_ema" />);
    await waitFor(() => expect(radio('Ladder')).toBeInTheDocument());
    expect(radio('Arithmetic')).toBeInTheDocument();
    expect(radio('Monte Carlo')).toBeInTheDocument();
    // A stock position has no premium, so there is no premium stop for a stock
    // stop to race — the fourth method is absent by construction, not hidden.
    expect(screen.queryByRole('radio', { name: 'Barrier Race' })).not.toBeInTheDocument();
  });

  it('writes the pick into the SCAN-STAMPED stocks slice, keyed by symbol', async () => {
    stampStocksScan();
    render(<StockPositionCard card={makeCard('MSFT')} strategyKey="pullback_ema" />);
    await waitFor(() => expect(radio('Ladder')).toBeInTheDocument());
    fireEvent.click(radio('Ladder'));
    expect(stocksPicks().MSFT).toEqual(expect.objectContaining({
      method: 'ladder', stopBasis: 'stock',
    }));
  });

  it('every stocks row is STOCK space — rowOptionPrice is null on all of them', async () => {
    stampStocksScan();
    render(<StockPositionCard card={makeCard()} strategyKey="pullback_ema" />);
    await waitFor(() => expect(radio('Ladder')).toBeInTheDocument());
    fireEvent.click(radio('Ladder'));
    fireEvent.click(radio('T1'));
    // `t1` from `strategy.targets[0]`. A stocks pick can always seed
    // `resolved_tp_price` precisely because there is no premium anywhere on
    // this card to put in a stock-price column.
    expect(stocksPicks().AAPL).toEqual(expect.objectContaining({
      rowStockPrice: 160, rowOptionPrice: null,
    }));
  });

  it('a Clear deletes the key rather than storing a null', async () => {
    stampStocksScan();
    render(<StockPositionCard card={makeCard()} strategyKey="pullback_ema" />);
    await waitFor(() => expect(radio('Ladder')).toBeInTheDocument());
    fireEvent.click(radio('Ladder'));
    expect('AAPL' in stocksPicks()).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: /clear/i }));
    // `picks` holds no nulls: a present key means a human picked.
    expect('AAPL' in stocksPicks()).toBe(false);
  });

  it('refuses to write at all when no scan is stamped', async () => {
    // No `stockScanResult`, so `currentScanIdFor` is null and `writeCardEdit`
    // drops the write rather than parking it under a stamp no reader accepts.
    render(<StockPositionCard card={makeCard()} strategyKey="pullback_ema" />);
    await waitFor(() => expect(radio('Ladder')).toBeInTheDocument());
    fireEvent.click(radio('Ladder'));
    expect(stocksPicks()).toEqual({});
  });

  it('clears an arithmetic pick on a symbol switch that has no plan', async () => {
    stampStocksScan();
    (api.getStockExitPlan as jest.Mock).mockResolvedValue(makePlan());
    const { rerender } = render(
      <StockPositionCard card={makeCard('AAPL')} strategyKey="pullback_ema" />,
    );
    fireEvent.click(await screen.findByRole('button', { name: /arithmetic plan/i }));
    await waitFor(() => expect(radio('Arithmetic')).toBeEnabled());
    fireEvent.click(radio('Arithmetic'));
    expect(stocksPicks().AAPL).toEqual(expect.objectContaining({ method: 'arithmetic' }));

    rerender(<StockPositionCard card={makeCard('MSFT')} strategyKey="pullback_ema" />);
    // MSFT has no plan of its own, so Arithmetic is unavailable there and any
    // pick naming it is about numbers that are not on screen. AAPL's pick is
    // untouched — the clear is keyed, not global.
    await waitFor(() => expect(radio('Arithmetic')).toBeDisabled());
    expect('MSFT' in stocksPicks()).toBe(false);
    expect(stocksPicks().AAPL).toEqual(expect.objectContaining({ method: 'arithmetic' }));
  });

  it('leaving a symbol does not wipe the pick stored under it', async () => {
    // The clear is KEYED. This card reads `methodPick` straight out of the
    // store, so on the commit that switches symbols the pick is already the
    // incoming symbol's while `plan` still holds the outgoing one's — see the
    // card's own note on why that cannot produce a wrong clear today, and what
    // would change that. What this pins is the outcome: navigating away leaves
    // the departed symbol's pick where it was.
    stampStocksScan();
    (api.getStockExitPlan as jest.Mock).mockResolvedValue(makePlan());
    const { rerender } = render(
      <StockPositionCard card={makeCard('MSFT')} strategyKey="pullback_ema" />,
    );
    fireEvent.click(await screen.findByRole('button', { name: /arithmetic plan/i }));
    await waitFor(() => expect(radio('Arithmetic')).toBeEnabled());
    fireEvent.click(radio('Arithmetic'));

    // Leave MSFT for AAPL and come straight back. MSFT's pick must survive the
    // round trip, because on returning the card immediately recomputes nothing
    // and the pick simply becomes unavailable-and-cleared — which is correct —
    // but it must not have been cleared DURING the outbound commit, when the
    // store already said MSFT and the state still said MSFT's plan.
    expect(stocksPicks().MSFT).toEqual(expect.objectContaining({ method: 'arithmetic' }));
    rerender(<StockPositionCard card={makeCard('AAPL')} strategyKey="pullback_ema" />);
    await waitFor(() => expect(radio('Arithmetic')).toBeDisabled());
    expect(stocksPicks().MSFT).toEqual(expect.objectContaining({ method: 'arithmetic' }));
  });
});

// New ephemeral execution records must not leak between independent test scans.
beforeEach(() => useScanStore.setState({ stockExecution: {}, stockExecutionGeneration: 0 }));
