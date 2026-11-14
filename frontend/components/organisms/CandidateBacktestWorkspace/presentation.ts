import type { BacktestTrade, DetailedBacktestResult } from '@/types/backtest';

export type PerformanceUnit = 'percent' | 'index';
export interface ValueSample { time: number; value: number; }
export interface TimeBounds { from: number; to: number; }

/** Missing/invalid curves are unavailable as a whole, never bridged or rebased. */
export function performanceSeries(detail: DetailedBacktestResult, unit: PerformanceUnit) {
 const curve = (key: 'strategy_index' | 'benchmark_index'): ValueSample[] | null => {
  if (!detail.equity.length || detail.equity.some(row => !Number.isFinite(row.time) || !Number.isFinite(row[key]))) return null;
  const rows = detail.equity.map(row => ({time: row.time, value: row[key] - (unit === 'percent' ? 100 : 0)}));
  return rows.every(row => Number.isFinite(row.value)) ? rows : null;
 };
 return {strategy: curve('strategy_index'), benchmark: curve('benchmark_index')};
}

/** Engine summary definitions remain distinct from the chart's equity returns. */
export function performanceSummary(detail: DetailedBacktestResult) {
 const curves = performanceSeries(detail, 'index');
 const strategy = curves.strategy?.at(-1) ?? null;
 const benchmark = curves.benchmark?.at(-1) ?? null;
 const difference = strategy && benchmark ? strategy.value - benchmark.value : null;
 return {
  engineReturn: detail.summary.total_return_pct,
  engineMaxDrawdown: detail.summary.max_drawdown_pct,
  closedTrades: detail.summary.n_trades,
  winRate: detail.summary.win_rate,
  strategyReturn: strategy ? strategy.value - 100 : null,
  benchmarkReturn: benchmark ? benchmark.value - 100 : null,
  difference: difference !== null && Number.isFinite(difference) ? difference : null,
  time: strategy?.time ?? benchmark?.time ?? null,
 };
}

/** Compute against the complete history before applying any display range. */
export function sampledDrawdown(detail: DetailedBacktestResult): ValueSample[] | null {
 let peak = detail.initial_equity;
 if (!Number.isFinite(peak) || peak <= 0 || !detail.equity.length) return null;
 const result: ValueSample[] = [];
 for (const sample of detail.equity) {
  if (!Number.isFinite(sample.time) || !Number.isFinite(sample.equity)) return null;
  peak = Math.max(peak, sample.equity);
  const value = 100 * (sample.equity / peak - 1);
  if (!Number.isFinite(value)) return null;
  result.push({time: sample.time, value});
 }
 return result;
}

/** Formatting is the only rounding boundary; values carry no assumed currency. */
export function formatValue(value: number | null | undefined): string {
 return value != null && Number.isFinite(value) ? value.toFixed(2) : 'Unavailable';
}

export function exactSample<T extends {time: number}>(rows: readonly T[], time: number | null | undefined): T | null {
 return time != null && Number.isFinite(time) ? rows.find(row => row.time === time) ?? null : null;
}

/** Bounds include both panes, without assuming matching candles/equity sessions. */
export function recordedBounds(detail: DetailedBacktestResult): TimeBounds | null {
 let from = Infinity, to = -Infinity;
 for (const row of [...detail.candles, ...detail.equity]) {
  if (!Number.isFinite(row.time)) return null;
  from = Math.min(from, row.time); to = Math.max(to, row.time);
 }
 return Number.isFinite(from) && Number.isFinite(to) ? {from, to} : null;
}

export function clampBounds(requested: TimeBounds, available: TimeBounds | null): TimeBounds | null {
 if (!available || ![requested.from, requested.to, available.from, available.to].every(Number.isFinite) || requested.from > requested.to || available.from > available.to) return null;
 const clamp = (time: number) => Math.max(available.from, Math.min(available.to, time));
 return {from: clamp(requested.from), to: clamp(requested.to)};
}

/** A UTC calendar year, with Feb 29 clamped to Feb 28 rather than March 1. */
export function displayBounds(detail: DetailedBacktestResult, range: 'all' | 'year'): TimeBounds | null {
 const bounds = recordedBounds(detail);
 if (!bounds || range === 'all') return bounds;
 const start = new Date(bounds.to * 1000);
 if (!Number.isFinite(start.getTime())) return null;
 const month = start.getUTCMonth();
 start.setUTCFullYear(start.getUTCFullYear() - 1);
 if (start.getUTCMonth() !== month) start.setUTCDate(0);
 return clampBounds({from: start.getTime() / 1000, to: bounds.to}, bounds);
}

