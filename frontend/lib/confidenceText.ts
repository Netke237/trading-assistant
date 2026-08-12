import type { DataTone } from '@/components/primitives';

// Mirrors backend/config/scoring_rules.yaml's confidence_gate
// (cautionBelow: 50, rejectBelow: 35), consumed by status_cap() in
// backend/app/scoring/signal_confidence.py.
export type ConfidenceTier = 'unknown' | 'low' | 'moderate' | 'high';

export function confidenceTier(confidence: number | null | undefined): ConfidenceTier {
  if (confidence === null || confidence === undefined) return 'unknown';
  if (confidence >= 50) return 'high';
  if (confidence >= 35) return 'moderate';
  return 'low';
}

export function confidenceTone(tier: ConfidenceTier): DataTone {
  switch (tier) {
    case 'high':     return 'pass';
    case 'moderate': return 'caution';
    case 'low':      return 'reject';
    default:         return 'dim';
  }
}
