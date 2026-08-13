import { renderHook, act } from '@testing-library/react';
import { useRiskStore } from '@/lib/riskStore';
import type { PortfolioPosition } from '@/types/domain';

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
