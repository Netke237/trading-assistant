import type { Direction, PortfolioPosition, TargetLevel } from '@/types/domain';
import type { PositionCardData } from '@/types/stockDomain';

/** One rung of a stock exit ladder, before sanitizing. */
export interface StockTargetInput {
  price:   number;
  shares?: number;
}

export interface StockLevels {
  stop:    number | null;
  targets: TargetLevel[];
}

/**
 * Turn a raw (entry, stop, ladder) triple into the exact `{ stop, targets }` pair
 * `PortfolioPosition` wants, dropping anything that would be meaningless or actively
 * dangerous downstream.
 *
 * Why each rule exists:
 *  - `portfolioStore.floorStop()` maps any non-positive stop to `null` ("unset") at all
 *    eight of its documented entry points, so sending `0` LOOKS like it worked and
 *    silently no-ops. This returns `null` explicitly instead, never `0`.
 *  - A stop on the wrong side of entry (bullish stop above entry) is a data error, and
 *    `alert_generator.py`'s STOP_REACHED comparison would treat it as breached on the
 *    very first tick — a real notification for a position that is fine. Dropped.
 *  - `alert_generator.py:93` fires TP_HIT against `targets[0]` and nothing else, so the
 *    ladder MUST be nearest-first; a user is free to type T1 > T2 in the card, so the
 *    ordering is enforced here rather than trusted. Share allocations travel with their
 *    price through the sort.
 *  - Both `stockPrice` and `targetPrice` are written. Only `stockPrice` is read today
 *    (by TP_HIT and the portfolio drawer), but `POST /api/portfolio`'s re-anchor branch
 *    does `(t.get("targetPrice") or 0) + delta`, which would turn a missing field into a
 *    bogus small number if that branch is ever enabled for stocks.
 */
export function stockPositionLevels(
  entry: number,
  direction: Direction,
  stop: number | null | undefined,
  targets: ReadonlyArray<StockTargetInput> = [],
): StockLevels {
  const sign = direction === 'Bullish' ? 1 : -1;
  const entryOk = Number.isFinite(entry) && entry > 0;

  const safeStop =
    entryOk && stop != null && Number.isFinite(stop) && stop > 0 && sign * (entry - stop) > 0
      ? Math.round(stop * 100) / 100
      : null;

  const rungs = entryOk
    ? targets
        .filter((t) => Number.isFinite(t.price) && t.price > 0 && sign * (t.price - entry) > 0)
        .map((t) => ({
          price: Math.round(t.price * 100) / 100,
          shares: t.shares != null && Number.isFinite(t.shares) && t.shares > 0
            ? Math.round(t.shares)
            : undefined,
        }))
        .sort((a, b) => sign * (a.price - b.price))
    : [];

  return {
    stop: safeStop,
    targets: rungs.map((r, i) => ({
      id: `T${i + 1}`,
      stockPrice: r.price,
      targetPrice: r.price,
      ...(r.shares != null ? { contractsToSell: r.shares } : {}),
      status: 'PENDING',
    })),
  };
}

/**
 * Prices from `targets` that `stockPositionLevels()` would silently drop —
 * on the wrong side of entry, non-finite, or non-positive — using the exact
 * same sign check. `EditableField.save()` on a T1/T2/T3 row accepts any
 * `price > 0` with no side check, so a fat-fingered target only surfaces
 * here: silently losing a rung (and the shares allocated to it) from the
 * sell-to-close plan with no indication anything happened would be worse
 * than the caller warning about it up front.
 */
export function invalidTargetRungs(
  entry: number,
  direction: Direction,
  targets: ReadonlyArray<{ price: number }>,
): number[] {
  if (!(Number.isFinite(entry) && entry > 0)) return targets.map((t) => t.price);
  const sign = direction === 'Bullish' ? 1 : -1;
  return targets
    .map((t) => t.price)
    .filter((price) => !(Number.isFinite(price) && price > 0 && sign * (price - entry) > 0));
}

// The "why was this bought" snapshot for the stocks path — attached once at
// buy time so it survives independent of later scans overwriting scanStore.
//
// This carries the PRISTINE strategy signal (`strategy`), which is the analytics /
// audit copy of the levels. The user's EDITED levels go into the live
// `PortfolioPosition.stop` / `.targets` fields, which are what the alert engine
// actually fires on. Passing `edited` here records the diff between the two, so the
// audit answer to "why was this bought, and at what levels" is complete rather than
// just a baseline. See the plan's "Pristine or edited?" decision.
export function stockCardSnapshotOf(
  c: PositionCardData,
  horizon: string,
  edited?: { entry: number; stop: number; targets: number[]; shares: number },
): Record<string, unknown> {
  return {
    ...(edited ? { edited } : {}),
    horizon,
    stock_score: c.stock_score,
    stock_status: c.stock_status,
    strategy: c.strategy,
    backtest: c.backtest,
    confidence: c.confidence,
    confidence_text: c.confidence_text,
    sector_rs_pct: c.sector_rs_pct,
    fundamentals: c.fundamentals,
  };
}

