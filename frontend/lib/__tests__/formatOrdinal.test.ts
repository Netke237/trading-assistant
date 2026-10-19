import { ordinalSuffix, formatOrdinal } from '../formatOrdinal';

describe('formatOrdinal & ordinalSuffix', () => {
  describe('ordinalSuffix', () => {
    it('returns "th" for 0', () => {
      expect(ordinalSuffix(0)).toBe('th');
    });

    it('returns "st", "nd", "rd" for 1, 2, 3', () => {
      expect(ordinalSuffix(1)).toBe('st');
      expect(ordinalSuffix(2)).toBe('nd');
      expect(ordinalSuffix(3)).toBe('rd');
    });

    it('returns "th" for 4 through 10', () => {
      for (let i = 4; i <= 10; i++) {
        expect(ordinalSuffix(i)).toBe('th');
      }
    });

    it('returns "th" for teens 11, 12, 13', () => {
      expect(ordinalSuffix(11)).toBe('th');
      expect(ordinalSuffix(12)).toBe('th');
      expect(ordinalSuffix(13)).toBe('th');
    });

    it('returns correct suffixes for 20 through 24', () => {
      expect(ordinalSuffix(20)).toBe('th');
      expect(ordinalSuffix(21)).toBe('st');
      expect(ordinalSuffix(22)).toBe('nd');
      expect(ordinalSuffix(23)).toBe('rd');
      expect(ordinalSuffix(24)).toBe('th');
    });

    it('returns correct suffixes for 100, 101, 102, 103, 111, 112, 113, 121', () => {
      expect(ordinalSuffix(100)).toBe('th');
      expect(ordinalSuffix(101)).toBe('st');
      expect(ordinalSuffix(102)).toBe('nd');
      expect(ordinalSuffix(103)).toBe('rd');
      expect(ordinalSuffix(111)).toBe('th');
      expect(ordinalSuffix(112)).toBe('th');
      expect(ordinalSuffix(113)).toBe('th');
      expect(ordinalSuffix(121)).toBe('st');
      expect(ordinalSuffix(122)).toBe('nd');
      expect(ordinalSuffix(123)).toBe('rd');
    });

    it('handles negative integers by magnitude', () => {
      expect(ordinalSuffix(-1)).toBe('st');
      expect(ordinalSuffix(-2)).toBe('nd');
      expect(ordinalSuffix(-3)).toBe('rd');
      expect(ordinalSuffix(-4)).toBe('th');
      expect(ordinalSuffix(-11)).toBe('th');
      expect(ordinalSuffix(-12)).toBe('th');
      expect(ordinalSuffix(-13)).toBe('th');
      expect(ordinalSuffix(-21)).toBe('st');
    });

    it('returns empty string for non-finite numbers', () => {
      expect(ordinalSuffix(NaN)).toBe('');
      expect(ordinalSuffix(Infinity)).toBe('');
      expect(ordinalSuffix(-Infinity)).toBe('');
    });
  });

  describe('formatOrdinal', () => {
    it('formats 0 through 10', () => {
      expect(formatOrdinal(0)).toBe('0th');
      expect(formatOrdinal(1)).toBe('1st');
      expect(formatOrdinal(2)).toBe('2nd');
      expect(formatOrdinal(3)).toBe('3rd');
      expect(formatOrdinal(4)).toBe('4th');
      expect(formatOrdinal(5)).toBe('5th');
      expect(formatOrdinal(10)).toBe('10th');
    });

    it('formats teens 11 through 14', () => {
      expect(formatOrdinal(11)).toBe('11th');
      expect(formatOrdinal(12)).toBe('12th');
      expect(formatOrdinal(13)).toBe('13th');
      expect(formatOrdinal(14)).toBe('14th');
    });

    it('formats decimal numbers by rounding', () => {
      expect(formatOrdinal(2.7)).toBe('3rd');
      expect(formatOrdinal(0.2)).toBe('0th');
      expect(formatOrdinal(0.8)).toBe('1st');
      expect(formatOrdinal(1.4)).toBe('1st');
      expect(formatOrdinal(1.5)).toBe('2nd');
      expect(formatOrdinal(20.9)).toBe('21st');
      expect(formatOrdinal(22.1)).toBe('22nd');
      expect(formatOrdinal(22.8)).toBe('23rd');
      expect(formatOrdinal(99.6)).toBe('100th');
    });

    it('formats larger numbers', () => {
      expect(formatOrdinal(50)).toBe('50th');
      expect(formatOrdinal(100)).toBe('100th');
      expect(formatOrdinal(101)).toBe('101st');
      expect(formatOrdinal(111)).toBe('111th');
      expect(formatOrdinal(112)).toBe('112th');
      expect(formatOrdinal(113)).toBe('113th');
      expect(formatOrdinal(121)).toBe('121st');
    });

    it('returns empty string for non-finite values', () => {
      expect(formatOrdinal(NaN)).toBe('');
      expect(formatOrdinal(Infinity)).toBe('');
      expect(formatOrdinal(-Infinity)).toBe('');
    });
  });
});
