import { SHORTLIST_REASON_PREFIX } from '@/lib/shortlistCap';

/**
 * Stock-scan `rejected` entries that are NOT rejections.
 *
 * The backend ranks every candidate (status, then score, then confidence) and
 * cuts the list at the shortlist cap. Names ranked below the cap passed every
 * gate; they are appended to `rejected` with this reason prefix so they are
 * visible, but counting them as "rejected" would misstate what the gates did.
 * The value lives in lib/shortlistCap.ts, shared with the options scan log
 * (backend/tests/test_stock_shortlist.py pins it against both backends).
 */
export const STOCK_SHORTLIST_REASON_PREFIX = SHORTLIST_REASON_PREFIX;

export interface StockRejectedEntry { symbol: string; reason: string }

export function splitStockRejected<T extends StockRejectedEntry>(
  rejected: readonly T[] | null | undefined,
): { rejected: T[]; overCap: T[] } {
  const out = { rejected: [] as T[], overCap: [] as T[] };
  for (const r of rejected ?? []) {
    (typeof r.reason === 'string' && r.reason.startsWith(STOCK_SHORTLIST_REASON_PREFIX)
      ? out.overCap : out.rejected).push(r);
  }
  return out;
}
