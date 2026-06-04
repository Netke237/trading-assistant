import { calcAnchoredVWAP, calcKeyLevels } from './overlays';
import type { Candle } from '@/lib/indicators';

const c = (time: number, price: number, vol: number): Candle =>
  ({ time, open: price, high: price, low: price, close: price, volume: vol });

describe('calcKeyLevels', () => {
  it('returns the previous completed day high/low', () => {
    const candles = [
      { time: '2025-01-01', open: 1, high: 12, low: 8,  close: 10, volume: 1 },
      { time: '2025-01-02', open: 10, high: 15, low: 9, close: 14, volume: 1 },
    ];
    const lv = calcKeyLevels(candles, '1D');
    expect(lv.pdh).toBe(12);
    expect(lv.pdl).toBe(8);
  });
});

describe('calcAnchoredVWAP', () => {
  it('returns na before the anchor and cumulative VWAP after', () => {
    const candles = [c(100, 10, 0), c(200, 20, 10), c(300, 30, 10)];
    const out = calcAnchoredVWAP(candles, 200);
    expect(out[0].value).toBeNull();          // before anchor
    expect(out[1].value).toBeCloseTo(20);     // first anchored bar
    expect(out[2].value).toBeCloseTo(25);     // (20*10 + 30*10) / 20
  });
});
