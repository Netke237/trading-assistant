/** Stable alert references encode parameters, never a mutable chart instance id. */
import { pythonRound4 } from './premiumStop';
import type { IndicatorConfig } from './chartStore';
import type { Condition } from '@/types/alerts';
import { calcSMA, calcRSI, calcATR, calcBB, calcVWAP, type Candle, type Point } from './indicators';

type Spec = { kind: string; params: number[] };
const defaults: Record<string, number[]> = {
  ema: [20], sma: [20], rsi: [14], atr: [14], macd: [12, 26, 9], macd_signal: [12, 26, 9],
  bb: [20, 2], bb_upper: [20, 2], bb_lower: [20, 2], bb_mid: [20, 2],
  vwap: [], volume: [], close: [],
};
export function parseAlertIndicator(reference: unknown): Spec | null {
  if (typeof reference !== 'string') return null;
  const aliases: Record<string, string> = {
    macd_line: 'macd', vol: 'volume', 'vol(default)': 'volume', 'vwap(default)': 'vwap',
    bollinger_upper: 'bb_upper', bollinger_lower: 'bb_lower', bollinger_mid: 'bb_mid',
  };
  const name = aliases[reference.toLowerCase()] ?? reference.toLowerCase();
  if (Object.hasOwn(defaults, name)) return { kind: name, params: defaults[name] };
  const old = /^(ema|sma)(9|20|50)$/.exec(name);
  if (old) return { kind: old[1], params: [Number(old[2])] };
  const match = /^(ema|sma|rsi|atr|macd|macd_signal|bb|bb_upper|bb_lower|bb_mid)\(([^()]*)\)$/.exec(name);
  if (!match) return null;
  const [, kind, raw] = match;
  const parts = raw.split(',');
  if (parts.length !== defaults[kind].length) return null;
  const params = parts.map(Number);
  if (parts.some((part, i) => {
    if (kind.startsWith('bb') && i === 1) return !/^(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:e[+-]?[0-9]+)?$/.test(part) || !Number.isFinite(params[i]) || params[i] <= 0 || params[i] > 10000;
    return !/^[1-9][0-9]*$/.test(part) || params[i] > 10000;
  })) return null;
  if (['macd', 'macd_signal'].includes(kind) && params[0] >= params[1]) return null;
  return { kind, params };
}

export function alertIndicatorReference(indicator: IndicatorConfig): string | null {
  const kind = indicator.type.toLowerCase();
  const p = indicator.params;
  let reference: string;
  if (['ema', 'sma', 'rsi', 'atr'].includes(kind)) {
    reference = `${indicator.type}(${p.period ?? defaults[kind][0]})`;
  } else if (kind === 'macd') {
    reference = `MACD(${p.fast ?? 12},${p.slow ?? 26},${p.signal ?? 9})`;
  } else if (kind === 'bb') {
    reference = `BB_MID(${p.period ?? 20},${p.stdDev ?? 2})`;
  } else if (kind === 'vwap') reference = 'VWAP';
  else if (kind === 'vol') reference = 'volume';
  else return null;
  return parseAlertIndicator(reference) ? reference : null;
}

/** Alert arithmetic mirrors backend _ema_seeded on the pinned Python 3.11 runtime.
 * Python 3.12 changes sum() semantics; updating the runtime requires parity validation.
 * Chart calcEMA uses an algebraically equivalent recurrence whose floating-point
 * result can round differently at a comparison boundary. */
function alertEMA(values: number[], period: number): (number | null)[] {
  const result: (number | null)[] = Array(values.length).fill(null);
  if (values.length < period) return result;
  const k = 2 / (period + 1);
  let ema = values.slice(0, period).reduce((sum, value) => sum + value, 0) / period;
  result[period - 1] = ema;
  for (let i = period; i < values.length; i++) {
    ema = (values[i] - ema) * k + ema;
    result[i] = ema;
  }
  return result;
}

function emaPoints(candles: Candle[], period: number): Point[] {
  return alertEMA(candles.map(c => c.close), period).flatMap((value, i) =>
    value === null ? [] : [{ time: candles[i].time, value }]);
}

function macdPoints(candles: Candle[], fast: number, slow: number, signal: number, signalLine: boolean): Point[] {
  const closes = candles.map(c => c.close);
  const fastEMA = alertEMA(closes, fast);
  const slowEMA = alertEMA(closes, slow);
  const start = slow - 1; // The parser requires fast < slow.
  const line = closes.slice(start).map((_, i) => fastEMA[start + i]! - slowEMA[start + i]!);
  const values = signalLine ? alertEMA(line, signal) : line;
  return values.flatMap((value, i) => value === null ? [] : [{ time: candles[start + i].time, value }]);
}

export function computeAlertIndicatorPoints(candles: Candle[], conditions: Condition[]): Record<string, Point[]> {
  const result: Record<string, Point[]> = {};
  for (const c of conditions) {
    if (c.kind !== 'indicator' || Object.hasOwn(result, c.indicator)) continue;
    const spec = parseAlertIndicator(c.indicator);
    if (!spec) continue;
    const { kind, params: p } = spec;
    let points: Point[];
    if (kind === 'ema') points = emaPoints(candles, p[0]);
    else if (kind === 'sma') points = calcSMA(candles, p[0]);
    else if (kind === 'rsi') points = calcRSI(candles, p[0]);
    else if (kind === 'atr') points = calcATR(candles, p[0]);
    else if (kind === 'macd' || kind === 'macd_signal') {
      points = macdPoints(candles, p[0], p[1], p[2], kind === 'macd_signal');
    } else if (kind.startsWith('bb')) {
      const bb = calcBB(candles, p[0], p[1]);
      points = kind === 'bb_upper' ? bb.upper : kind === 'bb_lower' ? bb.lower : bb.middle;
    } else if (kind === 'vwap') points = calcVWAP(candles);
    else points = candles.map(b => ({ time: b.time, value: kind === 'volume' ? b.volume : b.close }));
    // Match backend comparison precision; MACD and raw prices/volume are unrounded.
    result[c.indicator] = ['macd', 'macd_signal', 'volume', 'close'].includes(kind)
      ? points : points.map(p => ({ ...p, value: pythonRound4(p.value) }));
  }
  return result;
}
