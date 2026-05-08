import type { AlertKind, TargetLevel } from '@/types/domain';

export interface AlertPosition {
  symbol: string;
  contract: string;
  currentPrice: number;
  entryPrice: number;
  stop: number;
  targets: TargetLevel[];
  dteRemaining: number;
  dteTotal: number;
  pnlPct: number;
  nextEventDays?: number;
  nextEventLabel?: string;
}

export interface AlertReason {
  kind: AlertKind;
  symbol: string;
  reason: string;
}

export function scanPortfolio(positions: AlertPosition[]): AlertReason[] {
  const out: AlertReason[] = [];

  for (const p of positions) {
    // TP_HIT
    const firstTarget = p.targets[0];
    if (firstTarget && p.currentPrice >= firstTarget.stockPrice) {
      out.push({
        kind: 'Action',
        symbol: p.symbol,
        reason: `Target reached — ${p.symbol} at $${p.currentPrice.toFixed(2)}`,
      });
    }

    // STOP_REACHED — using currentPrice as stock-price proxy per spec
    if (p.currentPrice < p.stop) {
      out.push({
        kind: 'Critical',
        symbol: p.symbol,
        reason: `Stop breached — ${p.symbol} below $${p.stop.toFixed(2)}`,
      });
    }

    // PREMIUM_STOP — option lost 50% of value
    if (p.pnlPct <= -50) {
      out.push({
        kind: 'Critical',
        symbol: p.symbol,
        reason: `Premium stop — ${p.symbol} down ${p.pnlPct.toFixed(1)}%`,
      });
    }

    // TIME_STOP_APPROACHING
    const timeStopThreshold = Math.ceil(p.dteTotal * 0.3);
    if (p.dteRemaining <= timeStopThreshold) {
      out.push({
        kind: 'Action',
        symbol: p.symbol,
        reason: `Time stop approaching — ${p.dteRemaining} DTE (≤${timeStopThreshold})`,
      });
    }

    // EARNINGS_APPROACHING
    if (p.nextEventDays !== undefined && p.nextEventDays <= 3) {
      out.push({
        kind: 'Action',
        symbol: p.symbol,
        reason: `${p.nextEventLabel ?? 'Event'} in ${p.nextEventDays} days — ${p.symbol}`,
      });
    }

    // EXPIRATION_APPROACHING
    if (p.dteRemaining <= 3) {
      out.push({
        kind: 'Critical',
        symbol: p.symbol,
        reason: `Expiration approaching — ${p.dteRemaining} DTE`,
      });
    }
  }

  return out;
}
