import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import { StockPositionCard } from '@/components/organisms/StockPositionCard';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { api } from '@/lib/api';
import type { PositionCardData } from '@/types/stockDomain';

// api + heavy children are modules (not stores) — mocking them is correct.
jest.mock('@/lib/api', () => ({
  api: {
    getBrokerStatus: jest.fn().mockResolvedValue({}),
    getStockFirstPassage: jest.fn(),
    getStructuralStop: jest.fn(),
  },
}));
jest.mock('@/components/organisms/StockAutoTradeArm', () => ({ StockAutoTradeArm: () => null }));
jest.mock('@/components/molecules/MarketSentiment', () => ({ MarketSentiment: () => null }));
jest.mock('@/components/molecules/FundamentalHealthCard', () => ({ FundamentalHealthCard: () => null }));

/** entry 150, stop 145 → risk = 5. Every expected value below is derived from these. */
function makeCard(targets?: number[]): PositionCardData {
  return {
    symbol: 'AAPL', company: 'Apple Inc.', price: 150, direction: 'Bullish',
    strategy: {
      strategy: 'pullback_ema', entry_price: 150, stop_price: 145,
      target_price: targets?.length ? targets[0] : 160, rr_ratio: 2, atr: 3, detail: {},
      ...(targets ? { targets } : {}),
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

describe('StockPositionCard — exit ladder seeding', () => {
  beforeEach(() => {
    usePortfolioStore.setState({ positions: [], lastSyncError: null });
  });
  afterEach(() => jest.clearAllMocks());

  it('seeds T1/T2/T3 from the backend ladder, not a client-side 2R/3R', () => {
    // A deliberately non-R-shaped ladder: 155 is 1R, 162 is 2.4R, 170 is 4R.
    // No flat multiple of risk reproduces this, so matching it can only come
    // from strategy.targets.
    render(<StockPositionCard card={makeCard([155, 162, 170])} strategyKey="pullback_ema" />);

    // T1 renders twice — once in the sizing grid ("T1 TARGET") and once in the
    // sell-to-close plan row.
    expect(screen.getAllByText('155.00')).toHaveLength(2);
    expect(screen.getByText('162.00')).toBeTruthy();
    expect(screen.getByText('170.00')).toBeTruthy();

    // The retired client-side invention: with entry 150 and risk 5 the old
    // defaultOverlay produced T2 = entry + 2R = 160 and T3 = entry + 3R = 165
    // regardless of what the strategy actually targeted. Neither may appear.
    expect(screen.queryByText('160.00')).toBeNull();
    expect(screen.queryByText('165.00')).toBeNull();
  });

  it('falls back to R steps past target_price when the ladder is absent', () => {
    // A scan result rehydrated from localStorage before `targets` existed.
    render(<StockPositionCard card={makeCard()} strategyKey="pullback_ema" />);

    // T1 = target_price = 160 (= entry + 2R for this fixture).
    expect(screen.getAllByText('160.00')).toHaveLength(2);
    // Missing rungs step ONE MORE R past the previous rung — 165 then 170 — NOT
    // 2R/3R measured from entry. Measuring from entry can place T2 behind a
    // strategy-derived T1, and stockPositionLevels() sorts nearest-first into
    // the portfolio, so the persisted targets[0] (the only rung TP_HIT fires on)
    // would stop being the rung the card labelled T1.
    expect(screen.getByText('165.00')).toBeTruthy();
    expect(screen.getByText('170.00')).toBeTruthy();
  });

  it('treats an empty ladder as absent (?.length, not ??)', () => {
    // `targets: []` must take the same path as `targets: undefined` — a `??`
    // would keep the empty array and leave every rung undefined.
    render(<StockPositionCard card={makeCard([])} strategyKey="pullback_ema" />);
    expect(screen.getAllByText('160.00')).toHaveLength(2);
    expect(screen.getByText('165.00')).toBeTruthy();
    expect(screen.getByText('170.00')).toBeTruthy();
    expect(screen.queryByText('NaN')).toBeNull();
  });
});

// ─── Approach B affordances ───────────────────────────────────────────────────

const mockEstimate = api.getStockFirstPassage as jest.Mock;
const mockStructural = api.getStructuralStop as jest.Mock;

function estimateFixture(modelCaveat: string | null = null) {
  return {
    targets: [
      { price: 155, probability: 0.62, expectedDays: 4 },
      { price: 162, probability: 0.31, expectedDays: 8 },
      { price: 170, probability: 0.0, expectedDays: null },
    ],
    invalidation: { probability: 0.28, expectedDays: 6 },
    horizonDays: 10,
    modelCaveat,
  };
}

async function clickButton(name: RegExp) {
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name }));
  });
}

