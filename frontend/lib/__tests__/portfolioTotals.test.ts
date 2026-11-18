import {
  aggregateGreeks,
  deltaDollarsNote,
  openTotals,
  positionThetaDollars,
} from '../portfolioTotals';
import type { PortfolioPosition } from '@/types/domain';
import { portfolio20261117 } from '../../test-utils/portfolioFixture20261117';

// PORTFOLIO-NUMBERS T1 (#657): the open-P&L percent is on cost basis, and the
// greeks are aggregated per position as greek x multiplier x contracts.

function makePosition(overrides: Partial<PortfolioPosition> = {}): PortfolioPosition {
  return {
    symbol: 'AAPL', contract: 'AAPL|185|2027-01-15|C', direction: 'Bullish',
    entryDate: '2026-08-01', expiry: '2027-01-15', dteRemaining: 98, dteTotal: 140,
    entryPrice: 1.0, currentPrice: 1.2, pnlDollar: 20, pnlPct: 20,
    stop: null, targets: [], status: 'PASS', contracts: 1, recId: 'REC-1',
    ...overrides,
  };
}

describe('openTotals', () => {
  it('gives the 2026-11-17 return on cost basis, not on market value', () => {
    const t = openTotals(portfolio20261117());
    expect(t.deployed).toBeCloseTo(494, 6);
    expect(t.openPnL).toBe(-37);
    expect(t.costBasis).toBeCloseTo(531, 6);
    expect(t.openPnLPct).toBeCloseTo(-6.968, 3);
    expect(t.quoted).toBe(2);
    expect(t.unquoted).toBe(1);
  });

  it('applies the option x100 and stock x1 multiplier and the contract count to cost basis', () => {
    const t = openTotals([
      makePosition({ symbol: 'OPT', contract: 'OPT|10|2027-01-15|C', entryPrice: 1.0, contracts: 3, recId: 'R-OPT' }),
      makePosition({ symbol: 'X', contract: 'X|STOCK', entryPrice: 50, currentPrice: 51, contracts: 10, recId: 'R-X' }),
    ]);
    expect(t.costBasis).toBeCloseTo(800, 6);
  });

  it('gives 0 percent when the cost basis is 0', () => {
    const t = openTotals([makePosition({ entryPrice: 0, pnlDollar: 120 })]);
    expect(t.costBasis).toBe(0);
    expect(t.openPnLPct).toBe(0);
  });
});

describe('aggregateGreeks', () => {
  it('sums the 2026-11-17 greeks per position', () => {
    const g = aggregateGreeks(portfolio20261117());
    expect(g.deltaShares).toBeCloseTo(92.32, 6);
    expect(g.thetaDollars).toBeCloseTo(-1.81, 6);
    expect(g.deltaDollars).toBeCloseTo(2451.45, 2);
    expect(g.deltaDollarsExcluded).toBe(1);
  });

  it('scales theta by the multiplier and the contract count', () => {
    expect(positionThetaDollars(makePosition({ theta: -0.05, contracts: 3 }))).toBeCloseTo(-15, 6);
    expect(
      positionThetaDollars(makePosition({ contract: 'X|STOCK', theta: 0.02, contracts: 10 })),
    ).toBeCloseTo(0.2, 6);
    const g = aggregateGreeks([
      makePosition({ theta: -0.05, contracts: 3, recId: 'R-1' }),
      makePosition({ symbol: 'X', contract: 'X|STOCK', theta: 0.02, contracts: 10, recId: 'R-2' }),
    ]);
    expect(g.thetaDollars).toBeCloseTo(-14.8, 6);
  });

  it('gives null for all three when no position has greeks', () => {
    const positions = [makePosition({ recId: 'R-1' }), makePosition({ recId: 'R-2' })];
    const g = aggregateGreeks(positions);
    expect(g.deltaShares).toBeNull();
    expect(g.thetaDollars).toBeNull();
    expect(g.deltaDollars).toBeNull();
    expect(g.deltaDollarsExcluded).toBe(positions.length);
  });

  it('leaves a row with delta but no underlying price out of delta in dollars', () => {
    const g = aggregateGreeks([
      makePosition({ delta: 0.5, currentStockPrice: undefined, recId: 'R-1' }),
      makePosition({ delta: 0.5, currentStockPrice: 100, recId: 'R-2' }),
    ]);
    expect(g.deltaDollars).toBeCloseTo(5000, 6);
    expect(g.deltaDollarsExcluded).toBe(1);
  });

  it('gives null theta dollars for a row whose theta is null or absent', () => {
    expect(positionThetaDollars(makePosition({ theta: null as unknown as number }))).toBeNull();
    expect(positionThetaDollars(makePosition({ theta: undefined }))).toBeNull();
  });
});

describe('deltaDollarsNote', () => {
  it('says how many positions delta in dollars left out', () => {
    expect(deltaDollarsNote(0)).toBeNull();
    expect(deltaDollarsNote(1)).toBe('Δ in dollars excludes 1 position without delta or underlying price');
    expect(deltaDollarsNote(2)).toBe('Δ in dollars excludes 2 positions without delta or underlying price');
  });
});
