import { alignmentVerdict } from '@/lib/regimeAlignment';

describe('alignmentVerdict', () => {
  it('PASS when direction agrees with descriptor', () => {
    expect(alignmentVerdict('Bullish', 'Bull')).toBe('PASS');
    expect(alignmentVerdict('Bearish', 'Bear')).toBe('PASS');
  });
  it('REJECT when direction opposes descriptor', () => {
    expect(alignmentVerdict('Bearish', 'Bull')).toBe('REJECT');
    expect(alignmentVerdict('Bullish', 'Bear')).toBe('REJECT');
  });
  it('CAUTION on choppy regardless of direction', () => {
    expect(alignmentVerdict('Bullish', 'Choppy')).toBe('CAUTION');
    expect(alignmentVerdict('Bearish', 'Choppy')).toBe('CAUTION');
  });
});
