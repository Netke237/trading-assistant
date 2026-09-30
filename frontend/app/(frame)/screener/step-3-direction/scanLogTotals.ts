import type { ScanResult, RejectedEntry } from '@/lib/scanStore';
import { SHORTLIST_REASON_PREFIX } from '@/lib/shortlistCap';

/** Mirrors `_SHORTLIST_REASON_PREFIX` in backend/app/routers/scan.py; one
 *  source (lib/shortlistCap.ts) shared with the stock scan. */
export { SHORTLIST_REASON_PREFIX };

/**
 * The four numbers in the Step-3 SCAN LOG header, derived together.
 *
 * They are computed in one place because the bugs here have all been
 * DISAGREEMENTS between them, not wrong values individually:
 *
 *  - Deriving `scanned` as passed + rejected undercounts whenever the shortlist
 *    cap trims, which put "Scanned 508" beside the funnel's "Universe 518".
 *  - Reading `rejected` from the store field alone reported "Rejected 0" after
 *    a reload, because RunScanButton's `rejectedLog` is not persisted while the
 *    identical `scanResult.rejected` is.
 *  - Gating only SOME of them on scan state produced "Scanned 5" above
 *    "Universe 518" mid-scan: RunScanButton clears `rejectedLog` when a scan
 *    starts and when one fails, but never clears `scanResult`.
 *
 * So: one `shownResult`, gated once, feeds every number and the funnel.
 */
export interface ScanLogTotals {
  /** The result every number in the panel — and the funnel — must read. */
  shownResult: ScanResult | undefined;
  rejectedLog: RejectedEntry[];
  totalPassed: number;
  totalRejected: number;
  totalScanned: number;
  /** Trimmed candidates: not returned, and not counted in `totalRejected`.
   *  The options scan does LIST them in `rejected` (reason prefix SHORTLIST_REASON_PREFIX),
   *  but `totalRejected` filters them out, so this is still exactly the amount
   *  by which the three headline numbers fail to sum. */
  totalTrimmed: number;
}

export function scanLogTotals(
  scanState: string | undefined,
  liveRejectedLog: RejectedEntry[],
  scanResult: ScanResult | null | undefined,
): ScanLogTotals {
  const resultIsCurrent = scanState === 'COMPLETED' || scanState === 'PARTIAL';
  const shownResult = resultIsCurrent ? scanResult ?? undefined : undefined;

  const rejectedLog = liveRejectedLog.length > 0
    ? liveRejectedLog
    : (shownResult?.rejected ?? []);
  const totalPassed = shownResult?.candidates?.length ?? 0;
  // The options scan lists names trimmed by the shortlist cap in `rejected`
  // (reason prefix SHORTLIST_REASON_PREFIX, backend `_SHORTLIST_REASON_PREFIX`) so they
  // stay visible in the log below. They were not rejected, though: they count
  // toward "Over cap", not toward "Rejected".
  const totalRejected = rejectedLog.filter((e) => !e.reason.startsWith(SHORTLIST_REASON_PREFIX)).length;
  const totalScanned = shownResult?.pipeline?.scanned ?? totalPassed + totalRejected;
  const totalTrimmed = Math.max(0, totalScanned - totalPassed - totalRejected);

  return { shownResult, rejectedLog, totalPassed, totalRejected, totalScanned, totalTrimmed };
}
