import { MINUS, formatMoney, formatSignedPct, moneyTone, readableContract } from '../portfolioFormat';

// PORTFOLIO-NUMBERS T1 (#657): one money / percent / contract format for the
// Portfolio page and its rail.

describe('formatMoney', () => {
  it('uses U+2212 and puts $ after the sign', () => {
    const s = formatMoney(-564);
    expect(s).toBe('−$564');
    expect(s.charCodeAt(0)).toBe(0x2212);
    expect(MINUS).toBe('−');
  });

  it('adds + for positives only when asked', () => {
    expect(formatMoney(89, { plus: true })).toBe('+$89');
    expect(formatMoney(89)).toBe('$89');
  });

  it('prints $0 for anything that rounds to zero, never a signed zero', () => {
    expect(formatMoney(0, { plus: true })).toBe('$0');
    expect(formatMoney(-0, { plus: true })).toBe('$0');
    expect(formatMoney(-0.4, { plus: true })).toBe('$0');
    expect(formatMoney(0.4, { plus: true })).toBe('$0');
  });

  it('groups thousands in en-US', () => {
    expect(formatMoney(-2595)).toBe('−$2,595');
    expect(formatMoney(1234567, { plus: true })).toBe('+$1,234,567');
  });

  it('keeps Math.round semantics (half toward +infinity)', () => {
    expect(formatMoney(-44.5)).toBe('−$44');
  });

  it('prints 2 decimals when asked', () => {
    expect(formatMoney(-1.1, { decimals: 2 })).toBe('−$1.10');
    expect(formatMoney(-1.81, { decimals: 2 })).toBe('−$1.81');
    expect(formatMoney(0.004, { decimals: 2 })).toBe('$0.00');
  });

  it('prints — for a non-finite value', () => {
    expect(formatMoney(NaN)).toBe('—');
  });
});

describe('moneyTone', () => {
  it('follows the value as formatMoney rounds it', () => {
    expect(moneyTone(-0.004, 2)).toBeUndefined();
    expect(moneyTone(-0.006, 2)).toBe('reject');
    expect(moneyTone(0.02, 2)).toBe('pass');
    expect(moneyTone(-0.4)).toBeUndefined();
    expect(moneyTone(NaN)).toBeUndefined();
  });
});

describe('formatSignedPct', () => {
  it('signs with + and U+2212, 1 decimal by default', () => {
    expect(formatSignedPct(-18.26)).toBe('−18.3%');
    expect(formatSignedPct(4.48)).toBe('+4.5%');
    expect(formatSignedPct(-6.968)).toBe('−7.0%');
    expect(formatSignedPct(20)).toBe('+20.0%');
    expect(formatSignedPct(-10)).toBe('−10.0%');
  });

  it('prints an unsigned zero when it rounds to zero', () => {
    expect(formatSignedPct(-0.04)).toBe('0.0%');
  });

  it('prints — for a non-finite value', () => {
    expect(formatSignedPct(Infinity)).toBe('—');
  });
});

describe('readableContract', () => {
  it('formats an option key as strike+right · day month year', () => {
    expect(readableContract('CMG|40|2027-06-17|C')).toBe('40C · 17 Jun 27');
    expect(readableContract('BMY|187.5|2027-03-05|P')).toBe('187.5P · 5 Mar 27');
  });

  it('formats a stock key as Stock', () => {
    expect(readableContract('BA|STOCK')).toBe('Stock');
  });

  it('returns an unreadable key unchanged', () => {
    expect(readableContract('garbage')).toBe('garbage');
    expect(readableContract('AAPL|185|2027-13-15|C')).toBe('AAPL|185|2027-13-15|C');
  });
});
