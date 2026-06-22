import { statusForScore } from '@/lib/status';

describe('statusForScore', () => {
  it('returns PASS for score >= 55', () => {
    expect(statusForScore(55)).toBe('PASS');
    expect(statusForScore(60)).toBe('PASS');
    expect(statusForScore(100)).toBe('PASS');
  });

  it('returns CAUTION for score 35–54', () => {
    expect(statusForScore(35)).toBe('CAUTION');
    expect(statusForScore(54)).toBe('CAUTION');
  });

  it('returns REJECT for score < 35', () => {
    expect(statusForScore(0)).toBe('REJECT');
    expect(statusForScore(34)).toBe('REJECT');
  });

  it('respects max parameter — percentage is computed then compared', () => {
    // (55 / 200) * 100 = 27.5% → REJECT (< 35)
    expect(statusForScore(55, 200)).toBe('REJECT');
    // (110 / 200) * 100 = 55% → PASS (>= 55)
    expect(statusForScore(110, 200)).toBe('PASS');
  });
});
