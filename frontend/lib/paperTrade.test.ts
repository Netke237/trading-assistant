import { buildPaperStockPosition } from './paperTrade';

describe('buildPaperStockPosition', () => {
  it('creates a long underlying position tagged as paper stock', () => {
    const p = buildPaperStockPosition('AAPL', 150, 10);
    expect(p.symbol).toBe('AAPL');
    expect(p.contract).toBe('AAPL|STOCK');
    expect(p.entryPrice).toBe(150);
    expect(p.contracts).toBe(10);
  });
});
