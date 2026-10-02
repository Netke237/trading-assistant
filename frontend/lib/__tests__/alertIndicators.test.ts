import { alertIndicatorReference, computeAlertIndicatorPoints, parseAlertIndicator } from '../alertIndicators';
import { calcEMA, calcMACD } from '../indicators';
import type { IndicatorConfig } from '../chartStore';
import type { Condition } from '@/types/alerts';

const candles = Array.from({ length: 80 }, (_, i) => ({
  time: `bar-${i}`, open: 100+i, close: 100+i+i%3, high: 104+i, low: 98+i, volume: 1000+i,
}));
const condition = (indicator: string): Condition => ({ kind: 'indicator', indicator, operator: '>', value: 0 });

test('chart instance id and parameter insertion order do not change saved MACD reference', () => {
  const config: IndicatorConfig = { id: 'macd-1720000000000', type: 'MACD',
    params: { signal: 4, slow: 12, fast: 5 }, pane: 'sub', color: '#fff' };
  expect(alertIndicatorReference(config)).toBe('MACD(5,12,4)');
  expect(alertIndicatorReference({ ...config, id: 'different' })).toBe('MACD(5,12,4)');
});

test('browser computes rule parameters without any active chart indicators', () => {
  const points = computeAlertIndicatorPoints(candles, [condition('EMA(7)'), condition('MACD(5,12,4)')]);
  expect(points['EMA(7)']).toEqual(calcEMA(candles, 7));
  expect(points['MACD(5,12,4)']).toEqual(calcMACD(candles, 5, 12, 4).macd);
});

test.each(['', 'ema-20', 'macd-1720000000000', 'EMA(0)', 'RSI(1.5)', 'MACD(26,12,9)', 'EMA(' + '1'.repeat(5000) + ')', 'MACD(5,12)', 'SMA(10001)', 'BB_MID(8,nan)'])('rejects %s', ref => {
  expect(parseAlertIndicator(ref)).toBeNull();
});

test.each(['VOL(default)', 'VWAP(default)', 'BB(20,2)', 'RSI(5)', 'ATR(6)', 'macd_signal', 'ema20'])('preserves supported old references %s', ref => {
  expect(computeAlertIndicatorPoints(candles, [condition(ref)])[ref].length).toBeGreaterThan(0);
});
