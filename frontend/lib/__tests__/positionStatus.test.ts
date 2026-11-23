import { derivePositionStatus } from '@/lib/positionStatus';
import { scanPortfolio, STOP_PROXIMITY_PCT, TIME_STOP_DTE } from '@/lib/alertEngine';
import type { PortfolioPosition } from '@/types/domain';

const OPTS = { premiumStopPct: 0.6 };

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

describe('STOP_PROXIMITY_PCT', () => {
  it('is 2%', () => expect(STOP_PROXIMITY_PCT).toBe(0.02));
});

describe('derivePositionStatus - REJECT', () => {
  it('stop breached (bullish option, underlying below stop)', () => {
    const r = derivePositionStatus(opt({ currentStockPrice: 89 }), OPTS);
    expect(r).toEqual({ status: 'REJECT', reason: 'Stop breached', breach: 'stop' });
  });
  it('stop breached (bearish: underlying at/above stop)', () => {
    const r = derivePositionStatus(opt({ direction: 'Bearish', stop: 110, currentStockPrice: 110 }), OPTS);
    expect(r).toMatchObject({ status: 'REJECT', reason: 'Stop breached', breach: 'stop' });
  });
  it('stock stop breached', () => {
    expect(derivePositionStatus(stk({ stop: 105 }), OPTS)).toMatchObject({ status: 'REJECT', breach: 'stop' });
  });
  it('structural breach only', () => {
    const r = derivePositionStatus(opt({ stop: 80, structuralStop: 95, currentStockPrice: 94 }), OPTS);
    expect(r).toEqual({ status: 'REJECT', reason: 'Structural stop breached', breach: 'structural' });
  });
  it('premium stop only', () => {
    const r = derivePositionStatus(opt({ currentPrice: 1.5, pnlPct: -70 }), OPTS);
    expect(r).toEqual({ status: 'REJECT', reason: 'Premium stop hit', breach: 'premium' });
  });
  it('short stock premium stop fires on a rise', () => {
    const r = derivePositionStatus(
      stk({ direction: 'Bearish', stop: null, entryPrice: 100, currentPrice: 170 }), OPTS);
    expect(r).toMatchObject({ status: 'REJECT', breach: 'premium' });
  });
  it('precedence: stop beats structural beats premium', () => {
    const all = opt({ currentStockPrice: 80, stop: 90, structuralStop: 95, currentPrice: 1 });
    expect(derivePositionStatus(all, OPTS).breach).toBe('stop');
    const two = opt({ currentStockPrice: 94, stop: 80, structuralStop: 95, currentPrice: 1 });
    expect(derivePositionStatus(two, OPTS).breach).toBe('structural');
  });
  it('per-position alert overrides do not change the badge', () => {
    const p = opt({ currentStockPrice: 89, alertOverrides: { STOP_REACHED: false } });
    expect(derivePositionStatus(p, OPTS)).toMatchObject({ status: 'REJECT', breach: 'stop' });
  });
  it('uses the passed premiumStopPct', () => {
    const p = opt({ currentPrice: 3.4 });
    expect(derivePositionStatus(p, { premiumStopPct: 0.3 }).breach).toBe('premium');
    expect(derivePositionStatus(p, { premiumStopPct: 0.6 }).breach).toBeNull();
    expect(derivePositionStatus(opt({ currentPrice: 4 }), { premiumStopPct: 0.3 }).breach).toBeNull();
  });
});

