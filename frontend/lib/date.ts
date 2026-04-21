/*
 * DTE and event-proximity helpers.
 *
 * DTE progress — spec §Portfolio (Screen 5). Drift log G6.
 * EventFlag color ranges — spec §5 EVENT FLAG.
 */

export function dteFillPct(daysRemaining: number, totalDays: number): number {
  if (totalDays <= 0) return 0;
  const pct = (daysRemaining / totalDays) * 100;
  return Math.max(0, Math.min(100, pct));
}

/*
 * DTE status from remaining days (for the progress-bar color).
 * Spec says: full=pass, ~50%=caution, <20%=reject. We anchor on the
 * percentage so it matches whatever the contract's original DTE was.
 */
export function dteStatus(daysRemaining: number, totalDays: number): 'PASS' | 'CAUTION' | 'REJECT' {
  const pct = dteFillPct(daysRemaining, totalDays);
  if (pct >= 50) return 'PASS';
  if (pct >= 20) return 'CAUTION';
  return 'REJECT';
}

/*
 * EventFlag proximity color — spec §5 EVENT FLAG.
 * > 7 days: dim | ≤ 7 days: caution | ≤ 3 days: reject.
 */
export type EventProximity = 'distant' | 'near' | 'imminent';

export function eventProximity(days: number): EventProximity {
  if (days <= 3) return 'imminent';
  if (days <= 7) return 'near';
  return 'distant';
}
