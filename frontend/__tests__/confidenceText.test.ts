import { confidenceTier, confidenceTone, type ConfidenceTier } from '@/lib/confidenceText';

describe('confidenceTier', () => {
  it('returns "high" for confidence >= 70', () => {
    expect(confidenceTier(70)).toBe('high');
    expect(confidenceTier(100)).toBe('high');
  });

  it('returns "moderate" (not "medium") for confidence 50-69', () => {
    expect(confidenceTier(50)).toBe('moderate');
    expect(confidenceTier(69)).toBe('moderate');
    expect(confidenceTier(55)).toBe('moderate');
  });

  it('returns "low" for confidence < 50', () => {
    expect(confidenceTier(49)).toBe('low');
    expect(confidenceTier(0)).toBe('low');
  });

  it('returns "unknown" for null/undefined', () => {
    expect(confidenceTier(null)).toBe('unknown');
    expect(confidenceTier(undefined)).toBe('unknown');
  });
});

describe('confidenceTone', () => {
  it('returns "caution" for moderate tier', () => {
    expect(confidenceTone('moderate')).toBe('caution');
  });
});