export function buildPaperStockPosition(
  symbol: string,
  price: number,
  shares: number,
  direction: Direction,
  snapshot?: Record<string, unknown>,
  levels?: {
    stop?: number | null;
    targets?: ReadonlyArray<StockTargetInput>;
    /** Optional chart-structure level; only set when the user ran "Check structure". */
    structuralStop?: number | null;
  },
): PortfolioPosition {
  const today = new Date().toISOString().slice(0, 10);
  // Levels are OPTIONAL by design: ChartWorkspace's manual buy has no strategy and
  // therefore genuinely has no stop. `null` (not 0) is what every layer already means
  // by "unset" — floorStop(), toBackendPayload(), and the backend's own _floor_stop.
  const { stop, targets } = stockPositionLevels(price, direction, levels?.stop, levels?.targets ?? []);
  const structuralStop =
    levels?.structuralStop != null && Number.isFinite(levels.structuralStop) && levels.structuralStop > 0
      ? Math.round(levels.structuralStop * 100) / 100
      : null;
  return {
    symbol,
    contract:     `${symbol}|STOCK`,
    direction,
    entryPrice:   price,
    contracts:    shares,
    entryDate:    today,
    expiry:       '',
    stop,
    structuralStop,
    targets,
    dteTotal:     0,
    dteRemaining: 0,
    status:       'PENDING',
    // Not 'PAPER-' — callers override `source` (spread + override) for
    // broker-executed positions built via this same helper (see
    // StockSendDialog/StockPositionCard/step-7-position-card's broker
    // branches), so a 'PAPER-' prefix here would mislabel a real broker
    // fill's internal id.
    // Date.now() alone is millisecond-resolution — a rapid double-click or
    // two quick fills queued back-to-back can call this twice within the
    // same millisecond and collide. Every other id generator in this
    // codebase (generateRecId in portfolioStore.ts, and the trade-card
    // recId sites) already appends a Math.random() suffix for exactly this
    // reason; this was the one outlier. A collision here isn't cosmetic —
    // recId is portfolioStore.addPosition's dedupe/merge key (a match
    // overwrites the earlier position, client-side) and a unique DB column
    // backend-side (the second POST hard-fails with a 500).
    recId:        'POS-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 6).toUpperCase(),
    currentPrice: price,
    pnlDollar:    0,
    pnlPct:       0,
    source:       'paper',
    tradeCardSnapshot: snapshot,
  };
}

/**
 * Shrink the sell-to-close rungs so they never sell more than `newQty` — the
 * card's own shrink rule, and IDENTICAL to the backend's
 * `position_writer.scale_rung_quantities`, so a resized row's local rungs agree
 * with the stored ones before the first sync (stock plan Q1/Q2/Z1).
 *
 * Only rungs with a positive `contractsToSell` take part. If they already sum
 * to `newQty` or less, the rungs are returned unchanged (a runner the user left
 * unallocated stays unallocated). Otherwise each such rung except the last
 * becomes floor(c × newQty / alloc) and the last takes the remainder, so they
 * sum to exactly `newQty`. Never grows a rung.
 */
export function scaleRungShares<T extends { contractsToSell?: number }>(
  targets: T[] | undefined,
  newQty: number,
): T[] | undefined {
  if (!targets) return targets;
  const qtyOf = (t: T): number | null =>
    typeof t.contractsToSell === 'number' && Number.isFinite(t.contractsToSell) && t.contractsToSell > 0
      ? Math.trunc(t.contractsToSell)
      : null;
  const idx = targets.flatMap((t, i) => (qtyOf(t) != null ? [i] : []));
  const alloc = idx.reduce((sum, i) => sum + (qtyOf(targets[i]!) ?? 0), 0);
  if (idx.length === 0 || alloc <= newQty) return targets;
  const out = targets.map((t) => ({ ...t }));
  let taken = 0;
  for (const i of idx.slice(0, -1)) {
    const c = Math.floor((qtyOf(targets[i]!)! * newQty) / alloc);
    out[i]!.contractsToSell = c;
    taken += c;
  }
  out[idx[idx.length - 1]!]!.contractsToSell = Math.max(0, newQty - taken);
  return out;
}
