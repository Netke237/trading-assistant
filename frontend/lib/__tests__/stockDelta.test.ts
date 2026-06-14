import { computeStockDeltas } from '@/lib/stockDelta';
import type { StockScanResult } from '@/types/stockDomain';

function mk(symbols: Array<[string, number]>): StockScanResult {
  return {
    scan_id: 's', timestamp: 't', rejected: [],
    candidates: symbols.map(([symbol, stock_score]) => ({ symbol, stock_score } as any)),
  };
}

describe('computeStockDeltas', () => {
  it('returns empty map when previous is null', () => {
    const d = computeStockDeltas(mk([['AAPL', 80]]), null);
    expect(d.get('AAPL')).toBeUndefined();
  });

  it('computes score delta and rank delta vs previous run', () => {
    // previous order by score desc: MSFT(90, rank0), AAPL(70, rank1)
    const prev = mk([['MSFT', 90], ['AAPL', 70]]);
    // current order by score desc: AAPL(85, rank0), MSFT(80, rank1)
    const curr = mk([['AAPL', 85], ['MSFT', 80]]);

    const d = computeStockDeltas(curr, prev);
    expect(d.get('AAPL')).toEqual({ scoreDelta: 15, rankDelta: 1 });   // 85-70; moved 1→0 = +1
    expect(d.get('MSFT')).toEqual({ scoreDelta: -10, rankDelta: -1 }); // 80-90; moved 0→1 = -1
  });

  it('omits symbols not present in previous run', () => {
    const d = computeStockDeltas(mk([['NVDA', 50]]), mk([['AAPL', 80]]));
    expect(d.get('NVDA')).toBeUndefined();
  });
});
