import type { AlertKind, AlertType, TargetLevel, Direction } from '@/types/domain';

export interface AlertPosition {
  recId: string;
  symbol: string;
  contract: string;
  currentPrice: number;
  entryPrice: number;
  stop: number;
  targets: TargetLevel[];
  dteRemaining: number;
  dteTotal: number;
  pnlPct: number;
  direction: Direction;
  nextEventDays?: number;
  nextEventLabel?: string;
}

export interface AlertReason {
  recId: string;
  kind: AlertKind;
  symbol: string;
  alertType: AlertType;
  reason: string;
}

export interface ScanOptions {
  premiumStopPct?: number;  // fraction of premium lost at stop; default 0.60
}

export function scanPortfolio(
  positions: AlertPosition[],
  options: ScanOptions = {},
): AlertReason[] {
  const premiumStopPct = options.premiumStopPct ?? 0.60;
  const premiumStopThreshold = -(premiumStopPct * 100);  // e.g. -60 for 0.60

  const out: AlertReason[] = [];

  for (const p of positions) {
    const isBearish = p.direction === 'Bearish';

    // TP_HIT — direction-aware: bullish targets are above current price, bearish below
    const firstTarget = p.targets[0];
    const tpHit = firstTarget
      ? (isBearish ? p.currentPrice <= firstTarget.stockPrice : p.currentPrice >= firstTarget.stockPrice)
      : false;
    if (tpHit) {
      out.push({
        recId: p.recId,
        kind: 'Action',
        symbol: p.symbol,
        alertType: 'TP_HIT',
        reason: `Target reached — ${p.symbol} at $${p.currentPrice.toFixed(2)}`,
      });
    }

    // STOP_REACHED — direction-aware: puts/shorts are invalidated when price rises above stop.
    // `p.stop > 0` guards positions with no stop set: portfolioStore.ts:47 coerces a
    // null backend stop to 0 before it reaches this function (AlertPosition.stop is
    // non-optional), so the null/unset case is invisible here — without this guard,
    // a Bearish position with no stop would satisfy `currentPrice >= 0` on virtually
    // every poll (any real stock price is positive), firing a spurious Critical alert
    // every 30 seconds. The backend's equivalent check (alert_generator.py:109-112)
    // guards this explicitly via `pos.stop is not None`; `stop > 0` is this function's
    // only available proxy for the same condition since the null information is
    // already lost by the time data reaches here. (Bullish positions were already
    // safe from this by coincidence — currentPrice <= 0 is never true for a real
    // price — this guard makes that safety explicit for both directions instead of
    // relying on it remaining a coincidence.)
    const stopBreached = p.stop > 0 && (isBearish ? p.currentPrice >= p.stop : p.currentPrice <= p.stop);
    if (stopBreached) {
      out.push({
        recId: p.recId,
        kind: 'Critical',
        symbol: p.symbol,
        alertType: 'STOP_REACHED',
        reason: `Stop breached — ${p.symbol} ${isBearish ? 'above' : 'below'} $${p.stop.toFixed(2)}`,
      });
    }

    // PREMIUM_STOP — option lost premiumStopPct of its value
    if (p.pnlPct <= premiumStopThreshold) {
      out.push({
        recId: p.recId,
        kind: 'Critical',
        symbol: p.symbol,
        alertType: 'PREMIUM_STOP',
        reason: `Premium stop — ${p.symbol} down ${p.pnlPct.toFixed(1)}%`,
      });
    }

    // TIME_STOP — expiry within 3 days
    if (p.dteRemaining <= 3) {
      out.push({
        recId: p.recId,
        kind: 'Action',
        symbol: p.symbol,
        alertType: 'TIME_STOP',
        reason: `Time stop — ${p.symbol} ${p.dteRemaining} DTE`,
      });
    }

    // EVENT_RISK
    if (p.nextEventDays != null && p.nextEventDays <= 3) {
      out.push({
        recId: p.recId,
        kind: 'Action',
        symbol: p.symbol,
        alertType: 'EVENT_RISK',
        reason: `${p.nextEventLabel ?? 'Event'} in ${p.nextEventDays} days — ${p.symbol}`,
      });
    }
  }

  return out;
}