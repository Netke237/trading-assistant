import type { AlertKind, AlertType, TargetLevel, Direction } from '@/types/domain';

export interface AlertPosition {
  recId: string;
  symbol: string;
  contract: string;
  currentPrice: number;
  /** Live underlying stock price — see PortfolioPosition.currentStockPrice. For a stock
   *  position this always mirrors `currentPrice` (including its 0.0 fallback on a failed
   *  quote fetch); for an option position it's undefined when no live fetch has landed. */
  currentStockPrice?: number;
  entryPrice: number;
  stop: number | null;
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
  // Structured fields for position_alert_history — populated where the data
  // is actually available client-side; left undefined otherwise (e.g.
  // PREMIUM_STOP has no dollar price/threshold in scope here, only pnlPct).
  price?: number;
  referenceValue?: number;
  direction?: Direction;
  contract?: string;
  note?: string;
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

    // Shared by TP_HIT (below) and STOP_REACHED (further below) — both compare against an
    // underlying STOCK price (`firstTarget.stockPrice` / `stop`). For an option position,
    // `currentPrice` is the option PREMIUM, not comparable to either — use `currentStockPrice`
    // (the live underlying price fetched separately by the backend) instead. For a stock
    // position (`|STOCK` contract) `currentPrice` already IS the stock price, so it's used
    // directly. Falls back to `currentPrice` when `currentStockPrice` is unset (stale cached
    // data pre-dating this fix, or a failed live fetch) — this matches prior behavior rather
    // than silently skipping the check; do not "fix" this fallback away, every pre-existing
    // test in alertEngine.test.ts relies on it.
    const isStock = p.contract.endsWith('|STOCK');
    const referencePrice = isStock ? p.currentPrice : (p.currentStockPrice ?? p.currentPrice);

    // TP_HIT — direction-aware: bullish targets are above current price, bearish below
    const firstTarget = p.targets[0];
    const tpHit = firstTarget
      ? (isBearish ? referencePrice <= firstTarget.stockPrice : referencePrice >= firstTarget.stockPrice)
      : false;
    if (tpHit) {
      out.push({
        recId: p.recId,
        kind: 'Action',
        symbol: p.symbol,
        alertType: 'TP_HIT',
        reason: `Target reached — ${p.symbol} at $${referencePrice.toFixed(2)}`,
        price: referencePrice,
        referenceValue: firstTarget?.stockPrice,
        direction: p.direction,
        contract: p.contract,
      });
    }

    // STOP_REACHED — direction-aware: puts/shorts are invalidated when price rises above stop.
    // `stop != null` guards positions with no stop set — matches the backend's
    // equivalent check (alert_generator.py: `pos.stop is not None`) explicitly,
    // rather than relying on a `stop > 0` proxy for "unset" (that proxy broke
    // once `AlertPosition.stop`/`PortfolioPosition.stop` stopped being coerced
    // from null to 0 upstream in portfolioStore.ts).
    const stop = p.stop;
    const stopBreached = stop != null && (isBearish ? referencePrice >= stop : referencePrice <= stop);
    if (stopBreached && stop != null) {
      out.push({
        recId: p.recId,
        kind: 'Critical',
        symbol: p.symbol,
        alertType: 'STOP_REACHED',
        reason: `Stop breached — ${p.symbol} ${isBearish ? 'above' : 'below'} $${stop.toFixed(2)} (price $${referencePrice.toFixed(2)})`,
        price: referencePrice,
        referenceValue: stop,
        direction: p.direction,
        contract: p.contract,
      });
    }

    // PREMIUM_STOP — option lost premiumStopPct of its value. No dollar price/
    // threshold is available in this scope (only pnlPct), so price/referenceValue
    // are left undefined rather than mislabeled.
    if (p.pnlPct <= premiumStopThreshold) {
      out.push({
        recId: p.recId,
        kind: 'Critical',
        symbol: p.symbol,
        alertType: 'PREMIUM_STOP',
        reason: `Premium stop — ${p.symbol} down ${p.pnlPct.toFixed(1)}%`,
        direction: p.direction,
        contract: p.contract,
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
        referenceValue: p.dteRemaining,
        direction: p.direction,
        contract: p.contract,
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
        referenceValue: p.nextEventDays,
        direction: p.direction,
        contract: p.contract,
        note: p.nextEventLabel,
      });
    }
  }

  return out;
}
