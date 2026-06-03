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
  };
}
