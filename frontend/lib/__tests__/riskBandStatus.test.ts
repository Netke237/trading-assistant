/**
 * RISK-TOOLTIP-SHARED-COMPARATORS: the RiskPanel badge (riskStore.computeMetrics) and
 * its tooltip (statusTooltips.riskStatusTooltip) share lib/status.ts's riskBandStatus.
 * Both consumers are swept against an oracle written in INTEGER arithmetic, over caps
 * 1..30 — at the default caps (10, 5) floor(c*0.8) and floor(c*0.75) coincide, which is
 * how a wrong factor once shipped green against sampled pins.
 */
import { act } from '@testing-library/react';
import { riskBandStatus, type Status } from '@/lib/status';
import { useRiskStore } from '@/lib/riskStore';
import { riskStatusTooltip } from '@/lib/statusTooltips';
import type { PortfolioPosition, PortfolioRiskMetrics, RiskLimits } from '@/types/domain';

// REJECT iff v >= c; CAUTION iff v >= floor(4c/5); no floating point anywhere.
function countOracle(v: number, c: number): Status {
  if (v >= c) return 'REJECT';
  const floor80 = (4 * c - ((4 * c) % 5)) / 5;
  return v >= floor80 ? 'CAUTION' : 'PASS';
}

const CASES: Array<[number, number]> = [];
for (let c = 1; c <= 30; c++) for (let v = 0; v <= c + 2; v++) CASES.push([c, v]);

// Every band other than the one under test is held at PASS by a huge cap.
const WIDE: RiskLimits = {
  maxTotalExposurePct: 1000, maxConcurrentPositions: 1000, maxSingleTradeExposurePct: 1000,
  maxDailyRecommendations: 1000, portfolioValue: 100_000, maxLossPerTradePct: 0.0375,
  maxSingleStockPositionPct: 1000, maxTotalStockExposurePct: 1000,
};

function stockPosition(i: number, currentPrice: number): PortfolioPosition {
  return {
    symbol: `S${i}`, contract: `S${i}|STOCK`, direction: 'Bullish', entryDate: '2026-09-01',
    expiry: '', dteRemaining: 0, dteTotal: 0, entryPrice: currentPrice, currentPrice,
    pnlDollar: 0, pnlPct: 0, stop: null, targets: [], status: 'PASS', contracts: 1, recId: `R${i}`,
  } as PortfolioPosition;
}

function badge(limits: RiskLimits, positions: PortfolioPosition[], daily = 0): PortfolioRiskMetrics {
  act(() => {
    useRiskStore.setState({ limits, dailyRecommendations: daily });
    useRiskStore.getState().computeMetrics(positions);
  });
  return useRiskStore.getState().metrics;
}

/** One OPTION row worth `notional` (price x 100 x 1 contract). STOCK-SENDS:
 *  the option bands count option rows only. */
function optionPosition(i: number, notional: number): PortfolioPosition {
  return { ...stockPosition(i, notional / 100), contract: `O${i}|100|2026-12-18|C` } as PortfolioPosition;
}

const zeroed = (n: number) => Array.from({ length: n }, (_, i) => stockPosition(i, 0));

describe('riskBandStatus — count bands, caps 1..30 against an integer oracle', () => {
  it.each(CASES)('cap %i, value %i: riskBandStatus', (c, v) => {
    expect(riskBandStatus('count', v, c)).toBe(countOracle(v, c));
  });

  it.each(CASES)('cap %i, %i positions: badge and tooltip agree with the oracle', (c, v) => {
    const limits = { ...WIDE, maxConcurrentPositions: c };
    const metrics = badge(limits, zeroed(v));
    expect(metrics.concurrentPositions).toBe(v);
    expect(metrics.status).toBe(countOracle(v, c));
    expect(riskStatusTooltip(metrics, limits, 'positions')).toBe(`${v} of a ${c} limit (${countOracle(v, c)}).`);
  });

  it.each(CASES)('cap %i, %i daily recommendations: badge and tooltip agree with the oracle', (c, v) => {
    const limits = { ...WIDE, maxDailyRecommendations: c };
    const metrics = badge(limits, [], v);
    expect(metrics.dailyRecommendations).toBe(v);
    expect(metrics.status).toBe(countOracle(v, c));
    expect(riskStatusTooltip(metrics, limits, 'daily')).toBe(`${v} of a ${c} limit (${countOracle(v, c)}).`);
  });
});

describe('riskBandStatus — fraction bands at their boundaries', () => {
  // cap 0.5: exactly 80% (0.40) is PASS, above it CAUTION, the cap itself CAUTION, above REJECT.
  const POINTS: Array<[number, Status, string]> = [
    [0.40, 'PASS', '40%'], [0.41, 'CAUTION', '41%'], [0.50, 'CAUTION', '50%'], [0.51, 'REJECT', '51%'],
  ];

  it.each(POINTS)('riskBandStatus fraction %f -> %s', (v, s) => {
    expect(riskBandStatus('fraction', v, 0.5)).toBe(s);
  });

  it.each(POINTS)('total exposure %f: badge and tooltip -> %s', (v, s, pct) => {
    const limits = { ...WIDE, maxTotalExposurePct: 0.5 };
    const metrics = badge(limits, [optionPosition(0, v * 100_000)]);
    expect(metrics.status).toBe(s);
    expect(riskStatusTooltip(metrics, limits, 'exposure')).toBe(`${pct} of a 50% limit (${s}).`);
  });

  it.each(POINTS)('largest concentration %f: badge and tooltip -> %s', (v, s, pct) => {
    const limits = { ...WIDE, maxSingleTradeExposurePct: 0.5 };
    const metrics = badge(limits, [optionPosition(0, v * 100_000)]);
    expect(metrics.status).toBe(s);
    expect(riskStatusTooltip(metrics, limits, 'concentration')).toBe(`${pct} of a 50% limit (${s}).`);
  });

  // STOCK-SENDS: the two stock bands, each against its own stock cap.
  it.each(POINTS)('stock exposure %f: badge and tooltip -> %s', (v, s, pct) => {
    const limits = { ...WIDE, maxTotalStockExposurePct: 0.5 };
    const metrics = badge(limits, [stockPosition(0, v * 100_000)]);
    expect(metrics.status).toBe(s);
    expect(metrics.totalExposurePct).toBe(0);
    expect(riskStatusTooltip(metrics, limits, 'stockExposure')).toBe(`${pct} of a 50% limit (${s}).`);
  });

  it.each(POINTS)('largest stock %f: badge and tooltip -> %s', (v, s, pct) => {
    const limits = { ...WIDE, maxSingleStockPositionPct: 0.5 };
    const metrics = badge(limits, [stockPosition(0, v * 100_000)]);
    expect(metrics.status).toBe(s);
    expect(riskStatusTooltip(metrics, limits, 'stockConcentration')).toBe(`${pct} of a 50% limit (${s}).`);
  });
});

describe('riskBandStatus — small-cap behaviour kept as-is (a product call, not this refactor)', () => {
  it('cap 1: zero positions already reads CAUTION', () => {
    expect(riskBandStatus('count', 0, 1)).toBe('CAUTION');
  });
  it('cap 2: one position reads CAUTION', () => {
    expect(riskBandStatus('count', 1, 2)).toBe('CAUTION');
  });
  it('cap 0: every count is REJECT', () => {
    expect(riskBandStatus('count', 0, 0)).toBe('REJECT');
  });
});
