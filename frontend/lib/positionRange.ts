/*
 * Portfolio "underlying vs stop / T1" range, shared by the table bar and its
 * text equivalent.
 *
 * Price axis: the bar always runs low price (left) to high price (right), so a
 * bullish row has its stop at the left and T1 at the right, and a bearish row
 * is the mirror (T1 left, stop right). `fraction` is the underlying's place on
 * that axis, 0 = left end, 1 = right end, clamped; `pinned` says which end it
 * is clamped to (a bar at an end means the level is reached or passed).
 * Without a T1 the bar has no right end, so `fraction` is null.
 *
 * Percentages are (level - underlying) / underlying * 100, so a level below
 * the underlying is negative. T1 is the price the TP_HIT alert uses
 * (`resolveTpPrice`).
 */

import type { PortfolioPosition } from '@/types/domain';
import { resolveTpPrice } from '@/lib/alertEngine';
import { formatSignedPct } from '@/lib/portfolioFormat';

export interface PositionRange {
  stop: number;
  structural: number | null;
  t1: number | null;
  underlying: number;
  fraction: number | null;
  pinned: 'left' | 'right' | null;
  stopPct: number;
  structPct: number | null;
  t1Pct: number | null;
  text: string;
}

export function positionRange(p: PortfolioPosition): PositionRange | null {
  const isStock = p.contract.endsWith('|STOCK');
  const underlying = isStock ? p.currentPrice : p.currentStockPrice;
  if (underlying == null || !Number.isFinite(underlying) || underlying <= 0) return null;
  if (p.stop == null || !Number.isFinite(p.stop)) return null;

  const stop = p.stop;
  const structural = p.structuralStop != null && Number.isFinite(p.structuralStop) ? p.structuralStop : null;
  const t1 = resolveTpPrice(p);
  const pct = (level: number) => ((level - underlying) / underlying) * 100;

  let fraction: number | null = null;
  let pinned: 'left' | 'right' | null = null;
  if (t1 != null && t1 !== stop) {
    const low = Math.min(stop, t1);
    const high = Math.max(stop, t1);
    const raw = (underlying - low) / (high - low);
    fraction = Math.min(1, Math.max(0, raw));
    pinned = raw <= 0 ? 'left' : raw >= 1 ? 'right' : null;
  }

  const parts = [`$${underlying.toFixed(2)}`, `stop ${formatSignedPct(pct(stop))}`];
  if (structural != null) parts.push(`struct ${formatSignedPct(pct(structural))}`);
  if (t1 != null) parts.push(`T1 ${formatSignedPct(pct(t1))}`);

  return {
    stop,
    structural,
    t1,
    underlying,
    fraction,
    pinned,
    stopPct: pct(stop),
    structPct: structural != null ? pct(structural) : null,
    t1Pct: t1 != null ? pct(t1) : null,
    text: parts.join(' · '),
  };
}