describe('derivePositionStatus - CAUTION', () => {
  it('stop proximity bullish', () => {
    const r = derivePositionStatus(opt({ stop: 98.5 }), OPTS);
    expect(r).toEqual({ status: 'CAUTION', reason: '1.5% above stop', breach: null });
  });
  it('stop proximity bearish says below', () => {
    const r = derivePositionStatus(opt({ direction: 'Bearish', stop: 101.5 }), OPTS);
    expect(r).toMatchObject({ status: 'CAUTION', reason: '1.5% below stop' });
  });
  it('structural proximity', () => {
    const r = derivePositionStatus(opt({ stop: 50, structuralStop: 99 }), OPTS);
    expect(r).toMatchObject({ status: 'CAUTION', reason: '1.0% above struct. stop' });
  });
  it('picks the nearer of stop and structural', () => {
    const r = derivePositionStatus(opt({ stop: 98.5, structuralStop: 99.5 }), OPTS);
    expect(r.reason).toBe('0.5% above struct. stop');
  });
  it('boundary: exactly 2.0% is CAUTION (<=)', () => {
    expect(derivePositionStatus(opt({ stop: 98 }), OPTS)).toMatchObject({ status: 'CAUTION', reason: '2.0% above stop' });
  });
  it('boundary: just over 2.0% is not CAUTION', () => {
    expect(derivePositionStatus(opt({ stop: 97.9 }), OPTS).status).toBe('PASS');
  });
  it('bearish boundary exactly 2.0%', () => {
    expect(derivePositionStatus(opt({ direction: 'Bearish', stop: 102 }), OPTS).status).toBe('CAUTION');
  });
  it('proximity applies to stocks', () => {
    expect(derivePositionStatus(stk({ stop: 99 }), OPTS)).toMatchObject({ status: 'CAUTION', reason: '1.0% above stop' });
  });
  it('option time stop', () => {
    const r = derivePositionStatus(opt({ dteRemaining: TIME_STOP_DTE }), OPTS);
    expect(r).toEqual({ status: 'CAUTION', reason: '≤3 DTE', breach: null });
  });
  it('option just above the time-stop DTE is PASS', () => {
    expect(derivePositionStatus(opt({ dteRemaining: TIME_STOP_DTE + 1 }), OPTS).status).toBe('PASS');
  });
  describe('stock hold reached', () => {
    beforeEach(() => { jest.useFakeTimers(); jest.setSystemTime(new Date(2026, 10, 20, 12)); });
    afterEach(() => jest.useRealTimers());
    it('reports days held', () => {
      const r = derivePositionStatus(stk({ entryDate: '2026-11-10', holdMaxDays: 10 }), OPTS);
      expect(r).toEqual({ status: 'CAUTION', reason: 'Hold 10d reached', breach: null });
    });
    it('not reached is PASS', () => {
      expect(derivePositionStatus(stk({ entryDate: '2026-11-15', holdMaxDays: 10 }), OPTS).status).toBe('PASS');
    });
  });
  it('option with quoteUnavailable but known underlying and no stop hit', () => {
    const r = derivePositionStatus(opt({ quoteUnavailable: true, currentPrice: 0 }), OPTS);
    expect(r).toEqual({ status: 'CAUTION', reason: 'No option quote', breach: null });
  });
  it('option currentPrice 0 without the flag is also No option quote', () => {
    expect(derivePositionStatus(opt({ currentPrice: 0 }), OPTS).reason).toBe('No option quote');
  });
  it('stop proximity beats time stop and missing quote', () => {
    const r = derivePositionStatus(opt({ stop: 99, dteRemaining: 1, currentPrice: 0 }), OPTS);
    expect(r.reason).toBe('1.0% above stop');
  });
  it('stop-less rows skip proximity', () => {
    expect(derivePositionStatus(opt({ stop: null, structuralStop: null }), OPTS).status).toBe('PASS');
  });
});

describe('derivePositionStatus - PASS', () => {
  it('between stop and T1', () => {
    expect(derivePositionStatus(opt(), OPTS)).toEqual({ status: 'PASS', reason: 'Between stop and T1', breach: null });
  });
  it('target reached bullish', () => {
    expect(derivePositionStatus(opt({ currentStockPrice: 121 }), OPTS))
      .toEqual({ status: 'PASS', reason: 'Target 1 reached', breach: null });
  });
  it('target reached bearish', () => {
    const p = opt({ direction: 'Bearish', stop: 110, currentStockPrice: 79, targets: [{ stockPrice: 80 } as never] });
    expect(derivePositionStatus(p, OPTS).reason).toBe('Target 1 reached');
  });
  it('target reached via resolvedTpPrice snapshot', () => {
    expect(derivePositionStatus(opt({ resolvedTpPrice: 100, currentStockPrice: 101 }), OPTS).reason).toBe('Target 1 reached');
  });
});

