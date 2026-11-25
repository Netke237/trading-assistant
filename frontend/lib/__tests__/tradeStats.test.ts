import {
  classOf, holdDays, returnPct, exitCheck, computeTradeStats, filterTrades, sortTrades, tradeLabel,
} from '../tradeStats';
import type { ClosedPosition } from '../performanceStore';

let seq = 0;
function row(over: Partial<ClosedPosition> = {}): ClosedPosition {
  seq += 1;
  return {
    id: `id${seq}`, recId: `rec${seq}`, symbol: 'NFLX', contract: 'NFLX|82|2026-12-18|C',
    direction: 'Bullish', entryPrice: 5, entryDate: '2026-11-01', exitPrice: 4,
    exitDate: '2026-11-17', qtyClosed: 1, realizedPnlDollar: -100, realizedPnlPct: -20,
    closedAt: '2026-11-17T10:00:00Z', ...over,
  };
}

function addDays(iso: string, n: number): string {
  const [y, m, d] = iso.split('-').map(Number) as [number, number, number];
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}

const EXIT = '2026-11-17';
function fixture(): ClosedPosition[] {
  const spec: Array<[number, number, number]> = [
    // dollar, pct, hold days
    [400, 80, 6], [360, 60, 111],
    [-1000, -99, 100], [-900, -85, 90], [-655, -70, 80], [-500, -65, 70], [-300, -40, 60],
    [0, 0, 91],
  ];
  return spec.map(([d, p, h], i) => row({
    symbol: i < 4 ? 'NFLX' : 'AAPL', realizedPnlDollar: d, realizedPnlPct: p,
    exitDate: EXIT, entryDate: addDays(EXIT, -h),
  }));
}

describe('classOf', () => {
  it('uses integer cents', () => {
    expect(classOf(row({ realizedPnlDollar: 0.01 }))).toBe('win');
    expect(classOf(row({ realizedPnlDollar: -0.01 }))).toBe('loss');
    expect(classOf(row({ realizedPnlDollar: -0.004 }))).toBe('flat');
    expect(classOf(row({ realizedPnlDollar: 0 }))).toBe('flat');
  });
});

describe('holdDays', () => {
  it('counts calendar days', () => {
    expect(holdDays(row({ entryDate: '2026-11-01', exitDate: '2026-11-17' }))).toBe(16);
  });
  it('same day is 0', () => {
    expect(holdDays(row({ entryDate: '2026-11-17', exitDate: '2026-11-17' }))).toBe(0);
  });
  it('strips a time suffix', () => {
    expect(holdDays(row({ entryDate: '2026-11-01T23:59:00', exitDate: '2026-11-17T00:00:01Z' }))).toBe(16);
  });
  it('null for missing entry date', () => {
    expect(holdDays(row({ entryDate: undefined }))).toBeNull();
    expect(holdDays(row({ entryDate: '' }))).toBeNull();
  });
  it('null for an invalid calendar date', () => {
    expect(holdDays(row({ entryDate: '2026-02-31' }))).toBeNull();
    expect(holdDays(row({ exitDate: '2026-13-01' }))).toBeNull();
    expect(holdDays(row({ entryDate: 'garbage' }))).toBeNull();
  });
  it('null when exit is before entry', () => {
    expect(holdDays(row({ entryDate: '2026-11-18', exitDate: '2026-11-17' }))).toBeNull();
  });
  it('is not affected by a DST change', () => {
    expect(holdDays(row({ entryDate: '2026-03-01', exitDate: '2026-04-01' }))).toBe(31);
    expect(holdDays(row({ entryDate: '2026-10-01', exitDate: '2026-11-15' }))).toBe(45);
  });
});

describe('returnPct', () => {
  it('returns the stored pct', () => {
    expect(returnPct(row({ realizedPnlPct: -12.34 }))).toBe(-12.34);
  });
  it('null for a zero-cost entry', () => {
    expect(returnPct(row({ entryPrice: 0, realizedPnlPct: 0 }))).toBeNull();
  });
  it('null for non-finite pct', () => {
    expect(returnPct(row({ realizedPnlPct: Number.NaN }))).toBeNull();
  });
});

