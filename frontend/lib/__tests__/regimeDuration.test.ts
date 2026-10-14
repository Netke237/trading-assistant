import { formatRegimeAge, formatRegimeAverage } from '@/lib/regimeDuration';

describe('formatRegimeAge', () => {
  it('labels age 40 as bars, not days', () => {
    const text = formatRegimeAge(40);
    expect(text).toBe('40 bars');
    expect(text).not.toContain('Day');
    expect(text).not.toContain('days');
  });
});

describe('formatRegimeAverage', () => {
  it('shows the stride size only for an integer stride of at least 1', () => {
    expect(formatRegimeAverage(5, 20)).toBe('≈5 strides of 20 bars');
    expect(formatRegimeAverage(5, 26)).toContain('of 26 bars');
    expect(formatRegimeAverage(5, 50)).toContain('of 50 bars');
  });

  it('keeps 5.4 instead of rounding it to 5', () => {
    expect(formatRegimeAverage(5.4, 26)).toBe('≈5.4 strides of 26 bars');
    expect(formatRegimeAverage(5.4)).not.toBe('≈5 strides');
  });

  it('omits the size when the stride is absent, null, zero, or not an integer', () => {
    for (const stride of [undefined, null, 0, 1.5] as const) {
      const text = formatRegimeAverage(5, stride);
      expect(text).toBe('≈5 strides');
      expect(text).not.toContain('day');
      expect(text).not.toContain('of');
    }
  });

  it('keeps a one-decimal average and strips a trailing .0', () => {
    expect(formatRegimeAverage(31.5)).toBe('≈31.5 strides');
    expect(formatRegimeAverage(0)).toBe('≈0 strides');
  });

  it('returns an empty string for a non-finite average', () => {
    expect(formatRegimeAverage(Number.NaN)).toBe('');
    expect(formatRegimeAverage(Number.POSITIVE_INFINITY)).toBe('');
    expect(formatRegimeAverage(Number.NEGATIVE_INFINITY, 20)).toBe('');
  });
});
