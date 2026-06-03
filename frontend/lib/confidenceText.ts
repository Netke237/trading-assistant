import type { DataTone } from '@/components/primitives';

export type ConfidenceTier = 'unknown' | 'low' | 'medium' | 'high';

export function confidenceTier(confidence: number | null | undefined): ConfidenceTier {
  if (confidence === null || confidence === undefined) return 'unknown';
  if (confidence >= 70) return 'high';
  if (confidence >= 50) return 'medium';
  return 'low';
}

export function confidenceTone(tier: ConfidenceTier): DataTone {
  switch (tier) {
    case 'high':
      return 'pass';
    case 'medium':
      return 'caution';
    case 'low':
      return 'reject';
    default:
      return 'dim';
  }
}
