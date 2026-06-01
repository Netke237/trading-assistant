import { isoWeek, aggregateWeeks, tradeYears, toHistoryCsv, ymd } from '../portfolioHistory';
import type { ClosedPosition } from '../performanceStore';

function trade(partial: Partial<ClosedPosition>): ClosedPosition {
  return {
    id: 'id', recId: 'rec', symbol: 'AAPL', contract: 'AAPL|185|2026-06-19|C',
    direction: 'Bullish', entryPrice: 1.0, entryDate: '2026-01-01', exitPrice: 2.0,
    exitDate: '2026-01-08', qtyClosed: 1, realizedPnlDollar: 100, realizedPnlPct: 100,
    closedAt: '2026-01-08T00:00:00Z', ...partial,
  };
}

describe('ymd', () => {
  it('formats a local date as YYYY-MM-DD', () => {
    expect(ymd(new Date(2026, 0, 5))).toBe('2026-01-05');
  });
});

describe('isoWeek', () => {
  it('puts 2026-01-01 (Thursday) in ISO year 2026 week 1', () => {
    expect(isoWeek(new Date(2026, 0, 1))).toEqual({ isoYear: 2026, week: 1 });
  });
  it('puts 2027-01-01 (Friday) in ISO year 2026 week 53', () => {
    // 2026 is a 53-week ISO year; 2027-01-01 falls in its last ISO week.
    expect(isoWeek(new Date(2027, 0, 1))).toEqual({ isoYear: 2026, week: 53 });
  });
});

describe('aggregateWeeks', () => {
  it('produces 53 weeks for ISO year 2026 with week 1 starting on a Monday', () => {
    const weeks = aggregateWeeks([], 2026);
    expect(weeks).toHaveLength(53);
    expect(weeks[0]!.isoWeek).toBe(1);
    expect(weeks[0]!.start.getDay()).toBe(1); // Monday
    expect(weeks[52]!.isoWeek).toBe(53);
  });

  it('sums realized $ and computes weekly % from entry cost', () => {
    // Two trades closed Tue 2026-01-06 and Wed 2026-01-07 (both in ISO week 2 of 2026).
    const history = [
      trade({ exitDate: '2026-01-06', realizedPnlDollar: 200, entryPrice: 2, qtyClosed: 1 }), // cost 200
      trade({ exitDate: '2026-01-07', realizedPnlDollar: -50, entryPrice: 1, qtyClosed: 3 }), // cost 300
    ];
    const weeks = aggregateWeeks(history, 2026);
    const wk2 = weeks.find((w) => w.isoWeek === 2)!;
    expect(wk2.totalDollar).toBe(150);
    expect(wk2.totalCostBasis).toBe(500);
    expect(wk2.pct).toBeCloseTo(30, 5); // 150/500*100
    expect(wk2.days[1]).toBe(200);      // Tuesday
    expect(wk2.days[2]).toBe(-50);      // Wednesday
    expect(wk2.days[0]).toBeUndefined();// Monday, no trades
  });

  it('returns pct 0 for a week with no trades', () => {
    const wk1 = aggregateWeeks([], 2026).find((w) => w.isoWeek === 1)!;
    expect(wk1.totalDollar).toBe(0);
    expect(wk1.pct).toBe(0);
  });
});

describe('tradeYears', () => {
  it('returns sorted distinct ISO years that have trades', () => {
    const history = [
      trade({ exitDate: '2026-06-01' }),
      trade({ exitDate: '2027-03-01' }),
      trade({ exitDate: '2026-12-30' }), // ISO week 53 → still ISO year 2026
    ];
    expect(tradeYears(history)).toEqual([2026, 2027]);
  });
});

describe('toHistoryCsv', () => {
  it('emits a header row and one row per trade with quoted commas', () => {
    const csv = toHistoryCsv([
      trade({ symbol: 'AAPL', contract: 'AAPL|185|2026-06-19|C', qtyClosed: 2,
              entryPrice: 1.5, exitPrice: 2.25, realizedPnlDollar: 150, realizedPnlPct: 50,
              exitDate: '2026-06-01', entryDate: '2026-05-01', direction: 'Bull, ish' }),
    ]);
    const lines = csv.split('\n');
    expect(lines[0]).toBe('Exit Date,Entry Date,Symbol,Contract,Direction,Qty,Entry,Exit,P&L $,P&L %');
    expect(lines[1]).toBe('2026-06-01,2026-05-01,AAPL,AAPL|185|2026-06-19|C,"Bull, ish",2,1.50,2.25,150.00,50.00');
  });

  it('returns just the header for empty history', () => {
    expect(toHistoryCsv([])).toBe('Exit Date,Entry Date,Symbol,Contract,Direction,Qty,Entry,Exit,P&L $,P&L %');
  });
});
