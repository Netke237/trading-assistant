import { buildPaperStockPosition } from './paperTrade';

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
