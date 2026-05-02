import { statusForScore } from '@/lib/status';

describe('statusForScore', () => {
  it('returns PASS for score >= 70', () => {
    expect(statusForScore(70)).toBe('PASS');
    expect(statusForScore(100)).toBe('PASS');
    expect(statusForScore(82)).toBe('PASS');
  });

  it('returns CAUTION for score 50–69', () => {
    expect(statusForScore(50)).toBe('CAUTION');
    expect(statusForScore(69)).toBe('CAUTION');
    expect(statusForScore(61)).toBe('CAUTION');
  });

  it('returns REJECT for score < 50', () => {
    expect(statusForScore(0)).toBe('REJECT');
    expect(statusForScore(49)).toBe('REJECT');
    expect(statusForScore(42)).toBe('REJECT');
  });
});
