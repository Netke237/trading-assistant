import { calcAnchoredVWAP, calcKeyLevels, calcCrossSignals, calcSignalMarkers } from './overlays';
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

const series = (closes: number[]): Candle[] =>
  closes.map((p, i) => ({ time: i + 1, open: p, high: p, low: p, close: p, volume: 1 }));

describe('cross signals', () => {
  it('emits an arrowUp marker when EMA crosses above SMA', () => {
    const candles = series([1,1,1,1,1,1,1,1,1,10,11,12,13,14,15]);
    const m = calcCrossSignals(candles, 3, 5);
    expect(m.some((x) => x.shape === 'arrowUp')).toBe(true);
  });
  it('signal markers return an array', () => {
    const candles = series(Array.from({ length: 40 }, (_, i) => i));
    const m = calcSignalMarkers(candles, 9, 21, 14);
    expect(Array.isArray(m)).toBe(true);
  });
});

import { calcVolumeProfile } from './overlays';

describe('calcVolumeProfile', () => {
  it('bins volume by price and reports a POC', () => {
    const candles = [
      { time: 1, open: 10, high: 10, low: 10, close: 10, volume: 100 },
      { time: 2, open: 20, high: 20, low: 20, close: 20, volume: 10 },
    ];
    const vp = calcVolumeProfile(candles, 2, 4);
    expect(vp.bins.length).toBe(4);
    expect(vp.poc).toBeCloseTo(10, 0);
  });
});
