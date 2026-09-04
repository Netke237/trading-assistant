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
  stopPremiumRisk,
  formatStopPremiumRisk,
  formatStopLossHeadline,
  formatStopLossPct,
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

    it('Feature 5 — a pre-trade max-loss override resolves through resolveMaxLossLimitDollar, not a reimplementation', () => {
      // Same card as the "rejects" case above: lossAtStop = $2,000, global
      // default limit = $1,875 (rejected without an override). A $2,500
      // dollar override raises the limit above the loss, flipping approval.
      const card = makeCard({ exit: { ...makeCard().exit, exitPlan: makeExitPlan({ contractPrice: 0.5 }) } });
      const result = checkTradeRisk(card, 10, DEFAULT_LIMITS, [], 0, { mode: 'dollar', value: 2500 });
      expect(result.approved).toBe(true);
      expect(result.reasons).not.toContain('max_loss_per_trade_exceeded');
      expect(result.maxLossAtStop).toBe(2000);
      expect(result.maxLossLimitDollar).toBe(2500);
    });

    it('Feature 5 — a percent-mode override is resolved against portfolioValue, same as the global default', () => {
      const card = makeCard({ exit: { ...makeCard().exit, exitPlan: makeExitPlan({ contractPrice: 0.5 }) } });
      // 10% of the 50,000 portfolioValue = $5,000 — well above the $2,000 loss.
      const result = checkTradeRisk(card, 10, DEFAULT_LIMITS, [], 0, { mode: 'percent', value: 0.10 });
      expect(result.approved).toBe(true);
      expect(result.maxLossLimitDollar).toBe(5000);
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

describe('stopPremiumRisk', () => {
  // The CVX contract that produced this gate: stock $201.86, swing-low stop
  // $185.87, delta 0.30, premium $5.20. Uncapped loss 15.99 * 0.30 = $4.797,
  // which is 92% of the premium -- the stop works, but only just.
  it('reports the real fraction of premium a stop costs, with every input', () => {
    const r = stopPremiumRisk(185.87, 201.86, 0.30, 5.20)!;
    expect(r.stockMove).toBeCloseTo(15.99, 2);
    expect(r.delta).toBe(0.30);
    expect(r.rawLoss).toBeCloseTo(4.797, 3);
    expect(r.loss).toBeCloseTo(4.797, 3);
    expect(r.fraction).toBeCloseTo(0.9225, 4);
    expect(r.capped).toBe(false);
    expect(r.status).toBe('CAUTION');
  });

  it('flags CAUTION (never REJECT) when the stop is at or beyond a total loss', () => {
    // Same stop, same premium, but a higher-delta contract: 15.99 * 0.60 =
    // $9.59 against a $5.20 premium. You cannot lose $9.59 on a $5.20 option,
    // so the loss caps -- and the cap is the whole point: the stop sits past
    // the point where there is anything left to protect.
    const r = stopPremiumRisk(185.87, 201.86, 0.60, 5.20)!;
    expect(r.rawLoss).toBeCloseTo(9.594, 3);
    expect(r.loss).toBe(5.20);        // capped at premium
    expect(r.fraction).toBe(1);
    expect(r.capped).toBe(true);
    // Two states by design: a total-loss stop is the same verdict as an 85%
    // one. `capped` and the percentage carry the magnitude the badge doesn't.
    expect(r.status).toBe('CAUTION');
  });

  it('PASSes when the contract keeps meaningful value at the stop', () => {
    // A tight stop $2 away on the same delta: 2 * 0.30 = $0.60 of $5.20 = 12%.
    const r = stopPremiumRisk(199.86, 201.86, 0.30, 5.20)!;
    expect(r.fraction).toBeCloseTo(0.1154, 4);
    expect(r.status).toBe('PASS');
  });

  it('is contract-specific -- the same stop and stock price give different verdicts per contract', () => {
    // This is the property the two rejected R:R designs did NOT have: their
    // reward and risk were both proportional to premium, so premium cancelled
    // and every contract scored identically. Here it genuinely discriminates.
    const cheapOtm = stopPremiumRisk(185.87, 201.86, 0.30, 5.20)!;
    const richerItm = stopPremiumRisk(185.87, 201.86, 0.30, 20.00)!;
    expect(cheapOtm.fraction).not.toBeCloseTo(richerItm.fraction, 4);
    expect(cheapOtm.status).toBe('CAUTION');
    expect(richerItm.status).toBe('PASS');   // 4.797 / 20.00 = 24%
  });

  it('works bearish -- a stop above the current price is the same distance', () => {
    const bullish = stopPremiumRisk(185.87, 201.86, 0.30, 5.20)!;
    const bearish = stopPremiumRisk(217.85, 201.86, -0.30, 5.20)!;
    expect(bearish.stockMove).toBeCloseTo(bullish.stockMove, 2);
    expect(bearish.delta).toBe(0.30);        // |delta|
    expect(bearish.fraction).toBeCloseTo(bullish.fraction, 4);
  });

  it('floors a near-zero delta rather than reporting "no risk at the stop"', () => {
    const r = stopPremiumRisk(185.87, 201.86, 0.001, 5.20)!;
    expect(r.delta).toBe(0.05);
    expect(r.rawLoss).toBeCloseTo(0.7995, 4);
  });

  it('lands CAUTION exactly at the 80% threshold, PASS just below', () => {
    // stockMove * delta / premium == 0.80 exactly: 8.0 * 0.50 / 5.00
    expect(stopPremiumRisk(92.0, 100.0, 0.50, 5.00)!.status).toBe('CAUTION');
    // A CLOSER stop (92.1, not 91.9) is the cheaper one -- less distance to the
    // stop means less loss: 7.9 * 0.50 / 5.00 = 0.79.
    expect(stopPremiumRisk(92.1, 100.0, 0.50, 5.00)!.status).toBe('PASS');
  });

  it('never emits REJECT — the gate sorts candidates, it does not refuse them', () => {
    // Sweep from a trivial stop to one at twice the premium: only ever PASS or
    // CAUTION. REJECT is the red badge in this design system and a red badge on
    // a tradeable contract reads as a refusal.
    for (const stop of [99.9, 95, 92.1, 92.0, 90.1, 90.0, 80, 50]) {
      expect(stopPremiumRisk(stop, 100.0, 0.50, 5.00)!.status).not.toBe('REJECT');
    }
    expect(stopPremiumRisk(90.0, 100.0, 0.50, 5.00)!.capped).toBe(true);   // still detectable
  });

  it('returns null when there is no meaningful answer', () => {
    expect(stopPremiumRisk(185.87, 185.87, 0.30, 5.20)).toBeNull();  // stop == price
    expect(stopPremiumRisk(185.87, 201.86, 0.30, 0)).toBeNull();     // no premium
    expect(stopPremiumRisk(185.87, 201.86, 0.30, -1)).toBeNull();
    expect(stopPremiumRisk(NaN, 201.86, 0.30, 5.20)).toBeNull();
    expect(stopPremiumRisk(185.87, Infinity, 0.30, 5.20)).toBeNull();
    expect(stopPremiumRisk(185.87, 201.86, NaN, 5.20)).toBeNull();
  });
});

describe('the printed equation reconciles', () => {
  // The bug this replaced: delta printed at 2dp while the loss was computed
  // from full precision, so `$15.41 × Δ0.54 = $8.24` -- 15.41 × 0.54 is 8.32.
  // Kenneth checked it by hand and got a different answer than the card, on a
  // card whose entire premise is showing arithmetic you can verify.
  it('multiplies out to the printed loss at the printed precision', () => {
    const r = stopPremiumRisk(312.80, 328.21, 0.5347, 18.90, { pass_max_fraction: 0.80 })!;
    const printed = formatStopPremiumRisk(r);
    const m = printed.match(/\$([\d.]+) away × Δ([\d.]+) = \$([\d.]+)/)!;
    const [away, delta, loss] = [Number(m[1]), Number(m[2]), Number(m[3])];
    // Rounded to the cent, the printed factors must produce the printed answer.
    expect(Math.abs(away * delta - loss)).toBeLessThan(0.005);
  });

  it('multiplies out ACROSS A RANGE, not just on the one triple that was hand-picked', () => {
    // The test above passed on a single input the whole time the equation was
    // still wrong for about 6% of inputs -- 15.41 × 0.5347 happens to land
    // inside tolerance. Three factors are rounded independently (move to
    // cents, delta to 3dp, loss to cents), so no amount of delta precision
    // could close it; the printed product is now computed FROM the printed
    // factors. Only the uncapped rows are checked: when the cap binds, the
    // equation prints the premium and the "(uncapped $…)" tail carries the
    // product, which is the one place the two legitimately differ.
    const failures: string[] = [];
    for (let move = 0.13; move <= 42; move += 0.07) {
      for (const delta of [0.05, 0.2508, 0.3333, 0.4567, 0.5, 0.5347, 0.789, 0.9999]) {
        for (const premium of [0.35, 2.0, 6.51, 18.9]) {
          const r = stopPremiumRisk(200 - move, 200, delta, premium);
          if (!r) continue;
          const printed = formatStopPremiumRisk(r);
          const m = printed.match(/\$([\d.]+) away × Δ([\d.]+) = \$([\d.]+) of \$([\d.]+)/)!;
          const [away, d, loss, premiumShown] = [Number(m[1]), Number(m[2]), Number(m[3]), Number(m[4])];
          // EXACT, not an epsilon: the printed loss must be the printed factors
          // multiplied and rounded to the cent, which is what a hand-check
          // produces. An epsilon of half a cent passes 0.13 × 0.500 = 0.065
          // against a printed $0.07 either way and would hide a real drift.
          const product = Number((away * d).toFixed(2));
          const expected = Math.min(product, premiumShown);
          if (loss !== expected) failures.push(`${printed} (expected $${expected})`);
          // CAPPED ROWS ARE CHECKED TOO. This used to `continue` past them, and
          // that skip hid a whole class: `r.capped` is decided at full
          // precision while the line is printed at 3dp on the delta, so the two
          // disagreed in both directions -- an "(uncapped)" figure BELOW the
          // capped one, and a clamp with no tail at all. The clamp is no longer
          // "the one legitimate exception"; the tail is what the reader is owed
          // whenever the product and the printed loss differ, and it is
          // present exactly then.
          const tail = printed.match(/\(uncapped \$([\d.]+)\)/);
          if (product > premiumShown) {
            if (!tail) failures.push(`clamped with no tail: ${printed}`);
            else if (Number(tail[1]) !== product) {
              failures.push(`tail is not the printed product: ${printed}`);
            }
          } else if (tail) {
            failures.push(`tail on a row that multiplies out: ${printed}`);
          }
        }
      }
    }
    expect(failures).toEqual([]);
  });

  it('never prints an "uncapped" figure below the capped one', () => {
    // $70.10 away × Δ0.5505 on a $38.59 premium read
    // "= $38.59 of $38.59 premium (uncapped $38.55)". `loss` is
    // min(rawLoss, premium) by construction, so an uncapped estimate BELOW it
    // cannot happen -- unless the two figures come from two precisions, which
    // is what `r.capped` (full) against `product` (printed) was doing.
    const r = stopPremiumRisk(100.00, 170.10, 0.5505, 38.59)!;
    expect(r.capped).toBe(true);              // still true at full precision
    expect(formatStopPremiumRisk(r)).toBe(
      '$70.10 away × Δ0.550 = $38.55 of $38.59 premium · delta-linear, priced today',
    );
  });

  it('carries the tail when the printed product clears the premium', () => {
    // The mirror image: `r.capped` is FALSE (rawLoss 52.47999 < 52.48) but the
    // printed factors give $52.52. It printed "= $52.48 of $52.48 premium" with
    // nothing to explain the 4c, above a headline claiming "$0 left" for a stop
    // the code itself did not classify as a total loss.
    const r = stopPremiumRisk(100.00, 170.02, 0.7495, 52.48)!;
    expect(r.capped).toBe(false);
    expect(formatStopPremiumRisk(r)).toBe(
      '$70.02 away × Δ0.750 = $52.48 of $52.48 premium (uncapped $52.52) · delta-linear, priced today',
    );
  });

  it('the badge percentage never contradicts the money beside it', () => {
    // The badge read `(r.fraction * 100).toFixed(0)` -- full precision -- while
    // the headline scaled from the printed pair, so the two disagreed by a
    // point on ~1.4% of inputs and flatly contradicted each other at the top of
    // the range: "100% OF PREMIUM" printed beside "$8 left".
    const r = stopPremiumRisk(164.76, 200, 0.5342, 18.90)!;
    expect(formatStopLossHeadline(r)).toBe(
      '$1,882 per contract — of the $1,890 premium, $8 left',
    );
    expect(formatStopLossPct(r)).toBe('99%');

    const failures: string[] = [];
    for (let move = 0.11; move <= 42; move += 0.03) {
      for (const delta of [0.05, 0.2508, 0.5, 0.5342, 0.5347, 0.789, 0.9999]) {
        for (const premium of [0.35, 2.0, 6.51, 18.9]) {
          const x = stopPremiumRisk(200 - move, 200, delta, premium);
          if (!x) continue;
          const head = formatStopLossHeadline(x);
          const h = head.match(/\$([\d,]+) per contract — of the \$([\d,]+) premium, \$(-?[\d,]+) left/)!;
          const num = (v: string) => Number(v.replace(/,/g, ''));
          const [perContract, premiumTotal, left] = [num(h[1]), num(h[2]), num(h[3])];
          const badge = formatStopLossPct(x);
          // 100% is reserved for an actual total loss on the printed figures.
          if (badge === '100%' && left !== 0) failures.push(`${badge} beside ${head}`);
          if (left === 0 && perContract > 0 && badge !== '100%') {
            failures.push(`${badge} beside a total loss: ${head}`);
          }
          // And it stays within a point of the ratio the reader can compute.
          const implied = Math.round((perContract / premiumTotal) * 100);
          if (Math.abs(Number(badge.replace('%', '')) - implied) > 1) {
            failures.push(`${badge} vs computed ${implied}%: ${head}`);
          }
        }
      }
    }
    expect(failures).toEqual([]);
  });

  it('the headline sums, and agrees with the per-share line beneath it', () => {
    // $8.01 away × Δ0.500 on a $6.51 premium printed "$401 per contract — of
    // the $651 premium, $251 left" (401 + 251 = 652) two lines above
    // "= $4.00", whose hundred is $400. Three figures rounded independently
    // from full precision; they are now all scaled from one rounded pair.
    const failures: string[] = [];
    for (let move = 0.11; move <= 42; move += 0.07) {
      for (const delta of [0.05, 0.2508, 0.5, 0.5347, 0.789, 0.9999]) {
        for (const premium of [0.35, 2.0, 6.51, 18.9]) {
          const r = stopPremiumRisk(200 - move, 200, delta, premium);
          if (!r) continue;
          const head = formatStopLossHeadline(r);
          const h = head.match(/\$([\d,]+) per contract — of the \$([\d,]+) premium, \$(-?[\d,]+) left/)!;
          const num = (x: string) => Number(x.replace(/,/g, ''));
          const [perContract, premiumTotal, left] = [num(h[1]), num(h[2]), num(h[3])];
          if (perContract + left !== premiumTotal) failures.push(`sum: ${head}`);
          const line = formatStopPremiumRisk(r);
          const lossPerShare = Number(line.match(/= \$([\d.]+) of/)![1]);
          if (Math.abs(lossPerShare * 100 - perContract) > 0.5) {
            failures.push(`headline vs line: ${head} || ${line}`);
          }
        }
      }
    }
    expect(failures).toEqual([]);
  });

  it('the audit case itself: $8.01 away, Δ0.500, $6.51 premium', () => {
    const r = stopPremiumRisk(191.99, 200, 0.5, 6.51)!;
    expect(formatStopLossHeadline(r)).toBe('$400 per contract — of the $651 premium, $251 left');
    expect(formatStopPremiumRisk(r)).toContain('$8.01 away × Δ0.500 = $4.00 of $6.51 premium');
  });

  it('names its basis, so it cannot be confused with the Barrier Race figure', () => {
    // Two cards print a stop loss for the same stop and they legitimately
    // differ -- this one is priced today, the race's at the median day to the
    // barrier. Unlabelled they read as a contradiction.
    const r = stopPremiumRisk(312.80, 328.21, 0.5347, 18.90, { pass_max_fraction: 0.80 })!;
    expect(formatStopPremiumRisk(r)).toContain('delta-linear, priced today');
  });
});

describe('formatStopLossHeadline', () => {
  it('gives per-contract dollars and what is left', () => {
    const r = stopPremiumRisk(312.80, 328.21, 0.5347, 18.90, { pass_max_fraction: 0.80 })!;
    // 8.24/share -> $824 of the $1,890 paid, $1,066 left.
    expect(formatStopLossHeadline(r)).toBe(
      '$824 per contract — of the $1,890 premium, $1,066 left',
    );
  });

  it('reads $0 left when the stop costs the whole premium', () => {
    const capped = stopPremiumRisk(100, 200, 0.9, 5.00, { pass_max_fraction: 0.80 })!;
    expect(capped.capped).toBe(true);
    expect(formatStopLossHeadline(capped)).toContain('$0 left');
  });
});

describe('formatStopPremiumRisk', () => {
  it('puts every input on one line so the verdict is auditable', () => {
    const r = stopPremiumRisk(185.87, 201.86, 0.30, 5.20)!;
    expect(formatStopPremiumRisk(r)).toBe(
      '$15.99 away × Δ0.300 = $4.80 of $5.20 premium · delta-linear, priced today',
    );
  });

  it('appends the uncapped loss only when the cap actually bound', () => {
    const capped = stopPremiumRisk(185.87, 201.86, 0.60, 5.20)!;
    // Without the tail, `loss` is pinned to `premium` and the reader cannot see
    // HOW far past a total loss the stop sits -- $9.59 on a $5.20 contract.
    expect(formatStopPremiumRisk(capped)).toBe(
      '$15.99 away × Δ0.600 = $5.20 of $5.20 premium (uncapped $9.59)'
      + ' · delta-linear, priced today',
    );

    const uncapped = stopPremiumRisk(199.86, 201.86, 0.30, 5.20)!;
    expect(formatStopPremiumRisk(uncapped)).not.toMatch(/uncapped/);
  });
});

describe('stopPremiumRisk — configurable thresholds', () => {
  // The gate's bands are per-horizon in scoring_rules.yaml and overridable per
  // run from Step 3, so the helper must take them rather than own them.
  it('uses the caller-supplied threshold instead of the module default', () => {
    // 70% loss: CAUTION under the Position band (0.70), PASS under Swing (0.80).
    const args = [93.0, 100.0, 0.50, 5.00] as const;   // 7.0 * 0.50 / 5.00 = 0.70
    expect(stopPremiumRisk(...args, { pass_max_fraction: 0.70 })!.status).toBe('CAUTION');
    expect(stopPremiumRisk(...args, { pass_max_fraction: 0.80 })!.status).toBe('PASS');
  });

  it('honours a tightened pass line', () => {
    // 50% loss passes at the 0.80 default, fails once the line drops to 0.40.
    const args = [95.0, 100.0, 0.50, 5.00] as const;   // 5.0 * 0.50 / 5.00 = 0.50
    expect(stopPremiumRisk(...args, { pass_max_fraction: 0.80 })!.status).toBe('PASS');
    expect(stopPremiumRisk(...args, { pass_max_fraction: 0.40 })!.status).toBe('CAUTION');
  });

  it('falls back to the default when the threshold is out of range or non-finite', () => {
    // The per-run override in Step 3 is user-editable, so these are reachable
    // inputs. Above 1.0 is meaningless -- the loss caps at the premium, so
    // nothing could exceed it and CAUTION would be unreachable.
    const at70 = [93.0, 100.0, 0.50, 5.00] as const;   // 70% loss
    const at85 = [91.5, 100.0, 0.50, 5.00] as const;   // 85% loss
    for (const bad of [{ pass_max_fraction: 1.5 }, { pass_max_fraction: 0 },
                       { pass_max_fraction: -0.5 }, { pass_max_fraction: NaN }]) {
      expect(stopPremiumRisk(...at70, bad)!.status).toBe('PASS');      // 0.80 default
      expect(stopPremiumRisk(...at85, bad)!.status).toBe('CAUTION');
    }
    // ...and omitting it entirely still gates, at the Swing default.
    expect(stopPremiumRisk(...at70)!.status).toBe('PASS');
    expect(stopPremiumRisk(...at85)!.status).toBe('CAUTION');
  });
});
