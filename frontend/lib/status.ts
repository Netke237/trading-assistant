/*
 * Status — the canonical classification used for rows, badges, scores.
 *
 * Drift log Screen 1 #5: the ONLY allowed labels are exactly these. Do not
 * invent "LONG" / "SHORT" / "Active" — those are different concepts (direction,
 * position state) and belong in their own types.
 */

import type { DataTone } from '@/components/primitives/Data';

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

/**
 * Shared 0–100 band for composite scores (55/35). `statusForScore` derives its
 * thresholds from this so the band has exactly one source of truth in this file.
 */
export const SCORE_BAND = { passAt: 55, cautionAt: 35 } as const;

/**
 * Fundamentals health deliberately uses a STRICTER band than composite scores
 * (65/40 vs 55/35): a mediocre balance sheet deserves a louder caution signal
 * than a mediocre trend score. Mirrors backend/app/scoring/fundamentals_scorer.py
 * — see also fundamentalScoreTooltip's strong/middling/weak vocabulary.
 */
export const FUNDAMENTAL_BAND = { passAt: 65, cautionAt: 40 } as const;

export function statusForScore(value: number, max = 100): Status {
  const pct = (value / max) * 100;
  if (pct >= SCORE_BAND.passAt) return 'PASS';
  if (pct >= SCORE_BAND.cautionAt) return 'CAUTION';
  return 'REJECT';
}

/**
 * Raw 0–100 score → Data tone, with the band thresholds as the single source
 * of truth. `band` defaults to SCORE_BAND; pass FUNDAMENTAL_BAND for the
 * stricter fundamentals-health band.
 */
export function toneForScore(
  value: number,
  band: { passAt: number; cautionAt: number } = SCORE_BAND,
): DataTone {
  if (value >= band.passAt) return 'pass';
  if (value >= band.cautionAt) return 'caution';
  return 'reject';
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

/**
 * Maps a Status to a Data-primitive tone. DataTone has no PENDING/NO_DATA
 * slot, so both map to 'dim' (the established "unknown/inactive" tone) —
 * an exhaustive Record so a future Status addition fails to compile here
 * instead of silently falling through to `undefined`.
 */
const STATUS_TONE: Record<Status, DataTone> = {
  PASS: 'pass',
  CAUTION: 'caution',
  REJECT: 'reject',
  PENDING: 'dim',
  NO_DATA: 'dim',
};

export function toneForStatus(status: Status): DataTone {
  return STATUS_TONE[status];
}
