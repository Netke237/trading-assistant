// frontend/lib/chart/overlays.ts
import type { Candle, Point } from '@/lib/indicators';

const hlc3 = (c: Candle) => (c.high + c.low + c.close) / 3;

/** Cumulative VWAP measured from the first candle whose time >= anchorMs. */
export function calcAnchoredVWAP(candles: Candle[], anchorMs: number): Point[] {
  let cumPV = 0, cumV = 0;
  const norm = (v: number | string) =>
    typeof v === 'number' ? (v < 1e12 ? v * 1000 : v) : Date.parse(String(v));
  const anchor = anchorMs < 1e12 ? anchorMs * 1000 : anchorMs;
  return candles.map((c): Point => {
    const t = norm(c.time);
    if (t < anchor) return { time: c.time, value: null as unknown as number };
    cumPV += hlc3(c) * c.volume;
    cumV  += c.volume;
    return { time: c.time, value: cumV > 0 ? cumPV / cumV : (null as unknown as number) };
  });
}
