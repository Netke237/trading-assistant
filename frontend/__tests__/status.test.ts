import { statusForScore, toneForStatus, toneForScore, SCORE_BAND, FUNDAMENTAL_BAND } from '@/lib/status';
import type { Status } from '@/lib/status';

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

describe('toneForStatus', () => {
  const cases: [Status, string][] = [
    ['PASS', 'pass'],
    ['CAUTION', 'caution'],
    ['REJECT', 'reject'],
    ['PENDING', 'dim'],
    ['NO_DATA', 'dim'],
  ];

  it.each(cases)('maps %s to tone %s', (status, tone) => {
    expect(toneForStatus(status)).toBe(tone);
  });
});

describe('toneForScore', () => {
  it('uses the shared 55/35 band by default', () => {
    expect(toneForScore(55)).toBe('pass');
    expect(toneForScore(35)).toBe('caution');
    expect(toneForScore(34)).toBe('reject');
    expect(toneForScore(100)).toBe('pass');
    expect(toneForScore(0)).toBe('reject');
  });

  it('default band matches SCORE_BAND constants', () => {
    expect(toneForScore(SCORE_BAND.passAt)).toBe('pass');
    expect(toneForScore(SCORE_BAND.cautionAt)).toBe('caution');
    expect(toneForScore(SCORE_BAND.cautionAt - 1)).toBe('reject');
  });

  it('applies the stricter fundamentals band when passed', () => {
    expect(toneForScore(65, FUNDAMENTAL_BAND)).toBe('pass');
    expect(toneForScore(64, FUNDAMENTAL_BAND)).toBe('caution');
    expect(toneForScore(40, FUNDAMENTAL_BAND)).toBe('caution');
    expect(toneForScore(39, FUNDAMENTAL_BAND)).toBe('reject');
    // 60 passes the composite band but is only caution for fundamentals
    expect(toneForScore(60)).toBe('pass');
    expect(toneForScore(60, FUNDAMENTAL_BAND)).toBe('caution');
  });
});