describe('derivePositionStatus - NO_DATA', () => {
  it('option with no quote and no underlying', () => {
    const r = derivePositionStatus(opt({ quoteUnavailable: true, currentPrice: 0, currentStockPrice: undefined }), OPTS);
    expect(r).toEqual({ status: 'NO_DATA', reason: 'No quote', breach: null });
  });
  it('option no quote and underlying 0', () => {
    expect(derivePositionStatus(opt({ currentPrice: 0, currentStockPrice: 0 }), OPTS).status).toBe('NO_DATA');
  });
  it('stock quoteUnavailable', () => {
    expect(derivePositionStatus(stk({ quoteUnavailable: true, currentPrice: 0, currentStockPrice: 0 }), OPTS))
      .toEqual({ status: 'NO_DATA', reason: 'No quote', breach: null });
  });
  it('stock currentPrice 0', () => {
    expect(derivePositionStatus(stk({ currentPrice: 0 }), OPTS).status).toBe('NO_DATA');
  });
});

describe('2026-11-17 fixtures', () => {
  const BMY = opt({
    symbol: 'BMY', contract: 'BMY|60|2027-01-15|C', direction: 'Bullish', quoteUnavailable: true,
    currentPrice: 0, currentStockPrice: 60.95, stop: 64.13, structuralStop: null, targets: [{ stockPrice: 70 } as never],
  });
  const CMG = opt({
    symbol: 'CMG', contract: 'CMG|35|2027-01-15|C', currentPrice: 2, entryPrice: 2, currentStockPrice: 36.06,
    stop: 30, structuralStop: 35.66, targets: [{ stockPrice: 45 } as never],
  });
  const NCLH = opt({
    symbol: 'NCLH', contract: 'NCLH|20|2027-01-15|C', currentPrice: 1, entryPrice: 1, currentStockPrice: 22,
    stop: 18, structuralStop: null, targets: [{ stockPrice: 26 } as never],
  });
  it('BMY REJECT Stop breached', () => {
    expect(derivePositionStatus(BMY, OPTS)).toEqual({ status: 'REJECT', reason: 'Stop breached', breach: 'stop' });
  });
  it('CMG CAUTION 1.1% above struct. stop', () => {
    expect(derivePositionStatus(CMG, OPTS)).toEqual({ status: 'CAUTION', reason: '1.1% above struct. stop', breach: null });
  });
  it('NCLH PASS', () => {
    expect(derivePositionStatus(NCLH, OPTS).status).toBe('PASS');
  });

  it('agrees with scanPortfolio on REJECT and Target-reached for every fixture', () => {
    const fixtures = [
      BMY, CMG, NCLH,
      opt({ currentStockPrice: 89 }), opt({ currentStockPrice: 121 }), opt({ currentPrice: 1 }),
      opt({ stop: 80, structuralStop: 95, currentStockPrice: 94 }),
      stk({ stop: 105 }), stk({ direction: 'Bearish', stop: null, currentPrice: 170 }),
      opt({ direction: 'Bearish', stop: 110, currentStockPrice: 79, targets: [{ stockPrice: 80 } as never] }),
      opt({ quoteUnavailable: true, currentPrice: 0, currentStockPrice: undefined }),
    ];
    for (const p of fixtures) {
      const types = scanPortfolio([{ ...p, alertOverrides: {} }], { premiumStopPct: 0.6 }).map(r => r.alertType);
      const d = derivePositionStatus(p, OPTS);
      const rejecting = types.some(t => t === 'STOP_REACHED' || t === 'STRUCTURAL_STOP_BREACHED' || t === 'PREMIUM_STOP');
      expect(d.status === 'REJECT').toBe(rejecting);
      if (!rejecting && d.status === 'PASS') expect(d.reason === 'Target 1 reached').toBe(types.includes('TP_HIT'));
      if (d.status === 'REJECT') {
        const expected = types.includes('STOP_REACHED') ? 'stop'
          : types.includes('STRUCTURAL_STOP_BREACHED') ? 'structural' : 'premium';
        expect(d.breach).toBe(expected);
      }
    }
  });
});
