import { formatStockStopDistance, formatPremiumStopDistance } from '../stopDistance';

describe('formatStockStopDistance', () => {
  it('returns null for unset, zero, or non-finite stop prices', () => {
    expect(formatStockStopDistance(null, 50, 'Bullish')).toBeNull();
    expect(formatStockStopDistance(undefined, 50, 'Bullish')).toBeNull();
    expect(formatStockStopDistance(0, 50, 'Bullish')).toBeNull();
    expect(formatStockStopDistance(-10, 50, 'Bullish')).toBeNull();
    expect(formatStockStopDistance(NaN, 50, 'Bullish')).toBeNull();
    expect(formatStockStopDistance(Infinity, 50, 'Bullish')).toBeNull();
  });

  it('handles NULL, undefined, zero, or non-finite entryStockPrice (legacy rows)', () => {
    expect(formatStockStopDistance(46.60, null, 'Bullish')).toBe('$46.60 · — (not recorded)');
    expect(formatStockStopDistance(46.60, undefined, 'Bullish')).toBe('$46.60 · — (not recorded)');
    expect(formatStockStopDistance(46.60, 0, 'Bullish')).toBe('$46.60 · — (not recorded)');
    expect(formatStockStopDistance(46.60, NaN, 'Bullish')).toBe('$46.60 · — (not recorded)');
  });

  it('formats Bullish stop below entry as adverse move (negative)', () => {
    // Made-up numbers from issue #630: call bought at $3.00 when stock was at $50.00, stop at $46.60
    const res = formatStockStopDistance(46.60, 50.00, 'Bullish');
    expect(res).toBe('$46.60 · −$3.40 / −6.8% from entry');
  });

  it('formats Bullish structural stop below entry', () => {
    // Structural level at $49.85 (15 cents away)
    const res = formatStockStopDistance(49.85, 50.00, 'Bullish');
    expect(res).toBe('$49.85 · −$0.15 / −0.3% from entry');
  });

  it('formats Bullish trailed stop in profit (positive)', () => {
    const res = formatStockStopDistance(53.00, 50.00, 'Bullish');
    expect(res).toBe('$53.00 · +$3.00 / +6.0% from entry');
  });

  it('formats Bearish stop above entry as adverse move (direction-aware negative)', () => {
    // Put entered when stock was at $50.00; stop sits at $53.40 (rises above entry)
    const res = formatStockStopDistance(53.40, 50.00, 'Bearish');
    expect(res).toBe('$53.40 · −$3.40 / −6.8% from entry');
  });

  it('formats Bearish structural stop above entry', () => {
    const res = formatStockStopDistance(50.15, 50.00, 'Bearish');
    expect(res).toBe('$50.15 · −$0.15 / −0.3% from entry');
  });

  it('formats Bearish trailed stop below entry as profit lock (positive)', () => {
    const res = formatStockStopDistance(45.00, 50.00, 'Bearish');
    expect(res).toBe('$45.00 · +$5.00 / +10.0% from entry');
  });

  it('formats stop exactly at entry', () => {
    const res = formatStockStopDistance(50.00, 50.00, 'Bullish');
    expect(res).toBe('$50.00 · $0.00 / 0.0% from entry');
  });
});

describe('formatPremiumStopDistance', () => {
  it('returns null for invalid entry prices', () => {
    expect(formatPremiumStopDistance(null, 0.6, 0.6, 'AAPL|220|2026-12-18|C', 'Bullish')).toBeNull();
    expect(formatPremiumStopDistance(0, 0.6, 0.6, 'AAPL|220|2026-12-18|C', 'Bullish')).toBeNull();
    expect(formatPremiumStopDistance(NaN, 0.6, 0.6, 'AAPL|220|2026-12-18|C', 'Bullish')).toBeNull();
  });

  it('formats option premium stop with explicit per-position pct', () => {
    // Example from issue #630: option bought at $3.00 with 60% stop -> $1.20 · −60% of $3.00
    const res = formatPremiumStopDistance(3.00, 0.60, 0.60, 'AAPL|220|2026-12-18|C', 'Bullish');
    expect(res).toBe('$1.20 · −60% of $3.00');
  });

  it('formats non-integer stop percentages without lossy rounding', () => {
    // Non-integer stop percentage (e.g. 12.5% typed or 48.43% fill-derived)
    const res125 = formatPremiumStopDistance(3.00, 0.125, 0.60, 'AAPL|220|2026-12-18|C', 'Bullish');
    expect(res125).toBe('$2.62 · −12.5% of $3.00');

    const res4843 = formatPremiumStopDistance(4.13, 0.4843, 0.60, 'AAPL|220|2026-12-18|C', 'Bullish');
    expect(res4843).toBe('$2.12 · −48.43% of $4.13');

    const resSmall = formatPremiumStopDistance(4.13, 0.0019, 0.60, 'AAPL|220|2026-12-18|C', 'Bullish');
    expect(resSmall).toBe('$4.12 · −0.19% of $4.13');
  });

  it('resolves inherited global stop when premiumStopPct is null', () => {
    const res = formatPremiumStopDistance(3.00, null, 0.50, 'AAPL|220|2026-12-18|C', 'Bullish');
    expect(res).toBe('$1.50 · −50% of $3.00');
  });

  it('formats short stock position stop firing on rise', () => {
    // Short stock at $50.00 with 10% stop: in JS floating point 50 * 1.1 = 55.00000000000001,
    // percentStopFiringPrice correctly names the smallest 2dp price >= threshold ($55.01).
    const res = formatPremiumStopDistance(50.00, 0.10, 0.60, 'AAPL|STOCK', 'Bearish');
    expect(res).toBe('$55.01 · −$5.01 / −10.0% from entry');
  });

  it('treats Bearish option as long put (not short stock)', () => {
    // Bearish option: premium drops to stop, so it behaves as an option
    const res = formatPremiumStopDistance(4.00, 0.50, 0.60, 'AAPL|200|2026-12-18|P', 'Bearish');
    expect(res).toBe('$2.00 · −50% of $4.00');
  });
});
