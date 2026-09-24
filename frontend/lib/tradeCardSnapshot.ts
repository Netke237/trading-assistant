import type { TradeCardData } from '@/types/domain';

// The "why was this bought" snapshot — attached to the position once, at buy
// time, so it survives independent of later scans overwriting scanStore.
//
// Module-level and shared (O4 step 6): Step 7's send paths and AutoTradeArm's
// arm request both call THIS function, so a card that is sent and a card that
// is armed record the same snapshot.
export function tradeCardSnapshotOf(card: TradeCardData): Record<string, unknown> {
  return {
    stockScore: card.stockScore,
    stockConfidence: card.stockConfidence,
    stockBreakdown: card.stockBreakdown,
    contractScore: card.contractScore,
    contractConfidence: card.contractConfidence,
    contractBreakdown: card.contractBreakdown,
    rrRatio: card.rrRatio,
    rrModel: card.rrModel,
    strike: card.contractDetails?.strike ?? null,
  };
}