export type TradeSortKey = keyof BacktestTrade;
/** Pages contain the original recorded trade objects; selection always uses id. */
export function tradePage(trades: readonly BacktestTrade[], key: TradeSortKey, direction: 'asc' | 'desc', requestedPage: number, requestedPageSize: number) {
 const pageSize = Number.isFinite(requestedPageSize) ? Math.max(1, Math.floor(requestedPageSize)) : 10;
 const compare = (a: string | number, b: string | number) => a < b ? -1 : a > b ? 1 : 0;
 const rows = [...trades].sort((a, b) => {
  const first = a[key], second = b[key];
  const invalidA = typeof first === 'number' && !Number.isFinite(first);
  const invalidB = typeof second === 'number' && !Number.isFinite(second);
  if (invalidA !== invalidB) return invalidA ? 1 : -1;
  return ((!invalidA ? compare(first, second) : 0) * (direction === 'asc' ? 1 : -1)) || compare(a.id, b.id);
 });
 const pageCount = Math.ceil(rows.length / pageSize);
 const page = Math.max(0, Math.min(Math.max(0, pageCount - 1), Number.isFinite(requestedPage) ? Math.floor(requestedPage) : 0));
 return {rows: rows.slice(page * pageSize, (page + 1) * pageSize), page, pageCount, total: rows.length};
}

/** Display-only sign: positive values carry '+', zero and negatives keep toFixed's own text. */
export function formatSigned(value: number | null | undefined): string {
 const text = formatValue(value);
 return text !== 'Unavailable' && (value as number) > 0 ? `+${text}` : text;
}

/** Return % is index - 100 (signed, with %); Index 100 is the raw recorded index. */
export function formatPerformance(value: number | null | undefined, unit: PerformanceUnit): string {
 if (unit === 'index') return formatValue(value);
 const text = formatSigned(value);
 return text === 'Unavailable' ? text : `${text}%`;
}

export type ComparisonOutcome = 'strategy_ahead' | 'holding_ahead' | 'equal' | 'missing';
/** Deterministic wording from the unrounded final indices of one shared recorded sample. */
export function performanceComparison(detail: DetailedBacktestResult) {
 const summary = performanceSummary(detail);
 const engineReturn = summary.engineReturn;
 const indexedReturn = summary.strategyReturn;
 const engineDiffers = indexedReturn !== null && Number.isFinite(engineReturn) && engineReturn !== indexedReturn;
 const strategy = formatPerformance(summary.strategyReturn, 'percent');
 const benchmark = formatPerformance(summary.benchmarkReturn, 'percent');
 const base = {engineReturn, indexedReturn, engineDiffers, difference: summary.difference};
 if (summary.strategyReturn === null || summary.benchmarkReturn === null || summary.difference === null) {
  return {...base, outcome: 'missing' as ComparisonOutcome, headline: 'Comparison unavailable.',
   sentence: `Recorded strategy equity return: ${strategy}; long buy-and-hold return: ${benchmark}. Both final recorded indices are required to compare them.`};
 }
 const outcome: ComparisonOutcome = summary.difference > 0 ? 'strategy_ahead' : summary.difference < 0 ? 'holding_ahead' : 'equal';
 const headline = outcome === 'strategy_ahead' ? 'Recorded strategy equity finished ahead of long buy-and-hold.'
  : outcome === 'holding_ahead' ? 'Long buy-and-hold finished ahead of recorded strategy equity.'
  : 'Recorded strategy equity and long buy-and-hold finished level.';
 return {...base, outcome, headline,
  sentence: `Recorded strategy equity returned ${strategy}; long buy-and-hold returned ${benchmark}; difference ${formatSigned(summary.difference)} percentage points over the full recorded period.`};
}

/** Final recorded values by default; a hovered timestamp reads exact samples only (never the nearest). */
export function legendReadout(detail: DetailedBacktestResult, unit: PerformanceUnit, time: number | null) {
 const curves = performanceSeries(detail, unit);
 if (time === null) {
  const strategy = curves.strategy?.at(-1) ?? null, benchmark = curves.benchmark?.at(-1) ?? null;
  return {time: strategy?.time ?? benchmark?.time ?? null, hovered: false, strategy: strategy?.value ?? null, benchmark: benchmark?.value ?? null};
 }
 const at = (rows: ValueSample[] | null) => rows ? exactSample(rows, time)?.value ?? null : null;
 return {time, hovered: true, strategy: at(curves.strategy), benchmark: at(curves.benchmark)};
}

/** Latest and deepest sampled-equity drawdown; unavailable when the derived series is. */
export function drawdownReadout(samples: ValueSample[] | null) {
 if (!samples?.length) return {latest: null, deepest: null};
 return {latest: samples[samples.length - 1].value, deepest: Math.min(...samples.map(row => row.value))};
}
