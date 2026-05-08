import type { AlertKind, AlertType, TargetLevel } from '@/types/domain';
import { useScanStore } from '@/lib/scanStore';

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

export function scanPortfolio(positions: AlertPosition[]): AlertReason[] {
  const conflicted = useScanStore.getState().conflictedSymbols;
  const out: AlertReason[] = [];

  for (const p of positions) {
    if (conflicted && conflicted.includes(p.symbol)) continue;

    // TP_HIT
    const firstTarget = p.targets[0];
    if (firstTarget && p.currentPrice >= firstTarget.stockPrice) {
      out.push({
        recId: p.recId,
        kind: 'Action',
        symbol: p.symbol,
        alertType: 'TP_HIT',
        reason: `Target reached — ${p.symbol} at $${p.currentPrice.toFixed(2)}`,
      });
    }

    // STOP_REACHED
    if (p.currentPrice <= p.stop) {
      out.push({
        recId: p.recId,
        kind: 'Critical',
        symbol: p.symbol,
        alertType: 'STOP_REACHED',
        reason: `Stop breached — ${p.symbol} below $${p.stop.toFixed(2)}`,
      });
    }

    // PREMIUM_STOP — option lost 40%+ (entry * 0.60 threshold)
    if (p.pnlPct <= -40) {
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
    if (p.nextEventDays !== undefined && p.nextEventDays <= 3) {
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