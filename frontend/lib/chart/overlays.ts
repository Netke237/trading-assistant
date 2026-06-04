// frontend/lib/chart/overlays.ts
import { calcEMA, calcSMA, calcRSI } from '@/lib/indicators';
import type { Candle, Point } from '@/lib/indicators';
import type { Interval } from '@/lib/chartStore';
import type { KeyLevels, MarkerPoint, VolumeProfile } from '@/types/overlays';

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

type TimeVal = Map<string | number, number>;

function toMap(pts: Point[]): TimeVal {
  return new Map(pts.map((p) => [p.time, p.value]));
}

function crossMarkers(
  candles: Candle[], a: Point[], b: Point[], upColor: string, dnColor: string,
): MarkerPoint[] {
  const am = toMap(a), bm = toMap(b);
  const out: MarkerPoint[] = [];
  for (let i = 1; i < candles.length; i++) {
    const a0 = am.get(candles[i - 1].time), a1 = am.get(candles[i].time);
    const b0 = bm.get(candles[i - 1].time), b1 = bm.get(candles[i].time);
    if (a0 == null || a1 == null || b0 == null || b1 == null) continue;
    if (a0 <= b0 && a1 > b1) out.push({ time: candles[i].time, position: 'belowBar', color: upColor, shape: 'arrowUp', text: 'X↑' });
    if (a0 >= b0 && a1 < b1) out.push({ time: candles[i].time, position: 'aboveBar', color: dnColor, shape: 'arrowDown', text: 'X↓' });
  }
  return out;
}

/** EMA(emaLen) crossing SMA(smaLen). */
export function calcCrossSignals(candles: Candle[], emaLen: number, smaLen: number): MarkerPoint[] {
  return crossMarkers(candles, calcEMA(candles, emaLen), calcSMA(candles, smaLen), '#26a69a', '#ef5350');
}

/** Fast EMA × slow EMA with RSI>50 / <50 confirmation. */
export function calcSignalMarkers(candles: Candle[], fast: number, slow: number, rsiLen: number): MarkerPoint[] {
  const ef = calcEMA(candles, fast), es = calcEMA(candles, slow), rsi = calcRSI(candles, rsiLen);
  const efm = toMap(ef), esm = toMap(es), rsim = toMap(rsi);
  const out: MarkerPoint[] = [];
  for (let i = 1; i < candles.length; i++) {
    const f0 = efm.get(candles[i - 1].time), f1 = efm.get(candles[i].time);
    const s0 = esm.get(candles[i - 1].time), s1 = esm.get(candles[i].time);
    const r = rsim.get(candles[i].time);
    if (f0 == null || f1 == null || s0 == null || s1 == null || r == null) continue;
    if (f0 <= s0 && f1 > s1 && r > 50) out.push({ time: candles[i].time, position: 'belowBar', color: '#26a69a', shape: 'arrowUp', text: 'BUY' });
    if (f0 >= s0 && f1 < s1 && r < 50) out.push({ time: candles[i].time, position: 'aboveBar', color: '#ef5350', shape: 'arrowDown', text: 'SELL' });
  }
  return out;
}

export function calcVolumeProfile(candles: Candle[], lookback: number, rows: number): VolumeProfile {
  const slice = candles.slice(-lookback);
  if (slice.length === 0 || rows < 1) return { bins: [], poc: null, vah: null, val: null };
  const hi = Math.max(...slice.map((c) => c.high));
  const lo = Math.min(...slice.map((c) => c.low));
  const rng = hi - lo;
  if (rng <= 0) return { bins: [], poc: null, vah: null, val: null };
  const binSz = rng / rows;
  const vols = new Array<number>(rows).fill(0);
  for (const c of slice) {
    const idx = Math.min(rows - 1, Math.max(0, Math.floor((hlc3(c) - lo) / binSz)));
    vols[idx] += c.volume;
  }
  const bins = vols.map((v, i) => ({ price: lo + i * binSz, volume: v }));
  const total = vols.reduce((a, b) => a + b, 0);
  const pocIdx = vols.indexOf(Math.max(...vols));
  let loI = pocIdx, hiI = pocIdx, acc = vols[pocIdx];
  while (acc < total * 0.7 && (loI > 0 || hiI < rows - 1)) {
    const down = loI > 0 ? vols[loI - 1] : -1;
    const up = hiI < rows - 1 ? vols[hiI + 1] : -1;
    if (up >= down) { hiI++; acc += Math.max(0, up); } else { loI--; acc += Math.max(0, down); }
  }
  return { bins, poc: bins[pocIdx].price, vah: bins[hiI].price, val: bins[loI].price };
}

/** Aggregate candles into buckets of `tfMin` minutes (numeric-time candles only). */
export function resample(candles: Candle[], tfMin: number): Candle[] {
  if (tfMin <= 0 || candles.length === 0) return candles;
  const bucketMs = tfMin * 60 * 1000;
  const norm = (v: number | string) => typeof v === 'number' ? (v < 1e12 ? v * 1000 : v) : Date.parse(String(v));
  const out: Candle[] = [];
  let cur: Candle | null = null; let curKey = NaN;
  for (const c of candles) {
    const key = Math.floor(norm(c.time) / bucketMs);
    if (cur === null || key !== curKey) {
      if (cur) out.push(cur);
      cur = { ...c }; curKey = key;
    } else {
      cur.high = Math.max(cur.high, c.high);
      cur.low = Math.min(cur.low, c.low);
      cur.close = c.close;
      cur.volume += c.volume;
    }
  }
  if (cur) out.push(cur);
  return out;
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
