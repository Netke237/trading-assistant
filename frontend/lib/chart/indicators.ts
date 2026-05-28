import type { Candle } from '@/types/chart';

function ema(data: number[], period: number): number[] {
  const result: number[] = new Array(data.length).fill(NaN);
  if (data.length < period) return result;
  let prev = data.slice(0, period).reduce((a, b) => a + b, 0) / period;
  result[period - 1] = prev;
  const k = 2 / (period + 1);
  for (let i = period; i < data.length; i++) {
    prev = data[i] * k + prev * (1 - k);
    result[i] = prev;
  }
  return result;
}

export function calculateRSI(
  candles: Candle[],
  period: number = 14,
): Array<{ time: string | number; value: number }> {
  if (candles.length < period + 1) return [];
  const closes = candles.map((c) => c.close);
  const times = candles.map((c) => c.time);

  let gains = 0;
  let losses = 0;
  for (let i = 1; i <= period; i++) {
    const change = closes[i] - closes[i - 1];
    if (change > 0) gains += change;
    else losses -= change;
  }
  let avgGain = gains / period;
  let avgLoss = losses / period;

  const result: Array<{ time: string | number; value: number }> = [];
  const firstRsi = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  result.push({ time: times[period], value: firstRsi });

  for (let i = period + 1; i < closes.length; i++) {
    const change = closes[i] - closes[i - 1];
    const gain = change > 0 ? change : 0;
    const loss = change < 0 ? -change : 0;
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
    const rsi = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
    result.push({ time: times[i], value: rsi });
  }

  return result;
}

export function calculateMACD(
  candles: Candle[],
  fast: number = 12,
  slow: number = 26,
  signal: number = 9,
): Array<{ time: string | number; macd: number; signal: number; histogram: number }> {
  if (candles.length < slow + signal - 1) return [];
  const closes = candles.map((c) => c.close);

  const emaFast = ema(closes, fast);
  const emaSlow = ema(closes, slow);

  const macdLine: number[] = [];
  for (let i = 0; i < closes.length; i++) {
    macdLine.push(
      Number.isNaN(emaFast[i]) || Number.isNaN(emaSlow[i])
        ? NaN
        : emaFast[i] - emaSlow[i],
    );
  }

  const validStart = slow - 1;
  const validMacd = macdLine.slice(validStart);
  const signalEmaArr = ema(validMacd, signal);

  const result: Array<{ time: string | number; macd: number; signal: number; histogram: number }> = [];
  for (let i = signal - 1; i < signalEmaArr.length; i++) {
    const idx = validStart + i;
    result.push({
      time: candles[idx].time,
      macd: macdLine[idx],
      signal: signalEmaArr[i],
      histogram: macdLine[idx] - signalEmaArr[i],
    });
  }
  return result;
}

export function calculateVolume(
  candles: Candle[],
): Array<{ time: string | number; value: number; color: string }> {
  return candles.map((c) => ({
    time: c.time,
    value: c.volume,
    color: c.close >= c.open ? 'up' : 'down',
  }));
}
