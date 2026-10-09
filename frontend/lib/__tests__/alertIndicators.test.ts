import parityFixture from './fixtures/alert_indicator_python311.json';
import { alertIndicatorReference, computeAlertIndicatorPoints, parseAlertIndicator } from '../alertIndicators';
import { pythonRound4 } from '../premiumStop';
import { evaluateRules } from '../chartAlertEngine';
import type { AlertRule } from '@/types/alerts';
import { calcEMA, calcMACD } from '../indicators';
import type { IndicatorConfig } from '../chartStore';
import type { IndicatorCondition } from '@/types/alerts';

const candles = Array.from({ length: 80 }, (_, i) => ({
  time: `bar-${i}`, open: 100+i, close: 100+i+i%3, high: 104+i, low: 98+i, volume: 1000+i,
}));
const condition = (indicator: string): IndicatorCondition => ({ kind: 'indicator', indicator, operator: '>', value: 0 });

test('chart instance id and parameter insertion order do not change saved MACD reference', () => {
  const config: IndicatorConfig = { id: 'macd-1720000000000', type: 'MACD',
    params: { signal: 4, slow: 12, fast: 5 }, pane: 'sub', color: '#fff' };
  expect(alertIndicatorReference(config)).toBe('MACD(5,12,4)');
  expect(alertIndicatorReference({ ...config, id: 'different' })).toBe('MACD(5,12,4)');
});

test('browser computes rule parameters without any active chart indicators', () => {
  const points = computeAlertIndicatorPoints(candles, [condition('EMA(7)'), condition('MACD(5,12,4)')]);
  expect(points['EMA(7)']).toEqual(calcEMA(candles, 7).map(p => ({ ...p, value: pythonRound4(p.value) })));
  const chartMACD = calcMACD(candles, 5, 12, 4).macd;
  expect(points['MACD(5,12,4)'].map(p => p.time)).toEqual(chartMACD.map(p => p.time));
  points['MACD(5,12,4)'].forEach((p, i) => expect(p.value).toBeCloseTo(chartMACD[i].value, 10));
});

test.each(['', 'ema-20', 'macd-1720000000000', 'EMA(0)', 'RSI(1.5)', 'MACD(26,12,9)', 'EMA(' + '1'.repeat(5000) + ')', 'MACD(5,12)', 'SMA(10001)', 'BB_MID(8,nan)', 'BB_UPPER(2,1e308)'])('rejects %s', ref => {
  expect(parseAlertIndicator(ref)).toBeNull();
});

test.each(['VOL(default)', 'VWAP(default)', 'BB(20,2)', 'RSI(5)', 'ATR(6)', 'macd_signal', 'ema20'])('preserves supported old references %s', ref => {
  expect(computeAlertIndicatorPoints(candles, [condition(ref)])[ref].length).toBeGreaterThan(0);
});


test('cent-price EMA decay cannot falsely fire above the rounded backend threshold', () => {
  const bars = [...Array(7).fill(100), 100.01, ...Array(16).fill(100)].map((close, i) => ({
    time: 1720000000 + i * 3600, open: close, high: close + 1, low: close - 1, close, volume: 100,
  }));
  const c = condition('EMA(7)');
  c.value = 100;
  const rule: AlertRule = { id: 'parity', name: 'parity', symbol: 'AAPL', interval: '1h',
    enabled: true, group: { logic: 'AND', conditions: [c] }, cooldown_minutes: 0,
    expiry_date: null, created_at: '2024-01-01', last_triggered_at: null };
  const points = computeAlertIndicatorPoints(bars, [c]);
  expect(points['EMA(7)'].at(-1)?.value).toBe(100);
  expect(evaluateRules([rule], bars.at(-1)!, bars, points, [], new Date(), 'AAPL', '1h')).toEqual([]);
});

test('an OR match never includes nonfinite indicator values in persisted trigger data', () => {
  const candle = candles.at(-1)!;
  const rule: AlertRule = { id: 'finite', name: 'finite', symbol: 'AAPL', interval: '1h',
    enabled: true, group: { logic: 'OR', conditions: [condition('BB_UPPER(2,2)'),
      { kind: 'price', operator: '>', value: 0 }] }, cooldown_minutes: 0,
    expiry_date: null, created_at: '2024-01-01', last_triggered_at: null };
  const result = evaluateRules([rule], candle, candles,
    { 'BB_UPPER(2,2)': [{ time: candle.time, value: Infinity }] }, [], new Date(), 'AAPL', '1h');
  expect(result).toHaveLength(1);
  expect(result[0].trigger_values).toEqual({ close: candle.close });
});


test.each(['>', 'crosses_above'] as const)('EMA backend arithmetic prevents a false %s at a rounding boundary', operator => {
  const bars = [100.05,99.87,100.46,100.38,100.08,99.69,99.61,99.4,99.96].map((close, i) => ({
    time: 1720000000 + i * 3600, open: close, high: close + 1, low: close - 1, close, volume: 100,
  }));
  const c: IndicatorCondition = { kind: 'indicator', indicator: 'EMA(7)', operator, value: 99.8887 };
  const points = computeAlertIndicatorPoints(bars, [c]);
  expect(points['EMA(7)'].at(-1)?.value).toBe(99.8887);
  const rule: AlertRule = { id: 'boundary', name: 'boundary', symbol: 'AAPL', interval: '1h',
    enabled: true, group: { logic: 'AND', conditions: [c] }, cooldown_minutes: 0,
    expiry_date: null, created_at: '2024-01-01', last_triggered_at: null };
  expect(evaluateRules([rule], bars.at(-1)!, bars, points, [], new Date(), 'AAPL', '1h')).toEqual([]);
});

describe('exact parity with the Docker/CI Python 3.11 runtime', () => {
  const fixture = parityFixture as unknown as {
    cases: { name: string; closes: number[]; expected: Record<string, [number, number][]> }[];
  };
  test.each(fixture.cases)('$name matches every timestamped backend reading exactly', c => {
    const bars = c.closes.map((close, i) => ({ time: 1720000000+i*3600,
      open: close, close, high: close+1, low: close-1, volume: 100+i*10 }));
    const points = computeAlertIndicatorPoints(bars, Object.keys(c.expected).map(condition));
    const actual = Object.fromEntries(Object.entries(points).map(([ref, series]) =>
      [ref, series.map(p => [p.time, p.value])]));
    expect(actual).toEqual(c.expected);
  });
});
