// frontend/lib/indicators.ts

export interface Candle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Point {
  time: string;
  value: number;
}

export interface MACDResult {
  macd: Point[];
  signal: Point[];
  histogram: Point[];
}

export interface BBResult {
  upper: Point[];
  middle: Point[];
  lower: Point[];
}

export function calcSMA(candles: Candle[], period: number): Point[] {
  if (candles.length < period) return [];
  return candles.slice(period - 1).map((_, i) => ({
    time: candles[i + period - 1].time,
    value: candles.slice(i, i + period).reduce((s, c) => s + c.close, 0) / period,
  }));
}

export function calcEMA(candles: Candle[], period: number): Point[] {
  if (candles.length < period) return [];
  const k = 2 / (period + 1);
  const result: Point[] = [];
  let ema = candles.slice(0, period).reduce((s, c) => s + c.close, 0) / period;
  result.push({ time: candles[period - 1].time, value: ema });
  for (let i = period; i < candles.length; i++) {
    ema = candles[i].close * k + ema * (1 - k);
    result.push({ time: candles[i].time, value: ema });
  }
  return result;
}

export function calcRSI(candles: Candle[], period = 14): Point[] {
  if (candles.length < period + 1) return [];
  const result: Point[] = [];
  let avgGain = 0;
  let avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    const diff = candles[i].close - candles[i - 1].close;
    if (diff > 0) avgGain += diff;
    else avgLoss += Math.abs(diff);
  }
  avgGain /= period;
  avgLoss /= period;
  result.push({
    time: candles[period].time,
    value: avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss),
  });
  for (let i = period + 1; i < candles.length; i++) {
    const diff = candles[i].close - candles[i - 1].close;
    avgGain = (avgGain * (period - 1) + (diff > 0 ? diff : 0)) / period;
    avgLoss = (avgLoss * (period - 1) + (diff < 0 ? Math.abs(diff) : 0)) / period;
    result.push({
      time: candles[i].time,
      value: avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss),
    });
  }
  return result;
}

export function calcMACD(candles: Candle[], fast = 12, slow = 26, signalPeriod = 9): MACDResult {
  const fastEMA = calcEMA(candles, fast);
  const slowEMA = calcEMA(candles, slow);
  const fastMap = new Map(fastEMA.map(p => [p.time, p.value]));
  const macdLine: Point[] = slowEMA
    .map(p => ({ time: p.time, value: (fastMap.get(p.time) ?? p.value) - p.value }))
    .sort((a, b) => a.time.localeCompare(b.time));

  if (macdLine.length < signalPeriod) return { macd: macdLine, signal: [], histogram: [] };
  const k = 2 / (signalPeriod + 1);
  let sig = macdLine.slice(0, signalPeriod).reduce((s, p) => s + p.value, 0) / signalPeriod;
  const signalLine: Point[] = [{ time: macdLine[signalPeriod - 1].time, value: sig }];
  for (let i = signalPeriod; i < macdLine.length; i++) {
    sig = macdLine[i].value * k + sig * (1 - k);
    signalLine.push({ time: macdLine[i].time, value: sig });
  }
  const sigMap = new Map(signalLine.map(p => [p.time, p.value]));
  const histogram = macdLine
    .filter(p => sigMap.has(p.time))
    .map(p => ({ time: p.time, value: p.value - sigMap.get(p.time)! }));
  return { macd: macdLine, signal: signalLine, histogram };
}

export function calcBB(candles: Candle[], period = 20, stdDev = 2): BBResult {
  const middle = calcSMA(candles, period);
  const upper: Point[] = [];
  const lower: Point[] = [];
  middle.forEach((m, i) => {
    const slice = candles.slice(i, i + period).map(c => c.close);
    const std = Math.sqrt(slice.reduce((s, v) => s + (v - m.value) ** 2, 0) / period);
    upper.push({ time: m.time, value: m.value + stdDev * std });
    lower.push({ time: m.time, value: m.value - stdDev * std });
  });
  return { upper, middle, lower };
}

export function calcATR(candles: Candle[], period = 14): Point[] {
  if (candles.length < 2) return [];
  const tr = candles.slice(1).map((c, i) => ({
    time: c.time,
    tr: Math.max(c.high - c.low, Math.abs(c.high - candles[i].close), Math.abs(c.low - candles[i].close)),
  }));
  if (tr.length < period) return [];
  const result: Point[] = [];
  let atr = tr.slice(0, period).reduce((s, r) => s + r.tr, 0) / period;
  result.push({ time: tr[period - 1].time, value: atr });
  for (let i = period; i < tr.length; i++) {
    atr = (atr * (period - 1) + tr[i].tr) / period;
    result.push({ time: tr[i].time, value: atr });
  }
  return result;
}

export function calcVWAP(candles: Candle[]): Point[] {
  let cumPV = 0;
  let cumVol = 0;
  return candles.map(c => {
    const tp = (c.high + c.low + c.close) / 3;
    cumPV += tp * c.volume;
    cumVol += c.volume;
    return { time: c.time, value: cumVol > 0 ? cumPV / cumVol : tp };
  });
}
