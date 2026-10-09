import {
  capitalAtRisk,
  exposurePct,
  checkInvalidation,
  checkMethodPick,
  totalNotional,
  computePortfolioRiskMetrics,
  checkTradeRisk,
  maxLossAtStop,
  resolveMaxLossLimitDollar,
  recommendedContractSize,
  formatRecommendedContractSizeRaw,
  stopPremiumRisk,
  formatStopPremiumRisk,
  formatStopLossHeadline,
  formatStopLossBadge,
  stopLossIsTotalOnPrintedFigures,
  formatStopLossPct,
} from '@/lib/risk';
import type { PortfolioPosition, RiskLimits, TradeCardData, ExitPlan, StopCostOut, MethodPick } from '@/types/domain';

const pick = (over: Partial<MethodPick> = {}): MethodPick => ({
  method: 'monte_carlo',
  rowStockPrice: 197.5,
  rowOptionPrice: 6.24,
  stopBasis: 'stock',
  pickedAt: '2026-09-14T10:00:00.000Z',
  ...over,
});

const DEFAULT_LIMITS: RiskLimits = {
  maxSingleTradeExposurePct: 0.05,
  maxTotalExposurePct: 0.25,
  maxConcurrentPositions: 10,
  maxDailyRecommendations: 5,
  portfolioValue: 50000,
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

  describe('checkMethodPick (Phase G piece 5, build step 4, spec test 7)', () => {
    it('returns false for null and undefined', () => {
      expect(checkMethodPick(null)).toBe(false);
      expect(checkMethodPick(undefined)).toBe(false);
    });

    it('returns true for a well-formed pick', () => {
      expect(checkMethodPick(pick())).toBe(true);
    });

    it('returns true even when rowStockPrice is null (Barrier Race never has one, §7.4)', () => {
      expect(checkMethodPick(pick({ rowStockPrice: null }))).toBe(true);
    });

    it('returns true even when rowOptionPrice is null (Ladder/Arithmetic never have one, §7.4)', () => {
      expect(checkMethodPick(pick({ rowOptionPrice: null }))).toBe(true);
    });

    it('is true for all four PickedMethod values', () => {
      for (const method of ['arithmetic', 'monte_carlo', 'ladder', 'barrier_race'] as const) {
        expect(checkMethodPick(pick({ method }))).toBe(true);
      }
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
      const result = checkTradeRisk(makeCard(), 1, DEFAULT_LIMITS, [], 0, null, undefined, pick());
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

    // Review fix #4 (D5): no protective order is placed, so a long option can
    // lose its whole premium. The per-trade loss limit therefore caps premium
    // too: the effective option cap is min(single-position cap, loss limit).
    it('rejects an option premium above maxLossPerTradePct even when under the single-position cap', () => {
      const limits = { ...DEFAULT_LIMITS, portfolioValue: 100000 };
      const card = makeCard({ contractDetails: { strike: 260, expiry: '2026-05-16', right: 'C', mid: 4.5, delta: 0.5, theta: -0.1, ivRank: 50, dte: 24 } });
      const result = checkTradeRisk(card, 10, limits, [], 0, null, undefined, pick()); // $4,500 = 4.5%
      expect(result.singleExposurePct).toBeCloseTo(0.045, 10);
      expect(result.reasons).toContain('single_trade_exposure_too_high');
      expect(result.approved).toBe(false);
    });

    it('approves an option premium exactly at maxLossPerTradePct', () => {
      const limits = { ...DEFAULT_LIMITS, portfolioValue: 100000 };
      const card = makeCard({ contractDetails: { strike: 260, expiry: '2026-05-16', right: 'C', mid: 3.75, delta: 0.5, theta: -0.1, ivRank: 50, dte: 24 } });
      const result = checkTradeRisk(card, 10, limits, [], 0, null, undefined, pick()); // $3,750 = 3.75%
      expect(result.reasons).not.toContain('single_trade_exposure_too_high');
    });

    it('keeps the single-position cap binding when the loss limit is looser', () => {
      const limits = { ...DEFAULT_LIMITS, portfolioValue: 100000, maxLossPerTradePct: 0.10 };
      const card = makeCard({ contractDetails: { strike: 260, expiry: '2026-05-16', right: 'C', mid: 5.5, delta: 0.5, theta: -0.1, ivRank: 50, dte: 24 } });
      const result = checkTradeRisk(card, 10, limits, [], 0, null, undefined, pick()); // 5.5% > 5%
      expect(result.reasons).toContain('single_trade_exposure_too_high');
    });

    it('rejects when total exposure limit would be reached', () => {
      const positions = [makePosition({ currentPrice: 20, contracts: 50 })]; // 100k notional
      const result = checkTradeRisk(makeCard(), 1, DEFAULT_LIMITS, positions, 0);
      expect(result.approved).toBe(false);
      expect(result.reasons).toContain('total_exposure_limit_reached');
    });

    // STOCK-SENDS (plan C2): the options basket's total counts OPTION rows
    // only; stock rows count against the stock total on the server.
    it('does not count a stock row toward the option total', () => {
      const stock = makePosition({ symbol: 'MSFT', contract: 'MSFT|STOCK', currentPrice: 200, contracts: 300, recId: 'S' }); // $60k
      const result = checkTradeRisk(makeCard(), 1, DEFAULT_LIMITS, [stock], 0, null, undefined, pick());
      expect(result.reasons).not.toContain('total_exposure_limit_reached');
      expect(result.approved).toBe(true);
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

    it('rejects a card whose stop the v15 migration stripped', () => {
      // PIECE 3. `exit.invalidation` is null on a candidate restored from a
      // scan session persisted before it: the stored flat percentage was
      // deleted rather than shown as a resolved stop. Before piece 3 the scan
      // always sent a number and this branch was effectively unreachable — the
      // migration is what makes it live, and an order must not go out against
      // a stop the model never chose.
      const card = makeCard({ exit: { invalidation: null, premiumStop: 1.5, timeStopDays: 10, target: 0, targets: [] } });
      const result = checkTradeRisk(card, 1, DEFAULT_LIMITS, [], 0);
      expect(result.approved).toBe(false);
      expect(result.reasons).toContain('missing_invalidation');
    });

    it('accepts a stripped card once the user has typed a stop into it', () => {
      // Typing a stop is the ONE gesture that makes a restored card orderable
      // without a re-scan, so the check has to judge the level the card is
      // actually showing — step 7 resolves that through `invalidationFor` and
      // the dialog passes it in. Reading `card.exit.invalidation` alone would
      // refuse the card forever.
      const card = makeCard({ exit: { invalidation: null, premiumStop: 1.5, timeStopDays: 10, target: 0, targets: [] } });
      const result = checkTradeRisk(card, 1, DEFAULT_LIMITS, [], 0, null, 172.5);
      expect(result.reasons).not.toContain('missing_invalidation');
    });

    it('still refuses when the resolved stop is itself unusable', () => {
      // A typed 0 is not an escape hatch. Same bar as the card's own value.
      const card = makeCard();
      expect(
        checkTradeRisk(card, 1, DEFAULT_LIMITS, [], 0, null, 0).reasons,
      ).toContain('missing_invalidation');
      expect(
        checkTradeRisk(card, 1, DEFAULT_LIMITS, [], 0, null, null).reasons,
      ).not.toContain('missing_invalidation');   // null = "no override", falls back to the card
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
      const result = checkTradeRisk(card, 1, DEFAULT_LIMITS, [], 0, null, undefined, pick());
      expect(result.approved).toBe(true);
      expect(result.reasons).not.toContain('max_loss_per_trade_exceeded');
    });

    it('Feature 5 — a pre-trade max-loss override resolves through resolveMaxLossLimitDollar, not a reimplementation', () => {
      // Same card as the "rejects" case above: lossAtStop = $2,000, global
      // default limit = $1,875 (rejected without an override). A $2,500
      // dollar override raises the limit above the loss, flipping approval.
      const card = makeCard({ exit: { ...makeCard().exit, exitPlan: makeExitPlan({ contractPrice: 0.5 }) } });
      const result = checkTradeRisk(card, 10, DEFAULT_LIMITS, [], 0, { mode: 'dollar', value: 2500 }, undefined, pick());
      // The $2,500 premium (5% of 50k) now also trips the premium cap, the
      // smaller of the 5% single cap and the 3.75% loss limit (review fix #4,
      // D5), so `approved` is false. The override still flips the STOP check.
      expect(result.reasons).toEqual(['single_trade_exposure_too_high']);
      expect(result.reasons).not.toContain('max_loss_per_trade_exceeded');
      expect(result.maxLossAtStop).toBe(2000);
      expect(result.maxLossLimitDollar).toBe(2500);
    });

    it('Feature 5 — a percent-mode override is resolved against portfolioValue, same as the global default', () => {
      const card = makeCard({ exit: { ...makeCard().exit, exitPlan: makeExitPlan({ contractPrice: 0.5 }) } });
      // 10% of the 50,000 portfolioValue = $5,000 — well above the $2,000 loss.
      const result = checkTradeRisk(card, 10, DEFAULT_LIMITS, [], 0, { mode: 'percent', value: 0.10 }, undefined, pick());
      // Premium cap (D5) also trips on this $2,500 / 5% card; only the stop check is under test.
      expect(result.reasons).toEqual(['single_trade_exposure_too_high']);
      expect(result.maxLossLimitDollar).toBe(5000);
    });

    it('Phase G piece 5, build step 4 (spec test 8) — pushes missing_method_pick and sets approved false when no pick is passed', () => {
      const result = checkTradeRisk(makeCard(), 1, DEFAULT_LIMITS, [], 0);
      expect(result.approved).toBe(false);
      expect(result.reasons).toContain('missing_method_pick');
    });

    it('does not push missing_method_pick once a pick is supplied', () => {
      const result = checkTradeRisk(makeCard(), 1, DEFAULT_LIMITS, [], 0, null, undefined, pick());
      expect(result.reasons).not.toContain('missing_method_pick');
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

/* ── Stop-vs-premium gate (B2) ─────────────────────────────────────────────
 *
 * `stopPremiumRisk` is a PRESENTER now. It renders the block the endpoint that
 * produced the stop already priced with Black-Scholes at today's date; it does
 * no arithmetic of its own. The delta-linear estimator these tests used to
 * exercise — `|stop − spot| × |delta|`, capped at the premium — is deleted, so
 * the cases that pinned its rounding, its cap and its threshold handling are
 * gone with it rather than rewritten against a function that no longer does
 * any of those things. What survives is what still has meaning: that the
 * printed figures agree with each other and with the verdict.
 *
 * Spec: docs/superpowers/plans/2026-09-02-gate-basis-spec.md §3, tests 1-2.
 */

/** The spec's own worked example (§3): the CVX contract that produced this
 *  gate, priced at its swing-low stop. Server-shaped — every figure per share
 *  and quantized to cents, as `compute_stop_cost` emits them. */
function block(over: Partial<StopCostOut> = {}): StopCostOut {
  return {
    premium:         5.20,
    valueAtStop:     1.49,
    lossDollar:      3.71,
    stopPrice:       185.87,
    fraction:        0.71,      // round(3.71 / 5.20, 2)
    status:          'CAUTION', // 0.71 >= the Swing line of 0.70
    passMaxFraction: 0.70,
    basis:           'bs_today',
    ...over,
  };
}

describe('stopPremiumRisk — the presenter (spec test 1)', () => {
  it('renders a StopCostOut unchanged', () => {
    const r = stopPremiumRisk(block())!;
    expect(r.premium).toBe(5.20);
    expect(r.valueAtStop).toBe(1.49);
    expect(r.loss).toBe(3.71);
    expect(r.stopPrice).toBe(185.87);
    expect(r.fraction).toBe(0.71);
    expect(r.passMaxFraction).toBe(0.70);
    expect(r.status).toBe('CAUTION');
    expect(r.basis).toBe('bs_today');
  });

  it('null in → null out', () => {
    expect(stopPremiumRisk(null)).toBeNull();
  });

  it('takes ONE argument — the delta-linear signature is gone', () => {
    // The old call was (stopPrice, stockPrice, delta, premium, thresholds).
    // Pinned by arity because a five-argument version reappearing is precisely
    // how the frontend would start answering a different question than the
    // gate it prints a verdict for.
    expect(stopPremiumRisk).toHaveLength(1);
  });

  it('does NOT re-grade the verdict — the server decided it', () => {
    // A block whose status disagrees with a naive fraction-vs-threshold read.
    // The server cannot emit this, and that is the point: if the presenter
    // ever recomputes, two rulers are back on one screen. The whole reason the
    // gate moved server-side is that the client cannot price the contract, so
    // it must not be able to overrule the price either.
    const r = stopPremiumRisk(block({ fraction: 0.85, status: 'PASS' }))!;
    expect(r.status).toBe('PASS');
    expect(formatStopLossBadge(r)).toContain('PASS');
  });

  it('is "not computed" where the arithmetic has no honest answer', () => {
    // Same rule as compute_stop_cost's, repeated at the one place a block can
    // arrive from somewhere other than a live endpoint: a persisted ExitPlan
    // restored from a blob written before B2.
    expect(stopPremiumRisk(block({ premium: 0.009, lossDollar: 0.009, valueAtStop: 0 }))).toBeNull();
    expect(stopPremiumRisk(block({ premium: NaN }))).toBeNull();
    expect(stopPremiumRisk(block({ valueAtStop: Infinity }))).toBeNull();
    expect(stopPremiumRisk(block({ stopPrice: NaN }))).toBeNull();
    // A premium of exactly one cent still has a printable card.
    expect(stopPremiumRisk(block({ premium: 0.01, valueAtStop: 0.00, lossDollar: 0.01 }))).not.toBeNull();
  });
});

describe('formatStopPremiumRisk (spec test 2)', () => {
  it("prints the spec's worked line", () => {
    expect(formatStopPremiumRisk(stopPremiumRisk(block())!))
      .toBe('$5.20 premium − $1.49 at $185.87 = $3.71 of $5.20 premium · Black-Scholes, priced today');
  });

  it('names the basis, so it cannot be read against the barrier race', () => {
    // The race reprices AT THE HORIZON (theta included) and drives sizing;
    // this prices at today's remaining life and drives only the verdict. The
    // two legitimately disagree about "what is this worth at the stop", and
    // the suffix is what stops that reading as a contradiction.
    expect(formatStopPremiumRisk(stopPremiumRisk(block())!)).toContain('Black-Scholes, priced today');
    expect(formatStopPremiumRisk(stopPremiumRisk(block())!)).not.toContain('delta-linear');
  });

  it('carries no cap disclosure — Black-Scholes cannot exceed the premium', () => {
    const total = block({ valueAtStop: 0.00, lossDollar: 5.20, fraction: 1.00 });
    expect(formatStopPremiumRisk(stopPremiumRisk(total)!)).not.toMatch(/uncapped/);
  });
});

describe('the printed figures agree with each other and with the verdict', () => {
  it('the equation subtracts exactly as printed', () => {
    const r = stopPremiumRisk(block())!;
    const line = formatStopPremiumRisk(r);
    const [, premium, value, loss] = line.match(
      /\$([\d.]+) premium − \$([\d.]+) at \$[\d.]+ = \$([\d.]+)/,
    )!;
    expect(Number(premium) - Number(value)).toBeCloseTo(Number(loss), 10);
  });

  it('"left" on the badge IS the value at the stop', () => {
    // premium − loss === valueAtStop by construction, so the badge's
    // dollars-left and the arithmetic line's middle term are one quantity
    // printed twice. If they ever diverge, one of them was rounded twice.
    for (const b of [block(), block({ premium: 18.90, valueAtStop: 8.24, lossDollar: 10.66, fraction: 0.56, status: 'PASS' })]) {
      const r = stopPremiumRisk(b)!;
      expect(formatStopLossBadge(r)).toContain(`$${b.valueAtStop.toFixed(2)}/share left`);
    }
  });

  it('the headline is the per-share pair × 100, and its three figures add up', () => {
    const r = stopPremiumRisk(block())!;
    expect(formatStopLossHeadline(r)).toBe('$371 per contract — of the $520 premium, $149 left');
    expect(371 + 149).toBe(520);
  });

  it('the badge percentage is the number the verdict was decided on', () => {
    const r = stopPremiumRisk(block())!;
    expect(formatStopLossPct(r)).toBe('71%');
    expect(formatStopLossBadge(r)).toBe('CAUTION · 71% of premium · $1.49/share left');
  });

  it('100% is reserved for an actual total loss on the printed cents', () => {
    // `fraction` is rounded to hundredths server-side, so a contract with one
    // cent of a $5.20 premium left arrives as 1.00. Printing "100% of premium"
    // beside "$0.01/share left" asserts something the money contradicts.
    const nearlyTotal = block({ valueAtStop: 0.01, lossDollar: 5.19, fraction: 1.00 });
    const r = stopPremiumRisk(nearlyTotal)!;
    expect(formatStopLossPct(r)).toBe('99%');
    expect(stopLossIsTotalOnPrintedFigures(r)).toBe(false);

    const total = stopPremiumRisk(block({ valueAtStop: 0.00, lossDollar: 5.20, fraction: 1.00 }))!;
    expect(formatStopLossPct(total)).toBe('100%');
    expect(stopLossIsTotalOnPrintedFigures(total)).toBe(true);
    expect(formatStopLossBadge(total)).toContain('$0.00/share left');
  });

  it('0% is NOT reserved the same way, deliberately', () => {
    // "0% of premium" beside "$9.99/share left" asserts nothing false — it is a
    // percentage rounded to a whole point, like every other figure on the
    // badge. Forcing it up to 1% would break the stronger property that the
    // printed percentage is within half a point of the true fraction.
    const r = stopPremiumRisk(block({ premium: 10.00, valueAtStop: 9.99, lossDollar: 0.01, fraction: 0.00, status: 'PASS' }))!;
    expect(formatStopLossPct(r)).toBe('0%');
    expect(formatStopLossBadge(r)).toContain('$9.99/share left');
  });

  it('sweep: badge, headline and percentage never contradict each other', () => {
    let checked = 0;
    for (let premiumCents = 1; premiumCents <= 4000; premiumCents += 7) {
      for (let lossCents = 0; lossCents <= premiumCents; lossCents += Math.max(1, Math.floor(premiumCents / 9))) {
        const premium = premiumCents / 100;
        const loss = lossCents / 100;
        const r = stopPremiumRisk(block({
          premium,
          lossDollar:  loss,
          valueAtStop: Math.round((premiumCents - lossCents)) / 100,
          fraction:    Math.round((lossCents / premiumCents) * 100) / 100,
          status:      'CAUTION',
        }));
        if (r == null) continue;
        checked++;
        const pct = Number(formatStopLossPct(r).replace('%', ''));
        const isTotal = stopLossIsTotalOnPrintedFigures(r);
        // 100% if and only if nothing is left.
        expect(pct === 100).toBe(isTotal);
        // The dollars-left on the badge and in the headline are one number.
        const left = premiumCents - lossCents;
        expect(formatStopLossBadge(r)).toContain(`$${(left / 100).toFixed(2)}/share left`);
        expect(formatStopLossHeadline(r)).toContain(`$${left.toLocaleString('en-US')} left`);
        // The percentage never claims more loss than the money shows.
        if (left > 0) expect(pct).toBeLessThanOrEqual(99);
      }
    }
    expect(checked).toBeGreaterThan(2000);
  });
});

// NO-LIVE-QUOTE NLQ-1 (round-1 F2): a position GET /api/portfolio got no quote
// for carries a 0 currentPrice that is not a price. Exposure values it at its
// entry (cost basis) through `exposureMark`, never 0, so the pre-trade check
// cannot approve an order past the total-exposure cap on a $0 mark.
describe('exposure of a position without a quote', () => {
  // 6.20 x 100 x 20 = $12,400 at entry; with the card's $250 that is 25.3% of
  // $50k, past the 25% cap. Valued at $0 it would be 0.5% and approved.
  const flagged = () => makePosition({ entryPrice: 6.2, currentPrice: 0, contracts: 20,
                                       pnlDollar: 0, pnlPct: 0, quoteUnavailable: true });

  it('checkTradeRisk blocks when the flagged row at entry pushes total exposure over the cap', () => {
    const result = checkTradeRisk(makeCard(), 1, DEFAULT_LIMITS, [flagged()], 0, null, undefined, pick());
    expect(result.totalExposurePct).toBeCloseTo((12400 + 250) / 50000, 10);
    expect(result.reasons).toContain('total_exposure_limit_reached');
    expect(result.approved).toBe(false);
  });

  it('values a flagged row at entry even when it still carries a stale non-zero mark', () => {
    const row = makePosition({ entryPrice: 6.2, currentPrice: 1, contracts: 20, quoteUnavailable: true });
    expect(totalNotional([row])).toBeCloseTo(12400, 10);
  });

  it('values a row whose currentPrice is not a finite number > 0 at entry', () => {
    for (const bad of [0, -1, NaN, Infinity]) {
      expect(totalNotional([makePosition({ entryPrice: 6.2, currentPrice: bad, contracts: 20 })])).toBeCloseTo(12400, 10);
    }
  });

  it('a quoted row is still valued at its live mark', () => {
    expect(totalNotional([makePosition({ entryPrice: 6.2, currentPrice: 5, contracts: 20 })])).toBe(10000);
  });

  it('computePortfolioRiskMetrics counts the flagged row at entry too', () => {
    const metrics = computePortfolioRiskMetrics([flagged()], DEFAULT_LIMITS, 0);
    expect(metrics.totalExposurePct).toBeCloseTo(12400 / 50000, 10);
    expect(metrics.largestConcentrationPct).toBeCloseTo(12400 / 50000, 10);
  });
});
