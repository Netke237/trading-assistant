import { EXIT_REASONS, exitReasonLabel, defaultExitReason } from '@/lib/exitReason';
import type { PortfolioPosition } from '@/types/domain';

const OPTS = { premiumStopPct: 0.6, exitDate: '2026-11-27' };

function opt(over: Partial<PortfolioPosition> = {}): PortfolioPosition {
  return {
    symbol: 'AAA', contract: 'AAA|100|2027-01-15|C', direction: 'Bullish',
    entryDate: '2026-11-01', expiry: '2027-01-15', dteRemaining: 40, dteTotal: 60,
    entryPrice: 5, currentPrice: 5, currentStockPrice: 100, pnlDollar: 0, pnlPct: 0,
    stop: 90, structuralStop: null, targets: [{ stockPrice: 120 } as never],
    status: 'PENDING', recId: 'r1',
    ...over,
  } as PortfolioPosition;
}
function stk(over: Partial<PortfolioPosition> = {}): PortfolioPosition {
  return opt({
    contract: 'AAA|STOCK', currentPrice: 100, currentStockPrice: 100, entryPrice: 100,
    dteRemaining: 0, dteTotal: 0, ...over,
  });
}

describe('EXIT_REASONS / exitReasonLabel', () => {
  it('lists the 8 stored values in order', () => {
    expect(EXIT_REASONS).toEqual([
      'stop', 'structural_stop', 'premium_stop', 'target', 'time_stop', 'expiry', 'manual', 'unknown',
    ]);
  });
  it('labels every value and says "Not recorded" for null/undefined', () => {
    expect(EXIT_REASONS.map(exitReasonLabel)).toEqual([
      'Stop', 'Structural stop', 'Premium stop', 'Target', 'Time stop', 'Expiry', 'Manual', 'Unknown',
    ]);
    expect(exitReasonLabel(null)).toBe('Not recorded');
    expect(exitReasonLabel(undefined)).toBe('Not recorded');
  });
});

describe('defaultExitReason', () => {
  it('stop breach -> stop', () => {
    expect(defaultExitReason(opt({ currentStockPrice: 89 }), OPTS)).toBe('stop');
  });
  it('structural breach -> structural_stop', () => {
    expect(defaultExitReason(opt({ stop: 80, structuralStop: 95, currentStockPrice: 94 }), OPTS)).toBe('structural_stop');
  });
  it('premium breach (option) -> premium_stop', () => {
    expect(defaultExitReason(opt({ currentPrice: 1.9 }), OPTS)).toBe('premium_stop');
  });
  it('percent-stop breach on a stock -> premium_stop too', () => {
    expect(defaultExitReason(stk({ stop: null, currentPrice: 30, currentStockPrice: 30, targets: [] }), OPTS)).toBe('premium_stop');
  });
  it('option expiring on/before the exit date -> expiry', () => {
    expect(defaultExitReason(opt({ contract: 'AAA|100|2026-11-27|C', dteRemaining: 0 }), OPTS)).toBe('expiry');
    expect(defaultExitReason(opt({ contract: 'AAA|100|2026-11-20|C', dteRemaining: 0 }), OPTS)).toBe('expiry');
  });
  it('option within the time-stop window but not expired -> time_stop', () => {
    expect(defaultExitReason(opt({ contract: 'AAA|100|2026-11-30|C', dteRemaining: 2 }), OPTS)).toBe('time_stop');
  });
  it('target reached -> target', () => {
    expect(defaultExitReason(opt({ currentStockPrice: 121 }), OPTS)).toBe('target');
  });
  it('nothing triggered -> manual', () => {
    expect(defaultExitReason(opt(), OPTS)).toBe('manual');
    expect(defaultExitReason(stk({ stop: 90 }), OPTS)).toBe('manual');
  });
  it('a breach beats a target', () => {
    // Bearish option: stop 110 above, target 120 also above; underlying 121 hits both.
    const p = opt({ direction: 'Bearish', stop: 110, currentStockPrice: 121, targets: [{ stockPrice: 125 } as never] });
    expect(defaultExitReason(p, OPTS)).toBe('stop');
    // Bullish stock whose percent stop fired while a (stale) target sits below price.
    const s = stk({ stop: null, entryPrice: 100, currentPrice: 30, currentStockPrice: 30, targets: [{ stockPrice: 25 } as never] });
    expect(defaultExitReason(s, OPTS)).toBe('premium_stop');
  });
});
