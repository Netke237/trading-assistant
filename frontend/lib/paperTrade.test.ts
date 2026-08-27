import { buildPaperStockPosition, stockPositionLevels, invalidTargetRungs, stockCardSnapshotOf } from './paperTrade';
import type { PositionCardData } from '@/types/stockDomain';

describe('buildPaperStockPosition', () => {
  it('creates a long underlying position tagged as paper stock', () => {
    const p = buildPaperStockPosition('AAPL', 150, 10, 'Bullish');
    expect(p.symbol).toBe('AAPL');
    expect(p.contract).toBe('AAPL|STOCK');
    expect(p.entryPrice).toBe(150);
    expect(p.contracts).toBe(10);
    expect(p.direction).toBe('Bullish');
  });

  it('records the real direction for a short entry, not a hardcoded Bullish', () => {
    const p = buildPaperStockPosition('TSLA', 250, 5, 'Bearish');
    expect(p.direction).toBe('Bearish');
  });
});

describe('stockPositionLevels', () => {
  it('never emits a 0 stop — floorStop would silently treat it as unset', () => {
    expect(stockPositionLevels(100, 'Bullish', 0, []).stop).toBeNull();
    expect(stockPositionLevels(100, 'Bullish', -5, []).stop).toBeNull();
    expect(stockPositionLevels(100, 'Bullish', null, []).stop).toBeNull();
  });

  it('drops a stop on the wrong side of entry', () => {
    expect(stockPositionLevels(100, 'Bullish', 105, []).stop).toBeNull();
    expect(stockPositionLevels(100, 'Bearish', 95, []).stop).toBeNull();
  });

  it('keeps a genuine stop on the correct side', () => {
    expect(stockPositionLevels(100, 'Bullish', 95, []).stop).toBe(95);
    expect(stockPositionLevels(100, 'Bearish', 105, []).stop).toBe(105);
  });

  it('sorts targets nearest-first because TP_HIT only reads targets[0]', () => {
    const { targets } = stockPositionLevels(100, 'Bullish', 95, [
      { price: 120, shares: 3 }, { price: 105, shares: 5 }, { price: 110, shares: 2 },
    ]);
    expect(targets.map((t) => t.stockPrice)).toEqual([105, 110, 120]);
    expect(targets.map((t) => t.contractsToSell)).toEqual([5, 2, 3]);
  });

  it('sorts bearish targets nearest-first (descending price)', () => {
    const { targets } = stockPositionLevels(100, 'Bearish', 105, [
      { price: 80 }, { price: 95 }, { price: 90 },
    ]);
    expect(targets.map((t) => t.stockPrice)).toEqual([95, 90, 80]);
  });

  it('drops targets on the wrong side of entry', () => {
    const { targets } = stockPositionLevels(100, 'Bullish', 95, [{ price: 99 }, { price: 110 }]);
    expect(targets.map((t) => t.stockPrice)).toEqual([110]);
  });

  it('writes both stockPrice and targetPrice on every rung', () => {
    const { targets } = stockPositionLevels(100, 'Bullish', 95, [{ price: 110 }]);
    expect(targets[0]).toMatchObject({ stockPrice: 110, targetPrice: 110, status: 'PENDING' });
  });

  it('returns no levels at all when entry is unusable', () => {
    expect(stockPositionLevels(0, 'Bullish', 95, [{ price: 110 }])).toEqual({ stop: null, targets: [] });
  });
});

