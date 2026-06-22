/*
 * Status — the canonical classification used for rows, badges, scores.
 *
 * Drift log Screen 1 #5: the ONLY allowed labels are exactly these. Do not
 * invent "LONG" / "SHORT" / "Active" — those are different concepts (direction,
 * position state) and belong in their own types.
 */

export type Status = 'PASS' | 'CAUTION' | 'REJECT' | 'PENDING' | 'NO_DATA';

export const STATUS_LABEL: Record<Status, string> = {
  PASS: 'PASS',
  CAUTION: 'CAUTION',
  REJECT: 'REJECT',
  PENDING: 'PENDING',
  NO_DATA: 'NO DATA',
};

/*
 * ScoreBar fill rule — spec §5 SCORE BAR. Drift log G5.
 * Input: percentage-like value (0–100).
 * Output: which status color to paint the fill.
 */
export function statusForScore(value: number, max = 100): Status {
  const pct = (value / max) * 100;
  if (pct >= 55) return 'PASS';
  if (pct >= 35) return 'CAUTION';
  return 'REJECT';
}

/**
 * Returns the "worst" (most restrictive) status from a list.
 * Priority: REJECT > CAUTION > PENDING > PASS > NO_DATA
 */
export function worstStatus(...statuses: Status[]): Status {
  if (statuses.includes('REJECT')) return 'REJECT';
  if (statuses.includes('CAUTION')) return 'CAUTION';
  if (statuses.includes('PENDING')) return 'PENDING';
  if (statuses.includes('PASS')) return 'PASS';
  return 'NO_DATA';
}
