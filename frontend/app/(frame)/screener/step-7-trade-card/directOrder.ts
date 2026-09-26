/*
 * Step 7's direct-send helpers. The shared ones moved to `@/lib/directOrder`
 * (STOCK-SENDS-SAVE-FIRST-THEN-REAL-SHARES) and are re-exported here; only the
 * options-card label stays, as it needs `TradeCardData`.
 */

import { contractLabel, type TradeCardData } from '@/types/domain';

export * from '@/lib/directOrder';

/** The human contract label every direct-send message carries, so a result
 *  that lands after Prev/Next is still true on whichever card is showing. */
export function contractLabelFor(card: TradeCardData): string {
  const cd = card.contractDetails;
  if (cd?.strike != null && cd.expiry && cd.right) {
    return contractLabel({ symbol: card.symbol, strike: cd.strike, right: cd.right, expiry: cd.expiry });
  }
  return card.contract;
}