describe('exitCheck', () => {
  const loss = (pct: number, over: Partial<ClosedPosition> = {}) =>
    row({ realizedPnlDollar: -100, realizedPnlPct: pct, ...over });

  it('win and flat', () => {
    expect(exitCheck(row({ realizedPnlDollar: 50, realizedPnlPct: 10 }), 0.6)).toEqual({ kind: 'win', label: 'Win' });
    expect(exitCheck(row({ realizedPnlDollar: 0, realizedPnlPct: 0 }), 0.6)).toEqual({ kind: 'flat', label: 'Flat' });
  });
  it('past stop label', () => {
    expect(exitCheck(loss(-99), 0.6)).toEqual({ kind: 'past-stop', lossPct: 99, label: 'Lost 99%: past 60% premium stop' });
  });
  it('exactly 60.00 is within', () => {
    expect(exitCheck(loss(-60), 0.6)).toEqual({ kind: 'within-stop', label: 'Within premium stop' });
  });
  it('60.01 is past the stop', () => {
    expect(exitCheck(loss(-60.01), 0.6).kind).toBe('past-stop');
  });
  it('float-product boundary does not flip (0.29 stop, 29.00 loss)', () => {
    expect(exitCheck(loss(-29), 0.29).kind).toBe('within-stop');
    expect(exitCheck(loss(-29.01), 0.29).kind).toBe('past-stop');
  });
  it('60.4% loss against a 60% stop reads Lost 60.4%', () => {
    // 60.4 rounds to 6040 hundredths > 6000, so past stop; label must not say "Lost 60%: past 60%".
    const r = exitCheck(loss(-60.4), 0.6);
    expect(r.kind).toBe('past-stop');
    expect(r.label).toBe('Lost 60.4%: past 60% premium stop');
  });
  it('stock loss is excluded', () => {
    expect(exitCheck(loss(-90, { contract: 'NFLX|STOCK' }), 0.6)).toEqual({ kind: 'stock-loss', label: 'Stock loss' });
  });
  it('unknown contract is excluded', () => {
    expect(exitCheck(loss(-90, { contract: 'weird' }), 0.6)).toEqual({ kind: 'unknown', label: '—' });
  });
  it('zero-cost option loss is not past-stop', () => {
    expect(exitCheck(loss(0, { entryPrice: 0 }), 0.6)).toEqual({ kind: 'unknown', label: '—' });
  });
  it('positive pct on a loss row is unknown', () => {
    expect(exitCheck(loss(5), 0.6).kind).toBe('unknown');
  });
  it('invalid stop gives unknown', () => {
    for (const s of [0, 1, -0.5, 1.5, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(exitCheck(loss(-99), s).kind).toBe('unknown');
    }
  });
});

describe('computeTradeStats', () => {
  it('reproduces the pinned 2026-11-17 numbers', () => {
    const s = computeTradeStats(fixture(), 0.6);
    expect(s.count).toBe(8);
    expect(s.wins).toBe(2);
    expect(s.losses).toBe(5);
    expect(s.flats).toBe(1);
    expect(s.skipped).toBe(0);
    expect(Math.round(s.winRate as number)).toBe(29);
    expect(s.grossWon).toBe(760);
    expect(s.grossLost).toBe(3355);
    expect(s.avgWin).toBe(380);
    expect(s.avgLoss).toBe(-671);
    expect((s.lossToWin as number).toFixed(1)).toBe('1.8');
    expect((s.profitFactor as number).toFixed(2)).toBe('0.23');
    expect(s.total).toBe(-2595);
    expect(s.expectancy).toBeCloseTo(-324.375, 6);
    expect(s.hold).toEqual({ avg: 76, min: 6, max: 111, n: 8 });
    expect(s.pastStop).toEqual({ n: 4, of: 5 });
  });

  it('no trades', () => {
    const s = computeTradeStats([], 0.6);
    expect(s).toMatchObject({
      count: 0, wins: 0, losses: 0, flats: 0, skipped: 0, winRate: null, avgWin: null, avgLoss: null,
      lossToWin: null, profitFactor: null, expectancy: null, total: 0,
      hold: { avg: null, min: null, max: null, n: 0 }, pastStop: { n: 0, of: 0 },
    });
  });

  it('no losses', () => {
    const s = computeTradeStats([row({ realizedPnlDollar: 100, realizedPnlPct: 10 })], 0.6);
    expect(s.profitFactor).toBeNull();
    expect(s.avgLoss).toBeNull();
    expect(s.lossToWin).toBeNull();
    expect(s.winRate).toBe(100);
  });

  it('no wins', () => {
    const s = computeTradeStats([row({ realizedPnlDollar: -100 })], 0.6);
    expect(s.profitFactor).toBe(0);
    expect(s.avgWin).toBeNull();
    expect(s.lossToWin).toBeNull();
    expect(s.winRate).toBe(0);
  });

  it('all flat', () => {
    const s = computeTradeStats([row({ realizedPnlDollar: 0 }), row({ realizedPnlDollar: 0 })], 0.6);
    expect(s.winRate).toBeNull();
    expect(s.expectancy).toBe(0);
    expect(s.flats).toBe(2);
  });

  it('flats count in the expectancy denominator but not in win rate', () => {
    const s = computeTradeStats([
      row({ realizedPnlDollar: 100 }), row({ realizedPnlDollar: 0 }),
    ], 0.6);
    expect(s.winRate).toBe(100);
    expect(s.expectancy).toBe(50);
  });

  it('drops non-finite dollars and counts them in skipped', () => {
    const s = computeTradeStats([
      row({ realizedPnlDollar: 100 }), row({ realizedPnlDollar: Number.NaN }),
      row({ realizedPnlDollar: Number.POSITIVE_INFINITY }),
    ], 0.6);
    expect(s.count).toBe(1);
    expect(s.skipped).toBe(2);
    expect(s.total).toBe(100);
  });

  it('hold stats cover only rows with a hold', () => {
    const s = computeTradeStats([
      row({ entryDate: undefined }), row({ entryDate: '2026-11-07', exitDate: '2026-11-17' }),
    ], 0.6);
    expect(s.hold).toEqual({ avg: 10, min: 10, max: 10, n: 1 });
    expect(s.count).toBe(2);
  });

  it('stock losses and unchecked rows stay out of the pastStop denominator', () => {
    const s = computeTradeStats([
      row({ realizedPnlDollar: -100, realizedPnlPct: -90 }),
      row({ realizedPnlDollar: -100, realizedPnlPct: -90, contract: 'NFLX|STOCK' }),
      row({ realizedPnlDollar: -100, realizedPnlPct: 0, entryPrice: 0 }),
      row({ realizedPnlDollar: -100, realizedPnlPct: -90, contract: 'junk' }),
    ], 0.6);
    expect(s.losses).toBe(4);
    expect(s.pastStop).toEqual({ n: 1, of: 1 });
  });

  it('does not mutate its input', () => {
    const rows = fixture();
    const copy = JSON.parse(JSON.stringify(rows));
    computeTradeStats(rows, 0.6);
    expect(rows).toEqual(copy);
  });
});

describe('filterTrades', () => {
  const rows = [
    row({ symbol: 'NFLX', realizedPnlDollar: 100 }),
    row({ symbol: 'AAPL', realizedPnlDollar: -100 }),
    row({ symbol: 'BRK.B', realizedPnlDollar: 0 }),
  ];
  it('all keeps everything including flats', () => {
    expect(filterTrades(rows, 'all', '')).toHaveLength(3);
  });
  it('wins and losses exclude flats', () => {
    expect(filterTrades(rows, 'wins', '').map((r) => r.symbol)).toEqual(['NFLX']);
    expect(filterTrades(rows, 'losses', '').map((r) => r.symbol)).toEqual(['AAPL']);
  });
  it('search is a case-insensitive substring, whitespace trimmed', () => {
    expect(filterTrades(rows, 'all', '  nf ').map((r) => r.symbol)).toEqual(['NFLX']);
    expect(filterTrades(rows, 'all', 'k.')).toHaveLength(1);
    expect(filterTrades(rows, 'all', '   ')).toHaveLength(3);
  });
  it('combines filter and search', () => {
    expect(filterTrades(rows, 'losses', 'nflx')).toEqual([]);
  });
  it('does not mutate input', () => {
    const before = [...rows];
    filterTrades(rows, 'wins', 'x');
    expect(rows).toEqual(before);
  });
});

describe('sortTrades', () => {
  const a = row({ symbol: 'bbb', entryDate: '2026-01-05', exitDate: '2026-02-01', realizedPnlDollar: 50, realizedPnlPct: 5 });
  const b = row({ symbol: 'AAA', entryDate: '2026-01-02', exitDate: '2026-03-01', realizedPnlDollar: -20, realizedPnlPct: -2 });
  const c = row({ symbol: 'CCC', entryDate: undefined, exitDate: '2026-01-15', realizedPnlDollar: 10, realizedPnlPct: 0, entryPrice: 0 });
  const rows = [a, b, c];
  const ids = (xs: ClosedPosition[]) => xs.map((x) => x.id);

  it('no sort returns API order as a copy', () => {
    const out = sortTrades(rows, null, 'asc');
    expect(ids(out)).toEqual(ids(rows));
    expect(out).not.toBe(rows);
  });
  it('symbol, uppercase compare', () => {
    expect(ids(sortTrades(rows, 'symbol', 'asc'))).toEqual([b.id, a.id, c.id]);
    expect(ids(sortTrades(rows, 'symbol', 'desc'))).toEqual([c.id, a.id, b.id]);
  });
  it('entry with missing last both ways', () => {
    expect(ids(sortTrades(rows, 'entry', 'asc'))).toEqual([b.id, a.id, c.id]);
    expect(ids(sortTrades(rows, 'entry', 'desc'))).toEqual([a.id, b.id, c.id]);
  });
  it('exit', () => {
    expect(ids(sortTrades(rows, 'exit', 'asc'))).toEqual([c.id, a.id, b.id]);
    expect(ids(sortTrades(rows, 'exit', 'desc'))).toEqual([b.id, a.id, c.id]);
  });
  it('hold with nulls last', () => {
    // a: 27d, b: 58d, c: null
    expect(ids(sortTrades(rows, 'hold', 'asc'))).toEqual([a.id, b.id, c.id]);
    expect(ids(sortTrades(rows, 'hold', 'desc'))).toEqual([b.id, a.id, c.id]);
  });
  it('pnl', () => {
    expect(ids(sortTrades(rows, 'pnl', 'asc'))).toEqual([b.id, c.id, a.id]);
    expect(ids(sortTrades(rows, 'pnl', 'desc'))).toEqual([a.id, c.id, b.id]);
  });
  it('return with null last both ways', () => {
    expect(ids(sortTrades(rows, 'return', 'asc'))).toEqual([b.id, a.id, c.id]);
    expect(ids(sortTrades(rows, 'return', 'desc'))).toEqual([a.id, b.id, c.id]);
  });
  it('ties keep API order in both directions', () => {
    const t1 = row({ realizedPnlDollar: 5 });
    const t2 = row({ realizedPnlDollar: 5 });
    const t3 = row({ realizedPnlDollar: 5 });
    expect(ids(sortTrades([t1, t2, t3], 'pnl', 'asc'))).toEqual([t1.id, t2.id, t3.id]);
    expect(ids(sortTrades([t1, t2, t3], 'pnl', 'desc'))).toEqual([t1.id, t2.id, t3.id]);
  });
  it('does not mutate the input', () => {
    const before = ids(rows);
    sortTrades(rows, 'pnl', 'desc');
    expect(ids(rows)).toEqual(before);
  });
});

describe('tradeLabel', () => {
  it('stock', () => {
    expect(tradeLabel(row({ symbol: 'NFLX', contract: 'NFLX|STOCK' }))).toBe('NFLX stock');
  });
  it('option, no trailing .0', () => {
    expect(tradeLabel(row({ symbol: 'NFLX', contract: 'NFLX|82|2026-12-18|C' }))).toBe('NFLX 82C');
    expect(tradeLabel(row({ symbol: 'NFLX', contract: 'NFLX|82.0|2026-12-18|P' }))).toBe('NFLX 82P');
    expect(tradeLabel(row({ symbol: 'NFLX', contract: 'NFLX|82.5|2026-12-18|C' }))).toBe('NFLX 82.5C');
  });
  it('unknown', () => {
    expect(tradeLabel(row({ symbol: 'NFLX', contract: 'weird' }))).toBe('NFLX');
  });
});
