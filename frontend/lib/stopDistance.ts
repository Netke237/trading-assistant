import type { Direction } from '@/types/domain';
import { isShortStockPosition, percentStopFiringPrice, resolvePremiumStopPct, premiumStopPctLabel } from '@/lib/premiumStop';

export interface StockStopDistance {
  formatted: string;
  stopPrice: number;
  dollarDelta: number | null;
  pctDelta: number | null;
  notRecorded: boolean;
}

/**
 * Computes direction-aware distance of a stock stop or structural stop level
 * from the stock entry price (#630).
 *
 * For Bullish: adverse move toward stop is below entry -> dollarDelta = stop - entry (negative).
 * For Bearish: adverse move toward stop is above entry -> dollarDelta = entry - stop (negative).
 * When stop has trailed into profit, dollarDelta is positive.
 *
 * Returns null if stop is unset/non-positive/non-finite.
 * Returns formatted "— (not recorded)" if entryStockPrice is unset/null/non-finite (legacy rows).
 */
export function formatStockStopDistance(
  stopPrice: number | null | undefined,
  entryStockPrice: number | null | undefined,
  direction: Direction,
): string | null {
  if (stopPrice == null || !Number.isFinite(stopPrice) || stopPrice <= 0) {
    return null;
  }

  const stopStr = `$${stopPrice.toFixed(2)}`;

  if (entryStockPrice == null || !Number.isFinite(entryStockPrice) || entryStockPrice <= 0) {
    return `${stopStr} · — (not recorded)`;
  }

  const isBearish = direction === 'Bearish';
  const dollarDelta = isBearish ? entryStockPrice - stopPrice : stopPrice - entryStockPrice;
  const pctDelta = (dollarDelta / entryStockPrice) * 100;

  let deltaStr: string;
  if (Math.abs(dollarDelta) < 0.005) {
    deltaStr = '$0.00 / 0.0% from entry';
  } else if (dollarDelta < 0) {
    deltaStr = `−$${Math.abs(dollarDelta).toFixed(2)} / −${Math.abs(pctDelta).toFixed(1)}% from entry`;
  } else {
    deltaStr = `+$${dollarDelta.toFixed(2)} / +${pctDelta.toFixed(1)}% from entry`;
  }

  return `${stopStr} · ${deltaStr}`;
}

/**
 * Computes distance of a premium stop from the option/stock entry price (#630).
 *
 * For options / long stock: fires at entry * (1 - pct). Formatted as:
 *   e.g. "$1.20 · −60% of $3.00"
 * For short stock: fires at entry * (1 + pct) on a rise (adverse loss). Formatted as:
 *   e.g. "$55.00 · −$5.00 / −10.0% from entry"
 */
export function formatPremiumStopDistance(
  entryPrice: number | null | undefined,
  premiumStopPct: number | null | undefined,
  globalPremiumStopPct: number,
  contract: string,
  direction: Direction,
): string | null {
  if (entryPrice == null || !Number.isFinite(entryPrice) || entryPrice <= 0) {
    return null;
  }

  const shortStock = isShortStockPosition(contract, direction);
  const effectivePct = resolvePremiumStopPct(premiumStopPct, globalPremiumStopPct);
  if (!Number.isFinite(effectivePct) || effectivePct <= 0) {
    return null;
  }

  const firingPrice = percentStopFiringPrice(entryPrice, effectivePct, shortStock);

  if (shortStock) {
    const dollarDelta = entryPrice - firingPrice; // adverse loss is negative
    const pctDelta = (dollarDelta / entryPrice) * 100;
    return `$${firingPrice.toFixed(2)} · −$${Math.abs(dollarDelta).toFixed(2)} / −${Math.abs(pctDelta).toFixed(1)}% from entry`;
  }

  const pctLabel = premiumStopPctLabel(effectivePct);
  return `$${firingPrice.toFixed(2)} · −${pctLabel} of $${entryPrice.toFixed(2)}`;
}
