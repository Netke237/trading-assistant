/** Scan-level plotting selectively adapted from PR #224 head 5e8a2d2.
 * These are returned setup evidence, never entry, stop or target prices. */
import type { FibSwing } from '@/types/stockDomain';
import type { ScanMode } from './scanThresholds';

export interface ScanPriceLine { price: number; title: string; }
interface ChartEvidence {
  direction: string;
  metrics?: Record<string, number>;
  fib_level_hit?: string;
  fib_swing?: FibSwing | null;
}
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const FIB_RATIOS = new Map([[23.6, .236], [38.2, .382], [50, .5], [61.8, .618], [78.6, .786]]);

export function fibLevelPrice(direction: string, label: string, low: number, high: number): number | null {
  if (!finite(low) || !finite(high) || !/^(?:\d+(?:\.\d+)?)%?$/.test(label.trim())) return null;
  const ratio = FIB_RATIOS.get(Number(label.trim().replace(/%$/, '')));
  if (ratio === undefined || (direction !== 'Bullish' && direction !== 'Bearish')) return null;
  const price = direction === 'Bullish' ? high - ratio * (high - low) : low + ratio * (high - low);
  return finite(price) ? price : null;
}

export function scanChartLines(row: ChartEvidence, mode: ScanMode): ScanPriceLine[] {
  if (mode === 'pullback') return [];
  const lines: ScanPriceLine[] = [];
  if (mode === 'prebreakout' && finite(row.metrics?.swing_level)) {
    const side = row.direction === 'Bullish' ? 'high' : row.direction === 'Bearish' ? 'low' : 'level';
    lines.push({price: row.metrics.swing_level, title: `Scan swing ${side}`});
  }
  const low = row.fib_swing?.low;
  const high = row.fib_swing?.high;
  const prefix = mode === 'prebreakout' ? 'Scan Fib swing' : 'Scan swing';
  if (finite(low)) lines.push({price: low, title: `${prefix} low`});
  if (finite(high)) lines.push({price: high, title: `${prefix} high`});
  if (mode === 'fib' && finite(low) && finite(high) && row.fib_level_hit != null) {
    const price = fibLevelPrice(row.direction, row.fib_level_hit, low, high);
    if (price != null) lines.push({price, title: `Scan Fib ${row.fib_level_hit.trim().replace(/%$/, '')}%`});
  }
  return lines;
}
