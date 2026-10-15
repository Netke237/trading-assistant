import { historicalSeries, fillEvents } from './chart';
import type { DetailedBacktestResult } from '@/types/backtest';
const detail = {
 candles: [{ time: 1700000000, open: 40, high: 45, low: 35, close: 42, volume: 10 }],
 equity: [{ time: 1700000000, equity: 99900, strategy_index: 99.9, benchmark_index: 100 }],
 trades: [{ id: 'a', direction: 'Bearish', entry_time: 1700000000, exit_time: 1700000000, entry_price: 43.125, exit_price: 39.875, exit_reason: 'unknown', net_return_pct: 7 }],
 open_positions: [{id: 'open', direction: 'Bullish', entry_time: 1700000000, entry_price: 40.25}],
} as DetailedBacktestResult;
it('keeps engine indexes, timestamps and units without rebasing or bearish benchmark inversion', () => {
 const result = historicalSeries(detail);
 expect(result.strategy).toEqual([{ time: 1700000000, value: 99.9 }]);
 expect(result.benchmark).toEqual([{ time: 1700000000, value: 100 }]);
 expect(result.candles[0].close).toBe(42);
});
it('preserves all same-bar exact fills, including an open entry without an invented exit', () => {
 expect(fillEvents(detail).map(x => [x.id, x.price, x.time])).toEqual([
 ['a:entry', 43.125, 1700000000], ['a:exit', 39.875, 1700000000], ['open:entry', 40.25, 1700000000],
 ]);
});
it('never snaps a fill from another session to a candle', () => {
 const changed = {...detail, trades: [{...detail.trades[0], entry_time: 1699999999}]};
 expect(fillEvents(changed).find(x => x.id === 'a:entry')?.candleTime).toBeNull();
});
