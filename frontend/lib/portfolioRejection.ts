/** The Portfolio page's rendering of a refused save (`lastSyncError.detail`).
 *
 *  Lives in lib/, not in `app/(frame)/portfolio/page.tsx`, so it can be unit-
 *  tested: an App Router page may not carry extra named exports.
 *
 *  STOP-SEMANTICS-2026-10-02 -- a PATCH 422 detail is ` | `-joined SEGMENTS
 *  (backend `routers/portfolio.py` `update_position`): the qty error verbatim
 *  (space-joined risk codes OR free text), then `premium_stop_below_one_cent`,
 *  then `qty_saved_as_<N>` when a trimmed qty WAS saved. Each segment is mapped
 *  on its own, so neither refusal can hide the other and free text is never
 *  swallowed. A single segment is exactly the pre-STOP-SEMANTICS detail and
 *  renders as it always did. */

export const REJECTION_LABELS: Record<string, string> = {
  single_trade_exposure_too_high: 'This trade is too large for your account size (over the single-trade limit). Raise your account value in Settings or reduce size.',
  size_reduced_to_fit_exposure_limit: 'This trade is too large for your account size (over the single-trade limit). Raise your account value in Settings or reduce size.',
  total_exposure_limit_reached: 'Adding this would exceed your total portfolio exposure limit.',
  max_concurrent_positions_reached: 'You are at your maximum number of open positions.',
  daily_recommendation_limit_reached: 'You have reached the maximum number of new positions for today.',
  duplicate_symbol_already_open: 'You already have an open position on this symbol.',
  portfolio_too_small: 'Your configured account value is below the minimum required.',
  premium_stop_below_one_cent: 'Premium stop not saved: at this entry it would fire below $0.01 and could never fire.',
};

const SEGMENT_SEPARATOR = ' | ';
// Exact prefix, digits only: `qty_saved_as_x` and `xqty_saved_as_3` are not it.
const QTY_SAVED = /^qty_saved_as_(\d+)$/;
// A stored added fill the cap would have resized. The amount stays visible;
// nothing in this string is a quantity that was cut down.
const EXPOSURE_BREACH = /^exposure_breach:\s*(.*?);\s*combined exposure\s+(\S+)\s*$/;

/** Map one segment: a `qty_saved_as_<N>` code, an added-fill exposure warning,
 *  else its space-split tokens through REJECTION_LABELS, else the raw segment. */
function segmentMessage(segment: string): string {
  const saved = QTY_SAVED.exec(segment);
  if (saved) return `Quantity saved as ${saved[1]} (reduced to fit exposure).`;
  const breach = EXPOSURE_BREACH.exec(segment);
  if (breach) {
    const reasons = [...new Set(
      breach[1].split(/\s+/).map((code) => REJECTION_LABELS[code]).filter(Boolean),
    )];
    const why = reasons.length ? reasons.join(' ') : breach[1];
    return `${why} Combined exposure ${breach[2]}. The full fill was recorded.`;
  }
  const mapped = segment
    .split(' ')
    .map((code) => REJECTION_LABELS[code])
    .filter(Boolean);
  return mapped.length ? mapped.join(' ') : segment;
}

export function rejectionMessage(detail: string): string {
  return detail.split(SEGMENT_SEPARATOR).map(segmentMessage).join(' ');
}

/** True when every segment is a refusal that left the rest of the PATCH saved
 *  (the premium code, or the trimmed qty that was saved) -- the banner then
 *  says "some changes were not saved" instead of "was not saved". */
export function isPartialSave(detail: string): boolean {
  return detail
    .split(SEGMENT_SEPARATOR)
    .every((seg) => seg === 'premium_stop_below_one_cent' || QTY_SAVED.test(seg));
}