describe('buildPaperStockPosition levels', () => {
  it('carries a real stop and ladder', () => {
    const p = buildPaperStockPosition('AAPL', 100, 10, 'Bullish', undefined, {
      stop: 95, targets: [{ price: 110, shares: 4 }, { price: 120, shares: 6 }],
    });
    expect(p.stop).toBe(95);
    expect(p.targets).toHaveLength(2);
    expect(p.targets[0].stockPrice).toBe(110);
  });

  it('leaves stop null when no levels are supplied (ChartWorkspace manual buy)', () => {
    expect(buildPaperStockPosition('AAPL', 100, 10, 'Bullish').stop).toBeNull();
  });

  it('carries a structural stop only when one was supplied', () => {
    expect(buildPaperStockPosition('AAPL', 100, 10, 'Bullish').structuralStop).toBeNull();
    const p = buildPaperStockPosition('AAPL', 100, 10, 'Bullish', undefined, {
      stop: 95, structuralStop: 93.456,
    });
    expect(p.structuralStop).toBe(93.46);
  });
});

describe('invalidTargetRungs', () => {
  it('returns nothing when every target is on the correct side of entry', () => {
    expect(invalidTargetRungs(100, 'Bullish', [{ price: 105 }, { price: 110 }])).toEqual([]);
    expect(invalidTargetRungs(100, 'Bearish', [{ price: 95 }, { price: 90 }])).toEqual([]);
  });

  it('flags a Bullish target that sits behind (or at) entry', () => {
    expect(invalidTargetRungs(100, 'Bullish', [{ price: 95 }, { price: 110 }])).toEqual([95]);
    expect(invalidTargetRungs(100, 'Bullish', [{ price: 100 }])).toEqual([100]);
  });

  it('flags a Bearish target that sits behind (or at) entry', () => {
    expect(invalidTargetRungs(100, 'Bearish', [{ price: 105 }, { price: 90 }])).toEqual([105]);
  });

  it('flags a non-finite or non-positive price', () => {
    expect(invalidTargetRungs(100, 'Bullish', [{ price: 0 }, { price: -5 }, { price: NaN }]))
      .toEqual([0, -5, NaN]);
  });

  it('flags every target when entry itself is unusable', () => {
    expect(invalidTargetRungs(0, 'Bullish', [{ price: 105 }, { price: 110 }])).toEqual([105, 110]);
  });

  it('agrees with stockPositionLevels on what survives', () => {
    // The two functions apply the same sign check; what one flags as invalid,
    // the other must drop, and vice versa.
    const targets = [{ price: 95 }, { price: 105 }, { price: 110 }];
    const bad = invalidTargetRungs(100, 'Bullish', targets);
    const { targets: kept } = stockPositionLevels(100, 'Bullish', 95, targets);
    expect(bad).toEqual([95]);
    expect(kept.map((t) => t.stockPrice)).toEqual([105, 110]);
  });
});

describe('stockCardSnapshotOf', () => {
  function makeCard(overrides: Partial<PositionCardData> = {}): PositionCardData {
    return {
      symbol: 'AAPL', company: 'Apple Inc.', price: 190, direction: 'Bullish',
      strategy: {
        strategy: 'pullback_ema', entry_price: 190, stop_price: 182,
        target_price: 205, rr_ratio: 1.9, atr: 3.2, detail: {},
      },
      backtest: {
        n_trades: 40, win_rate: 0.55, total_return_pct: 12, max_drawdown_pct: 8,
        expectancy: 0.4, sharpe: 1.1, confidence: 70, passes_gate: true, summary_text: 'ok',
      },
      stock_score: 78, stock_status: 'PASS', shares: 10, dollar_risk: 80, dollar_size: 1900,
      confidence: 70, confidence_text: 'Solid',
      ...overrides,
    };
  }

  it('includes the horizon label passed in', () => {
    const snap = stockCardSnapshotOf(makeCard(), 'Swing (5–15d)');
    expect(snap.horizon).toBe('Swing (5–15d)');
    expect(snap.stock_score).toBe(78);
  });

  it('still carries the edited overlay when one is passed', () => {
    const snap = stockCardSnapshotOf(makeCard(), 'Swing (5–15d)', {
      entry: 191, stop: 183, targets: [206, 212, 218], shares: 12,
    });
    expect(snap.edited).toEqual({ entry: 191, stop: 183, targets: [206, 212, 218], shares: 12 });
  });
});
