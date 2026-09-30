import { splitStockRejected, STOCK_SHORTLIST_REASON_PREFIX } from '@/lib/stockShortlist';

describe('splitStockRejected', () => {
  it('separates over-cap names from gate rejections, keeping order', () => {
    const entries = [
      { symbol: 'A', reason: 'no pullback_ema setup' },
      { symbol: 'B', reason: `${STOCK_SHORTLIST_REASON_PREFIX} PASS score 70 confidence 60% ranked 11 of 12 (cap 10)` },
      { symbol: 'C', reason: 'backtest gate: 38% win over 12 trades' },
      { symbol: 'D', reason: `${STOCK_SHORTLIST_REASON_PREFIX} CAUTION score 80 confidence n/a ranked 12 of 12 (cap 10)` },
    ];
    const { rejected, overCap } = splitStockRejected(entries);
    expect(rejected.map((r) => r.symbol)).toEqual(['A', 'C']);
    expect(overCap.map((r) => r.symbol)).toEqual(['B', 'D']);
  });

  it('only matches the prefix at the start of the reason', () => {
    const { rejected, overCap } = splitStockRejected([{ symbol: 'X', reason: 'error: Shortlist cap: x' }]);
    expect(rejected).toHaveLength(1);
    expect(overCap).toHaveLength(0);
  });

  it('tolerates a missing list', () => {
    expect(splitStockRejected(undefined)).toEqual({ rejected: [], overCap: [] });
  });
});