describe('StockPositionCard — first-passage Estimate', () => {
  beforeEach(() => {
    usePortfolioStore.setState({ positions: [], lastSyncError: null });
    mockEstimate.mockReset();
    mockStructural.mockReset();
  });
  afterEach(() => jest.clearAllMocks());

  it('renders one row per target with its probability and expected days', async () => {
    mockEstimate.mockResolvedValue(estimateFixture());
    render(<StockPositionCard card={makeCard([155, 162, 170])} strategyKey="pullback_ema" />);

    await clickButton(/^estimate$/i);

    expect(await screen.findByText('62%')).toBeTruthy();
    expect(screen.getByText('31%')).toBeTruthy();
    // A zero-probability rung says "unlikely" rather than "~0d", which would
    // read as "it happens on day zero".
    expect(screen.getByText('unlikely')).toBeTruthy();
    expect(screen.getByText('~4d')).toBeTruthy();
    // Stop-out row.
    expect(screen.getByText('28%')).toBeTruthy();
  });

  it('always states the holding window, in trading days', async () => {
    mockEstimate.mockResolvedValue(estimateFixture());
    render(<StockPositionCard card={makeCard([155, 162, 170])} strategyKey="pullback_ema" />);
    await clickButton(/^estimate$/i);
    // A probability without its window is meaningless — this must never become
    // optional chrome. "trading days", not "days": the window is a bar count.
    expect(await screen.findByText(/within 10 trading days/i)).toBeTruthy();
  });

  it('sends the EDITED overlay, not the pristine signal', async () => {
    mockEstimate.mockResolvedValue(estimateFixture());
    render(<StockPositionCard card={makeCard([155, 162, 170])} strategyKey="pullback_ema" />);
    await clickButton(/^estimate$/i);

    expect(mockEstimate).toHaveBeenCalledTimes(1);
    expect(mockEstimate.mock.calls[0][0]).toMatchObject({
      symbol: 'AAPL',
      direction: 'Bullish',
      strategy: 'pullback_ema',
      stock_price: 150,
      stop_price: 145,
      targets: [155, 162, 170],
    });
  });

  it('renders the GBM caveat verbatim when the backend sets one', async () => {
    const caveat = 'Approximate for mean-reversion strategies: drift is assumed constant.';
    mockEstimate.mockResolvedValue(estimateFixture(caveat));
    render(<StockPositionCard card={makeCard([155, 162, 170])} strategyKey="mean_reversion_bb" />);
    await clickButton(/^estimate$/i);
    expect(await screen.findByText(caveat)).toBeTruthy();
  });

  it('renders no caveat when the backend sets none', async () => {
    const caveat = 'Approximate for mean-reversion strategies: drift is assumed constant.';
    mockEstimate.mockResolvedValue(estimateFixture(null));
    render(<StockPositionCard card={makeCard([155, 162, 170])} strategyKey="breakout_base" />);
    await clickButton(/^estimate$/i);
    await screen.findByText('62%');
    expect(screen.queryByText(caveat)).toBeNull();
  });
});

describe('StockPositionCard — Check structure', () => {
  beforeEach(() => {
    usePortfolioStore.setState({ positions: [], lastSyncError: null });
    mockEstimate.mockReset();
    mockStructural.mockReset();
    global.fetch = jest.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({}),
    }) as unknown as typeof fetch;
  });
  afterEach(() => jest.clearAllMocks());

  it('carries the checked structural level into the added position', async () => {
    mockStructural.mockResolvedValue({
      available: true, price: 143.25, source: 'order_block', confidence: 80, distancePct: -4.5,
    });
    render(<StockPositionCard card={makeCard([155, 162, 170])} strategyKey="pullback_ema" />);

    await clickButton(/check structure/i);
    expect(await screen.findByText('143.25')).toBeTruthy();

    await clickButton(/add to portfolio/i);

    await waitFor(() => {
      expect(usePortfolioStore.getState().positions).toHaveLength(1);
    });
    // This is what makes STRUCTURAL_STOP_BREACHED able to fire for a stock
    // position — it was previously reachable only from the options path.
    expect(usePortfolioStore.getState().positions[0].structuralStop).toBe(143.25);
  });

  it('leaves structuralStop null when the user never checked structure', async () => {
    render(<StockPositionCard card={makeCard([155, 162, 170])} strategyKey="pullback_ema" />);
    await clickButton(/add to portfolio/i);
    await waitFor(() => {
      expect(usePortfolioStore.getState().positions).toHaveLength(1);
    });
    expect(usePortfolioStore.getState().positions[0].structuralStop).toBeNull();
    expect(mockStructural).not.toHaveBeenCalled();
  });

  it('reports a symbol with no structural level instead of rendering nothing', async () => {
    mockStructural.mockResolvedValue({
      available: false, price: null, source: null, confidence: null, distancePct: null,
    });
    render(<StockPositionCard card={makeCard([155, 162, 170])} strategyKey="pullback_ema" />);
    await clickButton(/check structure/i);
    expect(await screen.findByText(/no structural level found/i)).toBeTruthy();
  });
});
