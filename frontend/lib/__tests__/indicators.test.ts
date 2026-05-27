// frontend/lib/__tests__/indicators.test.ts
import { calcSMA, calcEMA, calcRSI, calcMACD, calcBB, calcATR, calcVWAP, Candle } from '../indicators';

const candles: Candle[] = Array.from({ length: 30 }, (_, i) => ({
  time: `2024-01-${String(i + 1).padStart(2, '0')}`,
  open: 100 + i,
  high: 102 + i,
  low: 99 + i,
  close: 101 + i,
  volume: 1000 + i * 10,
}));

describe('calcSMA', () => {
  it('returns correct number of points', () => {
    const result = calcSMA(candles, 5);
    expect(result.length).toBe(candles.length - 5 + 1);
  });
  it('first point equals average of first 5 closes', () => {
    const result = calcSMA(candles, 5);
    const expected = (101 + 102 + 103 + 104 + 105) / 5;
    expect(result[0].value).toBeCloseTo(expected, 4);
  });
  it('returns empty array when period > candles length', () => {
    expect(calcSMA(candles, 100)).toEqual([]);
  });
});

describe('calcEMA', () => {
  it('returns at least 1 point for period <= length', () => {
    expect(calcEMA(candles, 10).length).toBeGreaterThan(0);
  });
  it('returns empty array when not enough candles', () => {
    expect(calcEMA(candles.slice(0, 3), 5)).toEqual([]);
  });
});

describe('calcRSI', () => {
  it('values are between 0 and 100', () => {
    const result = calcRSI(candles, 14);
    result.forEach(p => {
      expect(p.value).toBeGreaterThanOrEqual(0);
      expect(p.value).toBeLessThanOrEqual(100);
    });
  });
});

describe('calcMACD', () => {
  it('returns macd, signal, and histogram arrays', () => {
    const result = calcMACD(candles);
    expect(Array.isArray(result.macd)).toBe(true);
    expect(Array.isArray(result.signal)).toBe(true);
    expect(Array.isArray(result.histogram)).toBe(true);
  });
});

describe('calcBB', () => {
  it('upper is always >= middle >= lower', () => {
    const result = calcBB(candles, 10, 2);
    result.upper.forEach((u, i) => {
      expect(u.value).toBeGreaterThanOrEqual(result.middle[i].value);
      expect(result.middle[i].value).toBeGreaterThanOrEqual(result.lower[i].value);
    });
  });
});

describe('calcATR', () => {
  it('all ATR values are positive', () => {
    const result = calcATR(candles, 14);
    result.forEach(p => expect(p.value).toBeGreaterThan(0));
  });
});

describe('calcVWAP', () => {
  it('returns same number of points as input', () => {
    expect(calcVWAP(candles).length).toBe(candles.length);
  });
});
