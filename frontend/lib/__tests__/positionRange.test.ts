import { positionRange } from '@/lib/positionRange';
import type { PortfolioPosition } from '@/types/domain';

function opt(over: Partial<PortfolioPosition> = {}): PortfolioPosition {
  return {
    symbol: 'AAA', contract: 'AAA|100|2027-01-15|C', direction: 'Bullish',
    entryDate: '2026-11-01', expiry: '2027-01-15', dteRemaining: 40, dteTotal: 60,
    entryPrice: 5, currentPrice: 5, currentStockPrice: 100, pnlDollar: 0, pnlPct: 0,
    stop: 90, structuralStop: 95, targets: [{ stockPrice: 120 } as never],
    status: 'PENDING', recId: 'r1',
    ...over,
  } as PortfolioPosition;
}

describe('positionRange', () => {
  it('bullish: stop left, T1 right, fraction between, percentages vs underlying', () => {
    const r = positionRange(opt())!;
    expect(r).toMatchObject({ stop: 90, structural: 95, t1: 120, underlying: 100, pinned: null });
    expect(r.fraction).toBeCloseTo(10 / 30, 6);
    expect(r.stopPct).toBeCloseTo(-10, 6);
    expect(r.structPct).toBeCloseTo(-5, 6);
    expect(r.t1Pct).toBeCloseTo(20, 6);
    expect(r.text).toBe('$100.00 · stop −10.0% · struct −5.0% · T1 +20.0%');
  });
  it('bearish mirrors: T1 at the low (left) end, stop at the high (right) end', () => {
    const r = positionRange(opt({ direction: 'Bearish', stop: 110, structuralStop: 105, targets: [{ stockPrice: 80 } as never] }))!;
    expect(r.fraction).toBeCloseTo(20 / 30, 6);
    expect(r.stopPct).toBeCloseTo(10, 6);
    expect(r.t1Pct).toBeCloseTo(-20, 6);
  });
  it('pins left at/below the stop (bullish) and right at/above T1', () => {
    expect(positionRange(opt({ currentStockPrice: 85 }))).toMatchObject({ fraction: 0, pinned: 'left' });
    expect(positionRange(opt({ currentStockPrice: 125 }))).toMatchObject({ fraction: 1, pinned: 'right' });
  });
  it('pins bearish: above the stop is the right end, below T1 the left end', () => {
    const b = { direction: 'Bearish' as const, stop: 110, targets: [{ stockPrice: 80 } as never] };
    expect(positionRange(opt({ ...b, currentStockPrice: 115 }))).toMatchObject({ fraction: 1, pinned: 'right' });
    expect(positionRange(opt({ ...b, currentStockPrice: 75 }))).toMatchObject({ fraction: 0, pinned: 'left' });
  });
  it('is null when the underlying or the stop is missing', () => {
    expect(positionRange(opt({ currentStockPrice: undefined }))).toBeNull();
    expect(positionRange(opt({ stop: null }))).toBeNull();
  });
  it('without T1: no right end, text omits T1', () => {
    const r = positionRange(opt({ targets: [] }))!;
    expect(r.t1).toBeNull();
    expect(r.t1Pct).toBeNull();
    expect(r.fraction).toBeNull();
    expect(r.text).not.toContain('T1');
  });
  it('without a structural stop: structural null and absent from text', () => {
    const r = positionRange(opt({ structuralStop: null }))!;
    expect(r.structural).toBeNull();
    expect(r.text).not.toContain('struct');
  });
  it('uses the resolved TP snapshot over the ladder', () => {
    expect(positionRange(opt({ resolvedTpPrice: 130 }))!.t1).toBe(130);
  });
  it('stock uses currentPrice as underlying', () => {
    const r = positionRange(opt({ contract: 'AAA|STOCK', currentPrice: 100, currentStockPrice: 1 }))!;
    expect(r.underlying).toBe(100);
  });
});
