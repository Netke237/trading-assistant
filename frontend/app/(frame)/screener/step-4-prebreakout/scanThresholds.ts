/**
 * STOCK-PRES-P5-PREBREAKOUT T2 — the parameters the backend applied to the
 * Pre-Breakout and Fib rows in memory, so every threshold the page prints
 * beside those rows is the one they were judged on.
 *
 * Why module-level: the rows live in `scanStore` (in memory, not persisted),
 * while the page's params are local `useState` reset to the defaults on every
 * mount. After leaving the page and coming back the rows remain but the live
 * params do not describe them. This state has the rows' lifetime: it survives
 * a remount and is lost on reload, together with the rows.
 *
 * What is stored is what the backend applied, not what was typed: the backend
 * coerces its integer override keys with Python `int()` (truncation toward
 * zero; `routers/stock_scan.py` `_INT_OVERRIDE_KEYS` / `_FIB_INT_OVERRIDE_KEYS`)
 * and uses the floats as sent. `Math.trunc` is the same truncation.
 */
import type { PreBreakoutParams } from '@/components/organisms/PreBreakoutParamsPanel';
import type { FibPullbackParams } from '@/components/organisms/FibPullbackParamsPanel';

let preBreakoutScanned: PreBreakoutParams | null = null;
let fibScanned: FibPullbackParams | null = null;

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

/** Call with the exact params the request was built from, just before storing its rows. */
export function rememberPreBreakoutScan(p: PreBreakoutParams): void {
  preBreakoutScanned = truncPreBreakoutInts(p);
}

/** The params the Pre-Breakout rows in memory were judged on; null before any scan this page load. */
export function preBreakoutScanParams(): PreBreakoutParams | null {
  return preBreakoutScanned;
}

/** Call with the exact params the request was built from, just before storing its rows. */
export function rememberFibScan(p: FibPullbackParams): void {
  fibScanned = truncFibInts(p);
}

/** The params the Fib rows in memory were judged on; null before any scan this page load. */
export function fibScanParams(): FibPullbackParams | null {
  return fibScanned;
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

export function __resetScanThresholdsForTests(): void {
  preBreakoutScanned = null;
  fibScanned = null;
}
