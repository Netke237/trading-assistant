import type { StockScanResult } from '@/types/stockDomain';

export interface StockDelta {
  scoreDelta: number;  // current score − previous score
  rankDelta:  number;  // positive = moved up (lower index) vs previous
}

/**
 * Build a symbol → delta map comparing the current run to the previous run.
 * Rank is the candidate's index in each run: the backend returns candidates
 * ranked (status PASS before CAUTION, then score desc, then confidence desc —
 * the order the shortlist cap cuts by). Symbols absent from the previous run
 * get no entry.
 */
export function computeStockDeltas(
  current: StockScanResult,
  previous: StockScanResult | null,
): Map<string, StockDelta> {
  const out = new Map<string, StockDelta>();
  if (!previous) return out;

  const prevRank  = new Map<string, number>();
  const prevScore = new Map<string, number>();
  previous.candidates.forEach((c, i) => {
    prevRank.set(c.symbol, i);
    prevScore.set(c.symbol, c.stock_score);
  });

  current.candidates.forEach((c, i) => {
    if (!prevRank.has(c.symbol)) return;
    out.set(c.symbol, {
      scoreDelta: c.stock_score - (prevScore.get(c.symbol) ?? c.stock_score),
      rankDelta:  (prevRank.get(c.symbol) ?? i) - i,
    });
  });

  return out;
}
