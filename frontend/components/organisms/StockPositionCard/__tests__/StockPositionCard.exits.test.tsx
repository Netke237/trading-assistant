import { render, screen } from '@testing-library/react';
import { StockPositionCard } from '@/components/organisms/StockPositionCard';
import { usePortfolioStore } from '@/lib/portfolioStore';
import type { PositionCardData } from '@/types/stockDomain';

// api + heavy children are modules (not stores) — mocking them is correct.
jest.mock('@/lib/api', () => ({ api: { getBrokerStatus: jest.fn().mockResolvedValue({}) } }));
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
