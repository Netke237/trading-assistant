import {
  capitalAtRisk,
  exposurePct,
  checkInvalidation,
  totalNotional,
  computePortfolioRiskMetrics,
  checkTradeRisk,
  maxLossAtStop,
  resolveMaxLossLimitDollar,
  recommendedContractSize,
  formatRecommendedContractSizeRaw,
} from '@/lib/risk';
import type { PortfolioPosition, RiskLimits, TradeCardData, ExitPlan } from '@/types/domain';

const DEFAULT_LIMITS: RiskLimits = {
  maxSingleTradeExposurePct: 0.05,
  maxTotalExposurePct: 0.25,
  maxConcurrentPositions: 10,
  maxDailyRecommendations: 5,
  portfolioValue: 50000,
  maxLossPerTradePct: 0.0375,
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

function makeExitPlan(overrides: Partial<ExitPlan['stop']> = {}): ExitPlan {
  return {
    computedAt: '2026-04-08T00:00:00.000Z',
    stop: {
      price: 240,
      source: 'structural',
      contractPrice: 1.0,
      rrModel: 'Heston repriced',
      structuralSource: 'swing_low',
      structuralConfidence: 0.8,
      structuralPrice: 240,
      atrFloorPrice: 230,
      distanceDollar: 10,
      ...overrides,
    },
    targets: [],
    atr: 3.5,
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

describe('risk helpers', () => {
  describe('capitalAtRisk', () => {
    it('computes mid * contracts * 100', () => {
      expect(capitalAtRisk(2.5, 2)).toBe(500);
      expect(capitalAtRisk(5, 1)).toBe(500);
    });
  });

  describe('exposurePct', () => {
    it('returns notional / portfolioValue', () => {
      expect(exposurePct(5000, 50000)).toBe(0.1);
    });

    it('returns 0 when portfolioValue is 0 or negative', () => {
      expect(exposurePct(5000, 0)).toBe(0);
      expect(exposurePct(5000, -100)).toBe(0);
    });
  });

  describe('checkInvalidation', () => {
    it('returns true for positive numbers', () => {
      expect(checkInvalidation(180)).toBe(true);
    });

    it('returns false for 0 or undefined', () => {
      expect(checkInvalidation(0)).toBe(false);
      expect(checkInvalidation(undefined)).toBe(false);
    });
  });

  describe('totalNotional', () => {
    it('sums currentPrice * 100 * contracts', () => {
      const positions = [
        makePosition({ currentPrice: 5, contracts: 2 }),
        makePosition({ currentPrice: 10, contracts: 1 }),
      ];
      expect(totalNotional(positions)).toBe(5 * 100 * 2 + 10 * 100 * 1);
    });
  });

  describe('computePortfolioRiskMetrics', () => {
    it('returns PASS when all within limits', () => {
      const positions = [makePosition({ currentPrice: 5, contracts: 1 })];
      const metrics = computePortfolioRiskMetrics(positions, DEFAULT_LIMITS, 0);
      expect(metrics.status).toBe('PASS');
      expect(metrics.totalExposurePct).toBe(500 / 50000);
      expect(metrics.concurrentPositions).toBe(1);
    });

    it('returns REJECT when total exposure exceeds limit', () => {
      const positions = [makePosition({ currentPrice: 200, contracts: 10 })];
      const metrics = computePortfolioRiskMetrics(positions, DEFAULT_LIMITS, 0);
      expect(metrics.status).toBe('REJECT');
    });

    it('returns CAUTION when total exposure is near limit', () => {
      const positions = [makePosition({ currentPrice: 11, contracts: 10 })];
      const metrics = computePortfolioRiskMetrics(positions, DEFAULT_LIMITS, 0);
      expect(metrics.totalExposurePct).toBe(11000 / 50000); // 0.22 > 80% of 0.25 limit
      expect(metrics.status).toBe('CAUTION');
    });

    it('tracks largest concentration', () => {
      const positions = [
        makePosition({ symbol: 'AAPL', currentPrice: 10, contracts: 5 }),
        makePosition({ symbol: 'MSFT', currentPrice: 5, contracts: 2 }),
      ];
      const metrics = computePortfolioRiskMetrics(positions, DEFAULT_LIMITS, 0);
      expect(metrics.largestConcentrationSymbol).toBe('AAPL');
      expect(metrics.largestConcentrationPct).toBe(5000 / 50000);
    });
  });

  describe('checkTradeRisk', () => {
    it('approves a clean trade within limits', () => {
      const result = checkTradeRisk(makeCard(), 1, DEFAULT_LIMITS, [], 0);
      expect(result.approved).toBe(true);
      expect(result.reasons).toEqual([]);
      expect(result.capitalAtRisk).toBe(250);
      expect(result.singleExposurePct).toBe(250 / 50000);
    });

    it('rejects when single trade exposure is too high', () => {
      const card = makeCard({ contractDetails: { strike: 260, expiry: '2026-05-16', right: 'C', mid: 10, delta: 0.5, theta: -0.1, ivRank: 50, dte: 24 } });
      const result = checkTradeRisk(card, 10, DEFAULT_LIMITS, [], 0);
      expect(result.approved).toBe(false);
      expect(result.reasons).toContain('single_trade_exposure_too_high');
    });

    it('rejects when total exposure limit would be reached', () => {
      const positions = [makePosition({ currentPrice: 20, contracts: 50 })]; // 100k notional
      const result = checkTradeRisk(makeCard(), 1, DEFAULT_LIMITS, positions, 0);
      expect(result.approved).toBe(false);
      expect(result.reasons).toContain('total_exposure_limit_reached');
    });

    it('rejects when max concurrent positions reached', () => {
      const positions = Array.from({ length: 10 }, (_, i) => makePosition({ symbol: `SYM${i}`, recId: `REC-${i}` }));
      const result = checkTradeRisk(makeCard(), 1, DEFAULT_LIMITS, positions, 0);
      expect(result.approved).toBe(false);
      expect(result.reasons).toContain('max_concurrent_positions_reached');
    });

    it('rejects when symbol already exists in portfolio', () => {
      const positions = [makePosition({ symbol: 'TSLA' })];
      const result = checkTradeRisk(makeCard(), 1, DEFAULT_LIMITS, positions, 0);
      expect(result.approved).toBe(false);
      expect(result.reasons).toContain('duplicate_symbol');
    });

    it('rejects when invalidation is missing', () => {
      const card = makeCard({ exit: { invalidation: 0, premiumStop: 1.5, timeStopDays: 10, target: 0, targets: [] } });
      const result = checkTradeRisk(card, 1, DEFAULT_LIMITS, [], 0);
      expect(result.approved).toBe(false);
      expect(result.reasons).toContain('missing_invalidation');
    });

    it('rejects when daily recommendations reached', () => {
      const result = checkTradeRisk(makeCard(), 1, DEFAULT_LIMITS, [], 5);
      expect(result.approved).toBe(false);
      expect(result.reasons).toContain('max_daily_recommendations_reached');
    });

    it('skips the max-loss check entirely when no exit plan has been computed', () => {
      const result = checkTradeRisk(makeCard(), 1, DEFAULT_LIMITS, [], 0);
      expect(result.reasons).not.toContain('max_loss_per_trade_exceeded');
      expect(result.maxLossAtStop).toBeUndefined();
      expect(result.maxLossLimitDollar).toBeUndefined();
    });

    it('rejects when the loss at the exit-plan final stop exceeds the per-trade limit', () => {
      // mid 2.5, stop contractPrice 0.5 -> $200/contract loss; limit is 3.75% of 50,000 = $1,875
      const card = makeCard({ exit: { ...makeCard().exit, exitPlan: makeExitPlan({ contractPrice: 0.5 }) } });
      const result = checkTradeRisk(card, 10, DEFAULT_LIMITS, [], 0);
      expect(result.approved).toBe(false);
      expect(result.reasons).toContain('max_loss_per_trade_exceeded');
      expect(result.maxLossAtStop).toBe(2000);
      expect(result.maxLossLimitDollar).toBe(1875);
    });

    it('approves when the loss at the exit-plan final stop is within the per-trade limit', () => {
      const card = makeCard({ exit: { ...makeCard().exit, exitPlan: makeExitPlan({ contractPrice: 2.0 }) } });
      const result = checkTradeRisk(card, 1, DEFAULT_LIMITS, [], 0);
      expect(result.approved).toBe(true);
      expect(result.reasons).not.toContain('max_loss_per_trade_exceeded');
    });
  });
});

describe('maxLossAtStop', () => {
  it('is entry premium minus stop contract price, times contracts * 100', () => {
    expect(maxLossAtStop(2.5, 1.0, 2)).toBe(300);
  });

  it('floors at 0 when the stop reprices at or above entry (not actually a loss)', () => {
    expect(maxLossAtStop(2.5, 3.0, 2)).toBe(0);
  });
});

describe('resolveMaxLossLimitDollar', () => {
  it('uses the global percent when no override is set', () => {
    expect(resolveMaxLossLimitDollar(50000, 0.0375)).toBe(1875);
    expect(resolveMaxLossLimitDollar(50000, 0.0375, null)).toBe(1875);
  });

  it('uses a percent override as a fraction of portfolioValue', () => {
    expect(resolveMaxLossLimitDollar(50000, 0.0375, { mode: 'percent', value: 0.02 })).toBe(1000);
  });

  it('uses a dollar override verbatim, ignoring portfolioValue', () => {
    expect(resolveMaxLossLimitDollar(50000, 0.0375, { mode: 'dollar', value: 300 })).toBe(300);
  });
});

describe('recommendedContractSize', () => {
  it('floors risk budget divided by risk per contract, keeping the raw decimal too', () => {
    expect(recommendedContractSize(1000, 270)).toEqual({ raw: 1000 / 270, recommended: 3 });
  });

  it('recommends 0 (not null) when the budget affords less than one contract', () => {
    expect(recommendedContractSize(100, 270)).toEqual({ raw: 100 / 270, recommended: 0 });
  });

  it('recommends exactly the whole-number result when it divides evenly', () => {
    expect(recommendedContractSize(1000, 250)).toEqual({ raw: 4, recommended: 4 });
  });

  it('returns null for a non-positive risk budget', () => {
    expect(recommendedContractSize(0, 270)).toBeNull();
    expect(recommendedContractSize(-100, 270)).toBeNull();
  });

  it('returns null for a non-positive risk per contract (stop reprices at or above entry — no real loss on this leg)', () => {
    expect(recommendedContractSize(1000, 0)).toBeNull();
    expect(recommendedContractSize(1000, -50)).toBeNull();
  });

  it('does not under-recommend by one contract at an exact-multiple budget corrupted by floating-point subtraction noise', () => {
    // maxLossAtStop(1.00, 0.41, 1) -> (1.00 - 0.41) * 100 = 59.00000000000001
    // in IEEE754, not the exact 59. A $118 budget genuinely, exactly affords
    // 2 contracts at that per-contract risk -- Math.floor(raw) alone would
    // compute 118 / 59.00000000000001 = 1.9999999999999998 and wrongly floor
    // to 1.
    const riskPerContract = maxLossAtStop(1.0, 0.41, 1);
    expect(riskPerContract).not.toBe(59); // sanity: reproduces the fp noise this guards against
    const result = recommendedContractSize(118, riskPerContract);
    expect(result?.recommended).toBe(2);
  });

  it('still floors a genuinely short budget to the lower count, not nudged up by the noise guard', () => {
    // 199.50 / 200 = 0.9975 -- really short of 1 contract, not fp noise.
    expect(recommendedContractSize(199.5, 200)).toEqual({ raw: 0.9975, recommended: 0 });
  });
});

describe('formatRecommendedContractSizeRaw', () => {
  it('always shows size.recommended as the whole part, by construction — it never comes from anywhere else', () => {
    expect(formatRecommendedContractSizeRaw({ raw: 0.9975, recommended: 0 })).toBe('0.99');
    expect(formatRecommendedContractSizeRaw({ raw: 3.71, recommended: 3 })).toBe('3.71');
    expect(formatRecommendedContractSizeRaw({ raw: 25, recommended: 25 })).toBe('25.00');
  });

  it('cannot disagree with recommended at a raw*100 fp-noise boundary, unlike the two prior (now-replaced) implementations', () => {
    // $3,748.83 budget / $43.09 per contract = 87 exactly in real arithmetic
    // (43.09 * 87 === 3748.83), but riskBudget / riskPerContract computes as
    // 86.99999999999999 in IEEE754. Two earlier versions of this formatter
    // each independently re-floored `raw` and could, at their own narrower
    // boundary, render "86.99" next to "87 contracts" -- self-contradictory.
    // Deriving the decimal from `recommended` instead makes that structurally
    // impossible: the whole part is always exactly `recommended`.
    const result = recommendedContractSize(3748.83, 43.09);
    expect(result?.raw).not.toBe(87); // sanity: reproduces the fp noise this guards against
    expect(result?.recommended).toBe(87);
    expect(formatRecommendedContractSizeRaw(result!)).toBe('87.00');
  });

  it('guards the fractional remainder against sub-epsilon negative noise (raw fractionally below recommended)', () => {
    // Pathological but not impossible if a future caller constructs the
    // object by hand rather than via recommendedContractSize: raw sitting a
    // hair below the integer recommended claims to be.
    expect(formatRecommendedContractSizeRaw({ raw: 4.999999999999999, recommended: 5 })).toBe('5.00');
  });
});
