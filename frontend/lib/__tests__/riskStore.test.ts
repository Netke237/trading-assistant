import { renderHook, act } from '@testing-library/react';
import { useRiskStore } from '@/lib/riskStore';
import type { PortfolioPosition } from '@/types/domain';

const DEFAULT_LIMITS = {
  maxSingleTradeExposurePct: 0.05,
  maxTotalExposurePct: 0.25,
  maxConcurrentPositions: 10,
  maxDailyRecommendations: 5,
  portfolioValue: 100000,
  maxLossPerTradePct: 0.0375, maxSingleStockPositionPct: 0.2, maxTotalStockExposurePct: 1,
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
          largestConcentrationSymbol: '—', stockExposurePct: 0, largestStockConcentrationPct: 0, largestStockConcentrationSymbol: '—',
          status: 'PASS',
        },
        symbols: [],
        portfolioValueUpdatedAt: null,
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

  it('setLimits stamps portfolioValueUpdatedAt when portfolioValue actually changes', () => {
    jest.useFakeTimers().setSystemTime(new Date('2026-04-08T12:00:00Z'));
    const { result } = renderHook(() => useRiskStore());
    expect(result.current.portfolioValueUpdatedAt).toBeNull();
    act(() => {
      result.current.setLimits({ ...DEFAULT_LIMITS, portfolioValue: 75000 });
    });
    expect(result.current.portfolioValueUpdatedAt).toBe('2026-04-08T12:00:00.000Z');
    jest.useRealTimers();
  });

  it('setLimits leaves portfolioValueUpdatedAt untouched when portfolioValue is unchanged', () => {
    const { result } = renderHook(() => useRiskStore());
    act(() => {
      // A no-op resync (e.g. RiskForm's hydration effect re-pushing the same
      // fetched value) must not look like a fresh edit.
      result.current.setLimits({ ...DEFAULT_LIMITS, maxConcurrentPositions: 8 });
    });
    expect(result.current.portfolioValueUpdatedAt).toBeNull();
  });

  it('setLimits with isUserEdit:false does not stamp portfolioValueUpdatedAt even when portfolioValue differs', () => {
    // Regression: RiskForm's fetch-on-mount hydration effect calls setLimits
    // purely to reconcile the store with whatever the backend currently
    // holds (e.g. a value changed in another session/device) — that is NOT
    // the user editing the field, and must not reset the staleness nudge.
    jest.useFakeTimers().setSystemTime(new Date('2026-04-08T12:00:00Z'));
    const { result } = renderHook(() => useRiskStore());
    act(() => {
      useRiskStore.setState({ portfolioValueUpdatedAt: '2026-01-01T00:00:00.000Z' });
    });
    act(() => {
      result.current.setLimits({ ...DEFAULT_LIMITS, portfolioValue: 250000 }, { isUserEdit: false });
    });
    expect(result.current.limits.portfolioValue).toBe(250000);
    expect(result.current.portfolioValueUpdatedAt).toBe('2026-01-01T00:00:00.000Z');
    jest.useRealTimers();
  });

  it('incrementDaily increases count', () => {
    const { result } = renderHook(() => useRiskStore());
    act(() => {
      result.current.incrementDaily();
    });
    expect(result.current.dailyRecommendations).toBe(1);
  });
});

// Mirrors the same technique used in calendar/__tests__/page.test.tsx for the sibling
// UTC-vs-local-midnight bug — mocks Date.prototype's local getters to simulate a timezone
// whose local calendar day differs from the instant's UTC calendar day, without relying on
// process.env.TZ (which doesn't reliably propagate in this Jest/Node sandbox).
function mockLocalDayOffsetFromUtc(offsetDays: number): void {
  const shift = (d: Date) => new Date(d.getTime() + offsetDays * 86_400_000);
  jest.spyOn(Date.prototype, 'getFullYear').mockImplementation(function (this: Date) {
    return shift(this).getUTCFullYear();
  });
  jest.spyOn(Date.prototype, 'getMonth').mockImplementation(function (this: Date) {
    return shift(this).getUTCMonth();
  });
  jest.spyOn(Date.prototype, 'getDate').mockImplementation(function (this: Date) {
    return shift(this).getUTCDate();
  });
}

describe('riskStore daily-recommendation-limit reset — local calendar day, not UTC', () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('does not reset the daily counter early for a UTC-behind zone in the evening', () => {
    // Real UTC instant: 2026-03-16T02:30:00Z. A UTC-behind zone (e.g. US Eastern, UTC-5) has
    // local wall-clock time 2026-03-15 21:30 -- still March 15th locally, one UTC calendar day
    // behind. Simulate that by shifting the local getters -1 day relative to UTC.
    jest.useFakeTimers().setSystemTime(new Date('2026-03-16T02:30:00Z'));
    mockLocalDayOffsetFromUtc(-1);

    const { result } = renderHook(() => useRiskStore());
    act(() => {
      useRiskStore.setState({ dailyRecommendations: 3, lastResetDate: '2026-03-15' });
    });
    act(() => {
      result.current.incrementDaily();
    });

    // Bug (naive new Date().toISOString()): lastResetDate '2026-03-15' !== UTC today
    // '2026-03-16' -> wrongly resets to 1. Fixed: local today is still '2026-03-15' -> increments.
    expect(result.current.dailyRecommendations).toBe(4);
    expect(result.current.lastResetDate).toBe('2026-03-15');

    jest.useRealTimers();
  });

  it('does reset the daily counter once the local calendar day genuinely advances', () => {
    jest.useFakeTimers().setSystemTime(new Date('2026-03-17T02:30:00Z'));
    mockLocalDayOffsetFromUtc(-1); // local: 2026-03-16, genuinely a new day vs. lastResetDate

    const { result } = renderHook(() => useRiskStore());
    act(() => {
      useRiskStore.setState({ dailyRecommendations: 3, lastResetDate: '2026-03-15' });
    });
    act(() => {
      result.current.incrementDaily();
    });

    expect(result.current.dailyRecommendations).toBe(1);
    expect(result.current.lastResetDate).toBe('2026-03-16');

    jest.useRealTimers();
  });
});

// NO-LIVE-QUOTE NLQ-1 (round-1 F2): RiskPanel's exposure must count a position
// without a quote at its entry price (exposureMark), not at its $0 mark.
describe('riskStore exposure of a position without a quote', () => {
  it('computeMetrics includes the flagged row at entry', () => {
    const { result } = renderHook(() => useRiskStore());
    act(() => {
      result.current.computeMetrics([
        makePosition({ symbol: 'AAPL', currentPrice: 5, contracts: 2 }),
        makePosition({ symbol: 'MSFT', recId: 'REC-NQ', entryPrice: 40, currentPrice: 0, contracts: 5,
                       pnlDollar: 0, pnlPct: 0, quoteUnavailable: true }),
      ]);
    });
    // 5 x 100 x 2 + 40 x 100 x 5 = 1,000 + 20,000
    expect(result.current.metrics.totalExposurePct).toBeCloseTo(21000 / 100000, 10);
    expect(result.current.metrics.largestConcentrationSymbol).toBe('MSFT');
  });
});
