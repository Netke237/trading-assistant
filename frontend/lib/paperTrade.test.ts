import { buildPaperStockPosition, stockPositionLevels } from './paperTrade';

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
