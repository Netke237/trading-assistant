import { renderHook, act } from '@testing-library/react';
import { useRiskStore } from '@/lib/riskStore';
import type { PortfolioPosition, TradeCardData } from '@/types/domain';

const DEFAULT_LIMITS = {
  maxSingleTradeExposurePct: 0.05,
  maxTotalExposurePct: 0.25,
  maxConcurrentPositions: 10,
  maxDailyRecommendations: 5,
  portfolioValue: 100000,
};

function makePosition(overrides: Partial<PortfolioPosition> = {}): PortfolioPosition {
  return {
    symbol: 'AAPL',
    contract: 'AAPL 190C 05/16',
    direction: 'Bullish',
    entryDate: '2026-04-08',
    expiry: '2026-05-16',
    dteRemaining: 28,
    dteTotal: 38,
    entryPrice: 4.15,
    currentPrice: 5.02,
    pnlDollar: 870,
    pnlPct: 20.96,
    stop: 180.0,
    targets: [{ id: 'tp1', stockPrice: 198.0, contractsToSell: 2, status: 'PENDING' }],
    status: 'PASS',
    contracts: 2,
    recId: 'REC-TEST-001',
    ...overrides,
  };
}

function makeCard(overrides: Partial<TradeCardData> = {}): TradeCardData {
  return {
    symbol: 'TSLA',
    company: 'Tesla Inc.',
    price: 250,
    direction: 'Bullish',
    status: 'PASS',
    stockScore: 80,
    stockConfidence: 'PASS',
    stockBreakdown: { trend: 80, pullback: 80, trigger: 80, event: 80, volatility: 80 },
    contract: 'TSLA 260C 05/16',
    contractScore: 75,
    contractConfidence: 'PASS',
    contractBreakdown: { dteFit: 75, delta: 75, ivAttractiveness: 75, liquidity: 75, spread: 75 },
    contractDetails: { strike: 260, expiry: '2026-05-16', right: 'C', mid: 2.5, delta: 0.5, theta: -0.1, ivRank: 50, dte: 24 },
    entry: { limit: 2.5, maxFill: 2.63, orderType: 'Limit' },
    exit: { invalidation: 240, premiumStop: 1.5, timeStopDays: 10, target: 270, targets: [{ id: 'tp1', stockPrice: 270, contractsToSell: 1, status: 'PENDING' }] },
    rrRatio: 2.5,
    rrModel: 'Heston repriced',
    finalStatus: 'PASS',
    ...overrides,
  };
}

describe('riskStore', () => {
  beforeEach(() => {
    act(() => {
      useRiskStore.setState({
        limits: { ...DEFAULT_LIMITS },
        dailyRecommendations: 0,
        lastResetDate: new Date().toISOString().split('T')[0],
        metrics: {
          totalExposurePct: 0,
          concurrentPositions: 0,
          dailyRecommendations: 0,
          largestConcentrationPct: 0,
          largestConcentrationSymbol: '—',
          status: 'PASS',
        },
        symbols: [],
      });
    });
  });

  it('has default limits', () => {
    const { result } = renderHook(() => useRiskStore());
    expect(result.current.limits).toEqual(DEFAULT_LIMITS);
  });

  it('sets limits', () => {
    const { result } = renderHook(() => useRiskStore());
    act(() => {
      result.current.setLimits({ ...DEFAULT_LIMITS, portfolioValue: 100000 });
    });
    expect(result.current.limits.portfolioValue).toBe(100000);
  });

  it('checkTrade approves a clean trade', () => {
    const { result } = renderHook(() => useRiskStore());
    const check = result.current.checkTrade(makeCard(), 1);
    expect(check.approved).toBe(true);
    expect(check.reasons).toEqual([]);
  });

  it('checkTrade rejects missing invalidation', () => {
    const { result } = renderHook(() => useRiskStore());
    const card = makeCard({ exit: { invalidation: 0, premiumStop: 1.5, timeStopDays: 10, target: 0, targets: [] } });
    const check = result.current.checkTrade(card, 1);
    expect(check.approved).toBe(false);
    expect(check.reasons).toContain('missing_invalidation');
  });

  it('checkTrade rejects duplicate symbol', () => {
    const { result } = renderHook(() => useRiskStore());
    act(() => {
      result.current.computeMetrics([makePosition({ symbol: 'TSLA' })]);
    });
    const check = result.current.checkTrade(makeCard(), 1);
    expect(check.approved).toBe(false);
    expect(check.reasons).toContain('duplicate_symbol');
  });

  it('checkTrade rejects max concurrent positions', () => {
    const { result } = renderHook(() => useRiskStore());
    const positions = Array.from({ length: 10 }, (_, i) => makePosition({ symbol: `SYM${i}`, recId: `REC-${i}` }));
    act(() => {
      result.current.computeMetrics(positions);
    });
    const check = result.current.checkTrade(makeCard(), 1);
    expect(check.approved).toBe(false);
    expect(check.reasons).toContain('max_concurrent_positions_reached');
  });

  it('checkTrade rejects max daily recommendations', () => {
    const { result } = renderHook(() => useRiskStore());
    act(() => {
      for (let i = 0; i < 5; i++) {
        result.current.incrementDaily();
      }
    });
    const check = result.current.checkTrade(makeCard(), 1);
    expect(check.approved).toBe(false);
    expect(check.reasons).toContain('max_daily_recommendations_reached');
  });

  it('computeMetrics calculates portfolio exposure', () => {
    const { result } = renderHook(() => useRiskStore());
    act(() => {
      result.current.computeMetrics([makePosition({ currentPrice: 5, contracts: 2 })]);
    });
    expect(result.current.metrics.totalExposurePct).toBe(1000 / 100000);
    expect(result.current.metrics.concurrentPositions).toBe(1);
    expect(result.current.metrics.status).toBe('PASS');
  });

  it('computeMetrics tracks largest concentration', () => {
    const { result } = renderHook(() => useRiskStore());
    act(() => {
      result.current.computeMetrics([
        makePosition({ symbol: 'AAPL', currentPrice: 10, contracts: 5 }),
        makePosition({ symbol: 'MSFT', currentPrice: 5, contracts: 2 }),
      ]);
    });
    expect(result.current.metrics.largestConcentrationSymbol).toBe('AAPL');
    expect(result.current.metrics.largestConcentrationPct).toBe(5000 / 100000);
  });

  it('incrementDaily increases count', () => {
    const { result } = renderHook(() => useRiskStore());
    act(() => {
      result.current.incrementDaily();
    });
    expect(result.current.dailyRecommendations).toBe(1);
  });
});
