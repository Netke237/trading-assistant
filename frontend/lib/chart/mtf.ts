// frontend/lib/chart/mtf.ts
import { calcEMA, calcRSI, type Candle } from '@/lib/indicators';
import type { Interval } from '@/lib/chartStore';
import type { MtfRow } from '@/types/overlays';

const last = <T,>(arr: T[]): T | undefined => arr[arr.length - 1];

/** One dashboard row for a timeframe given that timeframe's candles. */
export function buildMtfRow(tf: Interval, candles: Candle[], rsiLen: number): MtfRow {
  const ema21 = calcEMA(candles, 21);
  const ema50 = calcEMA(candles, 50);
  const rsi = calcRSI(candles, rsiLen);
  const e21 = last(ema21)?.value ?? 0;
  const e50 = last(ema50)?.value ?? 0;
  const c = last(candles);
  const changePct = c ? ((c.close - c.open) / c.open) * 100 : 0;
  return { tf, trendUp: e21 > e50, rsi: last(rsi)?.value ?? 0, changePct };
}
