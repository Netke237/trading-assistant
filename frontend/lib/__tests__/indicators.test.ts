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

  // 09:30, 10:30, 11:30 ET on 2024-01-02, then the same three on 2024-01-03.
  const DAY1 = [1704205800, 1704209400, 1704213000];
  const DAY2 = [1704292200, 1704295800, 1704299400];
  const intraday = (times: number[]): Candle[] =>
    times.map((t, i) => ({
      time: t, open: 100 + i, high: 101 + i, low: 99 + i, close: 100 + i, volume: 1000 + i * 10,
    }));

  it('resets the accumulation at each Eastern session boundary', () => {
    const bars = intraday([...DAY1, ...DAY2]);
    const out = calcVWAP(bars);
    const i = DAY1.length;
    const tp = (bars[i].high + bars[i].low + bars[i].close) / 3;
    expect(out[i].value).toBeCloseTo(tp, 8);
  });

  it('is independent of how much history is loaded', () => {
    // The regression guard: widening the chart lookback must not move VWAP.
    const all = intraday([...DAY1, ...DAY2]);
    const long = calcVWAP(all).slice(DAY1.length);
    const short = calcVWAP(all.slice(DAY1.length));
    expect(long.map(p => p.value)).toEqual(short.map(p => p.value));
  });

  it('keeps the running total for date-string (daily) bars', () => {
    const out = calcVWAP(candles);
    const last = candles[candles.length - 1];
    const tp = (last.high + last.low + last.close) / 3;
    expect(out[out.length - 1].value).not.toBeCloseTo(tp, 8);
  });
});
