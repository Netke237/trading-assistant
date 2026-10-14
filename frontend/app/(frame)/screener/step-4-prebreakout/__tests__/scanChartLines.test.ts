import { fibLevelPrice, scanChartLines } from '../scanChartLines';

test.each([
  ['23.6', .236], ['38.2%', .382], ['50.0', .5], ['61.8', .618], ['78.6%', .786],
])('known label %s uses exact directional retracement formula', (label, ratio) => {
  expect(fibLevelPrice('Bullish', String(label), 100, 200)).toBe(200 - Number(ratio) * 100);
  expect(fibLevelPrice('Bearish', String(label), 100, 200)).toBe(100 + Number(ratio) * 100);
});
test('unknown, malformed, absent and non-finite evidence creates no guessed level', () => {
  for (const label of ['42', '38.2junk', '38.2%%', '', 'Infinity']) expect(fibLevelPrice('Bullish', label, 100, 200)).toBeNull();
  expect(fibLevelPrice('unknown', '38.2', 100, 200)).toBeNull();
  expect(fibLevelPrice('Bullish', '38.2', NaN, 200)).toBeNull();
  expect(scanChartLines({direction: 'Bullish', fib_level_hit: '42', fib_swing: {low: 100, high: 200}}, 'fib').map(line => line.price)).toEqual([100, 200]);
  expect(scanChartLines({direction: 'Bullish', fib_level_hit: '38.2'}, 'fib')).toEqual([]);
  expect(scanChartLines({direction: 'Bullish', fib_swing: {low: null, high: Infinity}}, 'fib')).toEqual([]);
});
test('Pre returned swing level and optional Fib swing bounds are scan evidence; zero retained', () => {
  expect(scanChartLines({direction: 'Bearish', metrics: {swing_level: 0}, fib_swing: {low: 10, high: 20}}, 'prebreakout')).toEqual([
    {price: 0, title: 'Scan swing low'}, {price: 10, title: 'Scan Fib swing low'}, {price: 20, title: 'Scan Fib swing high'},
  ]);
  expect(scanChartLines({direction: 'Bullish', metrics: {swing_level: NaN}}, 'prebreakout')).toEqual([]);
  expect(scanChartLines({direction: 'Bullish', metrics: {swing_level: 200}}, 'pullback')).toEqual([]);
});
