/** Selectively adapted from PR #224 head 5e8a2d2. Applied overrides truncate
 * integer fields like the backend router. Snapshots follow result-array identity
 * in memory across page remount, without changing the persisted scan store. */
import type { PreBreakoutParams } from '@/components/organisms/PreBreakoutParamsPanel';
import type { FibPullbackParams } from '@/components/organisms/FibPullbackParamsPanel';

/** The Pre-Breakout params with the backend's integer keys truncated as `int()` does. */
export function truncPreBreakoutInts(p: PreBreakoutParams): PreBreakoutParams {
  return {
    ...p,
    atrAvgLookback:    Math.trunc(p.atrAvgLookback),
    rangeLookbackBars: Math.trunc(p.rangeLookbackBars),
    swingLookback:     Math.trunc(p.swingLookback),
  };
}

/** The Fib params with the backend's integer keys truncated as `int()` does. */
export function truncFibInts(p: FibPullbackParams): FibPullbackParams {
  return {
    ...p,
    fibLevels:        [...p.fibLevels],
    fibSwingLookback: Math.trunc(p.fibSwingLookback),
    emaFilterPeriod:  Math.trunc(p.emaFilterPeriod),
  };
}

/**
 * A threshold as text, without lossy rounding: the value to 6 decimals with
 * trailing zeros dropped, padded back to at least `minDecimals` decimals.
 * 0.85 → "0.85", (3, 1) → "3.0", 0.875 → "0.875", 0.0725 × 100 → "7.25".
 * At the panels' step values this is the same text as `toFixed(minDecimals)`.
 */
export function fmtThreshold(x: number, minDecimals: number): string {
  if (!Number.isFinite(x)) return String(x);
  const s = String(Number(x.toFixed(6)));
  const dot = s.indexOf('.');
  const decimals = dot < 0 ? 0 : s.length - dot - 1;
  if (decimals >= minDecimals) return s;
  return (dot < 0 ? `${s}.` : s) + '0'.repeat(minDecimals - decimals);
}

// Snapshots follow the exact in-memory result array. Replaced/legacy arrays have no snapshot.
export type ScanMode = 'prebreakout' | 'pullback' | 'fib';
export interface ScanScope { mode: ScanMode; direction: string; horizon: string | undefined; symbols: readonly string[]; universe: readonly string[] | undefined; runId: string | null; }
export interface ScanSnapshot { scope: Readonly<ScanScope>; pre?: PreBreakoutParams; fib?: FibPullbackParams; pullback?: { emaPeriod: number; trendEma: number }; }
const snapshots = new WeakMap<object, ScanSnapshot>();
export function rememberScan(rows: object, snapshot: ScanSnapshot): void { snapshots.set(rows, snapshot); }
export function scanSnapshot(rows: object): ScanSnapshot | undefined { return snapshots.get(rows); }
