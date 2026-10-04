/**
 * Audit round 1, F4 (Kenneth 2026-10-03: age it client-side) and F8.
 *
 * `earningsDays` and `earningsVeto` are computed by the backend ONCE, at scan
 * time, against that day's date. The scan result is persisted (scanStore
 * `partialize`), so a card reopened on a later day still carried Monday's
 * distance: a Swing card with earnings 23 days out on Monday (outside the
 * 21-day reject window) still read "23 days" on Thursday, when the print was
 * 20 days out and INSIDE the window, and Place Limit sent it.
 *
 * This ages the distance by the scan's age in WHOLE CALENDAR DAYS
 * (`earningsDays - daysSinceScan`) and judges it against the same window the
 * scan applied (`scanResult.event_window`). Step 7's buttons and its
 * `@contextRail` checklist both read this one helper, so the two cannot
 * disagree on a card.
 *
 *  - aged distance < 0: the print may already have passed, so the NEXT date is
 *    unknown -- `unknown` (D4: a single stock is CAUTION and cannot be armed).
 *  - aged distance < reject_days: `veto` (no send, no pin, no arm, no fire).
 *  - a card the backend already vetoed stays vetoed unless its aged distance
 *    went negative (then it is unknown, above): ageing only shortens the
 *    distance, so it can never clear a veto on its own.
 *
 * NOT COVERED (stated, Phase B): this guards Step 7 only. The backend's own
 * send paths (`POST /api/portfolio`, `/broker/option-order`) do not re-check
 * earnings against today; only the auto-trade fire does (`_apply_event_veto`).
 */
import type { TradeCardData } from '@/types/domain';

/** The sentence every vetoed control on Step 7 carries. */
export const EARNINGS_VETO_MESSAGE = 'Earnings inside the reject window — no send';
/** F8 — why a single stock with no known earnings date cannot be armed: the
 *  auto-trader's own fire-time lookup would refuse every fire of it. */
export const EARNINGS_UNKNOWN_ARM_MESSAGE =
  'Earnings date unknown — auto-trade will not fire a single stock; send it manually after checking the calendar';

const MS_PER_DAY = 86_400_000;

/** Whole calendar days from the scan's LOCAL date to today's local date.
 *  0 when the timestamp is missing or unreadable (nothing to age by). Never
 *  negative: a clock behind the scan does not lengthen the distance. */
export function daysSinceScan(scanTimestamp: string | null | undefined, now: Date = new Date()): number {
  if (!scanTimestamp) return 0;
  const scanned = new Date(scanTimestamp);
  if (Number.isNaN(scanned.getTime())) return 0;
  const startOf = (d: Date) => Date.UTC(d.getFullYear(), d.getMonth(), d.getDate());
  return Math.max(0, Math.round((startOf(now) - startOf(scanned)) / MS_PER_DAY));
}

export interface EarningsGate {
  /** Days to earnings as of TODAY (scan value minus the scan's age), or null
   *  when no date is known (including when it aged below zero). */
  daysNow: number | null;
  /** The scan-time value, for display beside an aged one. */
  daysAtScan: number | null;
  /** Calendar days since the scan. */
  ageDays: number;
  /** Earnings inside the reject window as of today: no send, pin, arm or fire. */
  veto: boolean;
  /** No known next date: the card says so, or the aged distance went below 0. */
  unknown: boolean;
  /** True only when the aged distance went below zero. */
  passedSinceScan: boolean;
  /** Why the Arm (and Fire now) must be refused, or null. A veto, or (F8) an
   *  unknown date on a single stock. An ETF with an unknown date may be armed. */
  armBlockedReason: string | null;
}

export function earningsGateFor(
  card: Pick<TradeCardData, 'earningsDays' | 'earningsVeto' | 'earningsUnknown' | 'isEtf'> | null | undefined,
  scanTimestamp: string | null | undefined,
  rejectDays: number | null | undefined,
  now: Date = new Date(),
): EarningsGate {
  const ageDays = daysSinceScan(scanTimestamp, now);
  const daysAtScan = card?.earningsDays ?? null;
  const aged = daysAtScan != null ? daysAtScan - ageDays : null;
  const passedSinceScan = aged != null && aged < 0;
  const daysNow = aged != null && aged >= 0 ? aged : null;
  const unknown = card?.earningsUnknown === true || passedSinceScan;
  const veto = !passedSinceScan && (
    card?.earningsVeto === true
    || (daysNow != null && rejectDays != null && daysNow < rejectDays)
  );
  const armBlockedReason = veto ? EARNINGS_VETO_MESSAGE
    : unknown && card?.isEtf !== true ? EARNINGS_UNKNOWN_ARM_MESSAGE
    : null;
  return { daysNow, daysAtScan, ageDays, veto, unknown, passedSinceScan, armBlockedReason };
}
