// frontend/lib/chart/overlays.ts
import type { Candle, Point } from '@/lib/indicators';
import type { Interval } from '@/lib/chartStore';
import type { KeyLevels } from '@/types/overlays';

const hlc3 = (c: Candle) => (c.high + c.low + c.close) / 3;

function bucketKey(time: string | number, unit: 'day' | 'week'): string {
  const d = typeof time === 'number'
    ? new Date(time < 1e12 ? time * 1000 : time)
    : new Date(`${time}T00:00:00Z`);
  if (unit === 'day') return d.toISOString().slice(0, 10);
  const onejan = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  const week = Math.ceil((((d.getTime() - onejan.getTime()) / 86400000) + onejan.getUTCDay() + 1) / 7);
  return `${d.getUTCFullYear()}-W${week}`;
}

function prevBucketHL(candles: Candle[], unit: 'day' | 'week'): [number | null, number | null] {
  if (candles.length === 0) return [null, null];
  const lastKey = bucketKey(candles[candles.length - 1].time, unit);
  const completed = candles.filter((c) => bucketKey(c.time, unit) !== lastKey);
  if (completed.length === 0) return [null, null];
  const prevKey = bucketKey(completed[completed.length - 1].time, unit);
  const inPrev = completed.filter((c) => bucketKey(c.time, unit) === prevKey);
  return [Math.max(...inPrev.map((c) => c.high)), Math.min(...inPrev.map((c) => c.low))];
}

export function calcKeyLevels(candles: Candle[], _interval: Interval): KeyLevels {
  const [pdh, pdl] = prevBucketHL(candles, 'day');
  const [pwh, pwl] = prevBucketHL(candles, 'week');
  return { pdh, pdl, pwh, pwl };
}

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
