/**
 * The one frontend copy of the shortlist-cap reason prefix.
 *
 * Both scans (options `backend/app/routers/scan.py`, stocks
 * `backend/app/routers/stock_scan.py`) rank every candidate and cut the list at
 * the shortlist cap; names ranked below the cap passed every gate and are
 * appended to `rejected` with a reason starting with this prefix. Both backend
 * `_SHORTLIST_REASON_PREFIX` constants must equal it —
 * backend/tests/test_stock_shortlist.py reads this file to pin all three, and
 * fails if any other frontend source file spells the literal itself.
 */
export const SHORTLIST_REASON_PREFIX = 'Shortlist cap:';
