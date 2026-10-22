import type { DetailedBacktestResult } from '@/types/backtest';

/** Server indexes retain the engine baseline, even after zooming. */
export function historicalSeries(detail: DetailedBacktestResult) {
 return {
  candles: detail.candles.map(({time,open,high,low,close}) => ({time,open,high,low,close})),
  strategy: detail.equity.map(s => ({time:s.time,value:s.strategy_index})),
  benchmark: detail.equity.map(s => ({time:s.time,value:s.benchmark_index})),
 };
}
export function fillEvents(detail: DetailedBacktestResult) {
 const candleTimes = new Set(detail.candles.map(c => c.time));
 const event = (id:string, tradeId:string, time:number, price:number, kind:'entry'|'exit', direction:string) => ({id,tradeId,time,price,kind,direction,candleTime:candleTimes.has(time)?time:null});
 return [
  ...detail.trades.flatMap(t => [event(`${t.id}:entry`,t.id,t.entry_time,t.entry_price,'entry',t.direction),event(`${t.id}:exit`,t.id,t.exit_time,t.exit_price,'exit',t.direction)]),
  ...detail.open_positions.map(t => event(`${t.id}:entry`,t.id,t.entry_time,t.entry_price,'entry',t.direction)),
 ].sort((a,b) => a.time-b.time);
}
export const utc = (time:number) => new Date(time*1000).toISOString();
