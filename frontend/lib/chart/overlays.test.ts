import { calcAnchoredVWAP } from './overlays';
import type { Candle } from '@/lib/indicators';

const c = (time: number, price: number, vol: number): Candle =>
  ({ time, open: price, high: price, low: price, close: price, volume: vol });

describe('calcAnchoredVWAP', () => {
  it('returns na before the anchor and cumulative VWAP after', () => {
    const candles = [c(100, 10, 0), c(200, 20, 10), c(300, 30, 10)];
    const out = calcAnchoredVWAP(candles, 200);
    expect(out[0].value).toBeNull();          // before anchor
    expect(out[1].value).toBeCloseTo(20);     // first anchored bar
    expect(out[2].value).toBeCloseTo(25);     // (20*10 + 30*10) / 20
  });
});
