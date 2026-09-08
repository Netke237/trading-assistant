import type { WatchlistRow, TradeCardData, Horizon } from '@/types/domain';
import type { ScanResult } from '@/lib/scanStore';

function parseHorizon(h: string | undefined): Horizon {
  if (!h) return 'Swing';
  if (h.startsWith('Intraday')) return 'Intraday';
  if (h.startsWith('Swing')) return 'Swing';
  if (h.startsWith('Position')) return 'Position';
  if (h.startsWith('Custom')) return 'Custom';
  return 'Swing';
}

export function cardToRow(
  c: TradeCardData,
  newRank: number,
  previousRun: ScanResult | null = null,
  contextHorizon: string | undefined = undefined,
): WatchlistRow {
  let rankDelta = 0;
  let scoreDelta = 0;

  if (previousRun) {
    const prevIndex = previousRun.candidates.findIndex((p) => p.symbol === c.symbol);
    if (prevIndex !== -1) {
      const oldRank = prevIndex + 1;
      rankDelta = oldRank - newRank;
      scoreDelta = c.stockScore - previousRun.candidates[prevIndex].stockScore;
    }
  }

  return {
    symbol: c.symbol,
    company: c.company,
    price: c.price,
    direction: c.direction,
    horizon: parseHorizon(contextHorizon),
    score: c.stockScore,
    rankDelta,
    scoreDelta,
    status: c.status,
    breakdown: c.stockBreakdown,
    nextEventDays: c.nextEventDays,
    nextEventLabel: c.nextEventLabel,
    confidence: c.confidence ?? null,
    confidenceText: c.confidenceText ?? null,
    // Phase B3. Copied, never derived: the verdict was reached server-side
    // against a stop this table does not have. `?? null` collapses `undefined`
    // (a candidate from a scan session persisted before B3) onto the same
    // "not computed" the backend sends for an unpriceable contract — the row
    // renders one state for both, because there is nothing a user could do
    // differently about them.
    stopCostPct: c.stopCostPct ?? null,
    stopCostStatus: c.stopCostStatus ?? null,
  };
}
