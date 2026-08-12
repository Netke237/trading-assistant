import { confidenceTier, confidenceTone } from '@/lib/confidenceText';

// Mirrors backend/config/scoring_rules.yaml's confidence_gate
// (cautionBelow: 50, rejectBelow: 35).
describe('confidenceTier', () => {
  it('returns "high" for confidence >= 50', () => {
    expect(confidenceTier(50)).toBe('high');
    expect(confidenceTier(100)).toBe('high');
  });

  it('returns "moderate" (not "medium") for confidence 35-49', () => {
    expect(confidenceTier(35)).toBe('moderate');
    expect(confidenceTier(49)).toBe('moderate');
    expect(confidenceTier(40)).toBe('moderate');
  });

  it('returns "low" for confidence < 35', () => {
    expect(confidenceTier(34)).toBe('low');
    expect(confidenceTier(0)).toBe('low');
  });

  it('returns "unknown" for null/undefined', () => {
    expect(confidenceTier(null)).toBe('unknown');
    expect(confidenceTier(undefined)).toBe('unknown');
  });
});

describe('confidenceTone', () => {
  it('returns "pass" for high tier', () => {
    expect(confidenceTone('high')).toBe('pass');
  });

  it('returns "caution" for moderate tier', () => {
    expect(confidenceTone('moderate')).toBe('caution');
  });

  it('returns "reject" for low tier', () => {
    expect(confidenceTone('low')).toBe('reject');
  });

  it('returns "dim" for unknown tier', () => {
    expect(confidenceTone('unknown')).toBe('dim');
  });
});
