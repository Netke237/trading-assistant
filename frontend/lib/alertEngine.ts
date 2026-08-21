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
  structuralStop?: number | null;
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
    // directly. `hasReferencePrice` suppresses these checks when no usable reference price is
    // available yet — for an option leg, that's `currentStockPrice` still unset (position just
    // opened and no live underlying quote has landed, or the quote fetch has been failing);
    // for a stock leg, `currentPrice` gets coerced to 0 on a failed fetch (portfolioStore.ts:
    // `p.currentPrice ?? 0`), and 0 is never a real stock price. `currentStockPrice` gets the
    // same `> 0` treatment for consistency, even though nothing currently sends it as exactly 0
    // — no reason for the two branches to rely on different "no real price" sentinels. Without
    // this guard a stale/missing reference price gets compared against the stop/target directly
    // — that false-fired a STOP_REACHED on a brand-new FTNT position where the $14 premium
    // tripped a $146 stock-price stop before the live underlying quote had loaded.
    const isStock = p.contract.endsWith('|STOCK');
    const hasReferencePrice = isStock ? p.currentPrice > 0 : (p.currentStockPrice ?? 0) > 0;
    // NaN, not p.currentPrice, when unusable: every consumer below already gates on
    // hasReferencePrice, but a future check added without that gate should get a value that
    // safely compares false everywhere (NaN <= x and NaN >= x are both false) instead of
    // silently falling back to the option premium — the exact bug this guard exists to prevent.
    const referencePrice = hasReferencePrice ? (isStock ? p.currentPrice : p.currentStockPrice!) : NaN;

    // TP_HIT — direction-aware: bullish targets are above current price, bearish below
    const firstTarget = p.targets[0];
    const tpHit = hasReferencePrice && firstTarget
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
    const stopBreached = hasReferencePrice && stop != null && (isBearish ? referencePrice >= stop : referencePrice <= stop);
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

    // STRUCTURAL_STOP_BREACHED — same direction-aware comparison as STOP_REACHED,
    // against the structural (order-block/swing) level instead of the
    // premium-based invalidation. `structuralStop != null` guards positions where
    // "Check structure" was never run before sending to broker — optional, unlike `stop`.
    const structuralStop = p.structuralStop;
    const structuralBreached = hasReferencePrice && structuralStop != null && (isBearish ? referencePrice >= structuralStop : referencePrice <= structuralStop);
    if (structuralBreached && structuralStop != null) {
      out.push({
        recId: p.recId,
        kind: 'Critical',
        symbol: p.symbol,
        alertType: 'STRUCTURAL_STOP_BREACHED',
        reason: `Structural stop breached — ${p.symbol} ${isBearish ? 'above' : 'below'} $${structuralStop.toFixed(2)} (price $${referencePrice.toFixed(2)})`,
        price: referencePrice,
        referenceValue: structuralStop,
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
