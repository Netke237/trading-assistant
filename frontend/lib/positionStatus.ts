import type { Status } from '@/lib/status';
import type { PortfolioPosition } from '@/types/domain';
import { scanPortfolio, STOP_PROXIMITY_PCT, TIME_STOP_DTE } from '@/lib/alertEngine';

export type PositionBreach = 'stop' | 'structural' | 'premium' | null;

export interface DerivedPositionStatus {
  status: Status;
  reason: string;
  breach: PositionBreach;
}

/** Portfolio row status, derived at render from the same engine the alerts use.
 *
 *  Breaches come from `scanPortfolio` itself (per-position alert overrides
 *  removed, every alert type on), so the badge and the alert cannot disagree.
 *  `scanPortfolio` reads the real clock for a stock hold; this function takes
 *  no clock of its own for that reason. */
export function derivePositionStatus(
  p: PortfolioPosition,
  opts: { premiumStopPct: number },
): DerivedPositionStatus {
  const isStock = p.contract.endsWith('|STOCK');
  const isBearish = p.direction === 'Bearish';
  const underlying = isStock ? p.currentPrice : (p.currentStockPrice ?? 0);
  const hasUnderlying = underlying > 0;

  const types = new Set(
    scanPortfolio([{ ...p, alertOverrides: {} }], { premiumStopPct: opts.premiumStopPct })
      .map(r => r.alertType),
  );

  if (types.has('STOP_REACHED')) return { status: 'REJECT', reason: 'Stop breached', breach: 'stop' };
  if (types.has('STRUCTURAL_STOP_BREACHED')) return { status: 'REJECT', reason: 'Structural stop breached', breach: 'structural' };
  if (types.has('PREMIUM_STOP')) return { status: 'REJECT', reason: 'Premium stop hit', breach: 'premium' };

  const noOptionQuote = !isStock && (p.quoteUnavailable === true || p.currentPrice <= 0);
  if (isStock ? (p.quoteUnavailable === true || p.currentPrice <= 0) : (noOptionQuote && !hasUnderlying)) {
    return { status: 'NO_DATA', reason: 'No quote', breach: null };
  }

  if (hasUnderlying) {
    const side = isBearish ? 'below' : 'above';
    const candidates: { dist: number; label: string }[] = [];
    const add = (level: number | null | undefined, label: string) => {
      if (level == null) return;
      // Safe side: bullish keeps the underlying above the level, bearish below.
      const dist = (isBearish ? level - underlying : underlying - level) / underlying;
      if (dist >= 0 && dist <= STOP_PROXIMITY_PCT) candidates.push({ dist, label });
    };
    add(p.stop, 'stop');
    add(p.structuralStop, 'struct. stop');
    if (candidates.length > 0) {
      const nearest = candidates.reduce((a, b) => (b.dist < a.dist ? b : a));
      return { status: 'CAUTION', reason: `${(nearest.dist * 100).toFixed(1)}% ${side} ${nearest.label}`, breach: null };
    }
  }

  if (types.has('TIME_STOP')) {
    return {
      status: 'CAUTION',
      reason: isStock ? `Hold ${p.holdMaxDays}d reached` : `≤${TIME_STOP_DTE} DTE`,
      breach: null,
    };
  }
  if (noOptionQuote && hasUnderlying) return { status: 'CAUTION', reason: 'No option quote', breach: null };

  return { status: 'PASS', reason: types.has('TP_HIT') ? 'Target 1 reached' : 'Between stop and T1', breach: null };
}
