import type { AlertKind, AlertType, TargetLevel, Direction, AlertOverrides, PositionAlertType, TpMethod } from '@/types/domain';
import {
  resolvePremiumStopPct, percentStopThresholdPrice, isShortStockPosition, premiumStopSide,
  PREMIUM_STOP_PCT_FALLBACK, pythonRound4,
} from './premiumStop';
import type { PremiumStopSide } from './premiumStop';

/** An option position raises TIME_STOP at this many days to expiry or fewer.
 *
 *  One number for the browser engine's comparison below, TradeCard's
 *  "Time exit: 3 DTE" row and the Portfolio drawer's "3 DTE or less" text, so
 *  the card cannot promise an exit the alert does not make (decision Q8).
 *  Two readers are NOT tied to it and keep a literal 3: the backend's
 *  `alert_generator.py` (`<= 3`) and the Alerts page label
 *  (`app/(frame)/alerts/page.tsx`). Change all three together. */
export const TIME_STOP_DTE = 3;

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
  /** Per-position premium stop (piece 4). Null/absent inherits the global
   *  passed in `ScanOptions.premiumStopPct`. */
  premiumStopPct?: number | null;
  /** Which TP computation drives this position's TP_HIT (Feature D). Absent =
   *  'ladder'. Carried purely so the TP_HIT reason line can name the method
   *  that fired; the price itself comes from `resolvedTpPrice` below. */
  activeTpMethod?: TpMethod;
  /** Stock price the active TP method resolved to, snapshotted when the method
   *  was picked or re-computed. Null/absent for 'ladder', which reads
   *  `targets[0].stockPrice` live instead. */
  resolvedTpPrice?: number | null;
  /** Per-position alert-type overrides — absent key inherits the global
   *  `enabledTypes` decision (see `effectiveEnabled`). */
  alertOverrides?: AlertOverrides;
  /** STOCKS-HORIZON-T1 H6 -- ISO entry date (`YYYY-MM-DD`), read with
   *  `holdMaxDays` for a stock position's TIME_STOP. */
  entryDate?: string;
  /** STOCKS-HORIZON-T1 H6 -- the scan's hold in calendar days. Null/absent =
   *  no hold: a stock position never raises TIME_STOP. */
  holdMaxDays?: number | null;
}

/** STOCKS-HORIZON-T1 H6 -- whole calendar days from `entryDate` to today, both
 *  as LOCAL calendar dates (the backend's `date.today() - entry_date` on the
 *  server's local date). Null when the entry date does not parse. */
export function daysHeld(entryDate: string | undefined, now: Date = new Date()): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(entryDate ?? '');
  if (!m) return null;
  const entered = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  return Number.isFinite(entered) ? Math.round((today - entered) / 86_400_000) : null;
}

export interface AlertReason {
  recId: string;
  kind: AlertKind;
  symbol: string;
  alertType: AlertType;
  reason: string;
  // Structured fields for position_alert_history — populated where the data
  // is actually available client-side; left undefined otherwise. (PREMIUM_STOP
  // was the example here while it compared `pnlPct` and had no dollar figures
  // in scope; it resolves a threshold price now and populates both.)
  price?: number;
  referenceValue?: number;
  direction?: Direction;
  contract?: string;
  note?: string;
  /** PREMIUM_STOP only — the fraction this fire actually used, so the Alerts
   *  page can label the row with the threshold that fired rather than whatever
   *  the position resolves to when the row is later looked at
   *  (ALERT-THRESHOLD-STAMP-2026-09-05). */
  premiumStopPct?: number;
  /** PREMIUM_STOP only — the side rule this fire used (STOP-SEMANTICS-2026-10-02):
   *  'short-stock' fires on a RISE. Absent on every pre-deploy row. */
  stopSide?: PremiumStopSide;
}

export interface ScanOptions {
  /** GLOBAL premium-stop fraction — the fallback for positions that do not
   *  carry their own `premiumStopPct` (piece 4). Not the value every position
   *  uses; see the per-position resolution in the scan loop. Default 0.60. */
  premiumStopPct?: number;
  /** The user's global `AlertConfig.enabledTypes`. Threading this in is the
   *  Feature D toast-gating bugfix: before it, `enabledTypes` gated ONLY the
   *  outbound email/Telegram dispatch (backend `notify_alert`), so turning a
   *  type off in Settings still popped an in-app toast for it. Left undefined
   *  every type is treated as enabled — that keeps a caller that hasn't been
   *  updated (and the engine's own unit tests) on the pre-fix behavior rather
   *  than silently muting everything. */
  enabledTypes?: AlertType[];
}

/** Human label for the TP method that fired, appended to the TP_HIT reason so
 *  the alert says WHICH target was reached. 'ladder' is the historical default
 *  and stays unlabelled — its reason line is unchanged from before Feature D. */
const TP_METHOD_LABEL: Record<Exclude<TpMethod, 'ladder'>, string> = {
  monte_carlo:  'Monte Carlo target',
  exit_plan_2r: '2R exit plan',
  exit_plan_3r: '3R exit plan',
};

/** Resolve one alert type for one position: an explicit per-position override
 *  wins, an absent key inherits the global `enabledTypes` list.
 *
 *  `??` (not `||`) is load-bearing — an explicit `false` must beat a global
 *  "on", which `||` would swallow. Overrides are only consulted for the
 *  position-scoped types; a stray key for an account-wide type (REGIME_CHANGE,
 *  SCAN_*) can never reach here because those aren't raised per position.
 *
 *  Mirrors backend `alert_generator.effective_enabled` — keep the two in step. */
function effectiveEnabled(
  type: PositionAlertType,
  overrides: AlertOverrides | undefined,
  enabledTypes: AlertType[] | undefined,
): boolean {
  // A non-bool stored value (hand-edited JSON, an older shape) is treated as
  // absent rather than coerced — mirrors backend `alert_generator.effective_enabled`,
  // which does the same `isinstance(value, bool)` check, so a truthy non-bool
  // (e.g. the string "off") can't silently force a type on here while the
  // backend correctly falls back to the global setting for it.
  const override = overrides?.[type];
  const explicit = typeof override === 'boolean' ? override : undefined;
  return explicit ?? (enabledTypes ? enabledTypes.includes(type) : true);
}

export function scanPortfolio(
  positions: AlertPosition[],
  options: ScanOptions = {},
): AlertReason[] {
  // Piece 4 — the GLOBAL fallback only. The threshold is now resolved per
  // position inside the loop below, because a position may carry its own
  // premium stop; hoisting one threshold out here is exactly the bug that made
  // every open position share a single number.
  const globalPremiumStopPct = options.premiumStopPct ?? PREMIUM_STOP_PCT_FALLBACK;
  const { enabledTypes } = options;

  const out: AlertReason[] = [];

  for (const p of positions) {
    const isBearish = p.direction === 'Bearish';
    // Per-position override ?? global enabledTypes, resolved once per position.
    // Every alert branch below gates on this, so a muted type produces no
    // AlertReason at all — no toast, and (since alertStore.addToast is what
    // POSTs /api/alerts/notify) no email/Telegram either.
    const enabled = (type: PositionAlertType) =>
      effectiveEnabled(type, p.alertOverrides, enabledTypes);

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

    // TP_HIT — direction-aware: bullish targets are above current price, bearish below.
    // The price compared against is whatever the position's ACTIVE TP method
    // resolved to (Feature D): `resolvedTpPrice` is a snapshot stamped when the
    // method was picked or re-computed, exactly like `structuralStop`, and is
    // deliberately never recomputed here. It is null for the 'ladder' method,
    // which reads the live first ladder target instead — and null is also the
    // fallback for a non-ladder method whose snapshot never got stamped, which
    // keeps a mis-set position alerting on the ladder rather than going silent.
    const firstTarget = p.targets[0];
    // `> 0`, not just non-null: 0 is never a real stock price (the same
    // convention portfolioStore's floorStop applies to stops), and an upstream
    // `?? 0` fallback can land one here — on either side. Left un-guarded, a 0
    // snapshot OR a 0 ladder target makes `referencePrice >= 0` true on every
    // single tick for a bullish position.
    const snapshotPrice = p.resolvedTpPrice != null && p.resolvedTpPrice > 0 ? p.resolvedTpPrice : null;
    const ladderPrice = firstTarget?.stockPrice != null && firstTarget.stockPrice > 0 ? firstTarget.stockPrice : undefined;
    const tpPrice = snapshotPrice ?? ladderPrice;
    const tpMethod = p.activeTpMethod ?? 'ladder';
    // Only label a non-ladder method that actually supplied the price — a
    // method selected without a stamped snapshot fell back to the ladder
    // above, so naming it here would misreport which target was hit.
    const tpMethodNote =
      tpMethod !== 'ladder' && snapshotPrice != null
        ? ` (${TP_METHOD_LABEL[tpMethod]})`
        : '';
    const tpHit = hasReferencePrice && tpPrice != null
      ? (isBearish ? referencePrice <= tpPrice : referencePrice >= tpPrice)
      : false;
    if (tpHit && enabled('TP_HIT')) {
      out.push({
        recId: p.recId,
        kind: 'Action',
        symbol: p.symbol,
        alertType: 'TP_HIT',
        reason: `Target reached — ${p.symbol} at $${referencePrice.toFixed(2)}${tpMethodNote}`,
        price: referencePrice,
        referenceValue: tpPrice,
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
    if (stopBreached && stop != null && enabled('STOP_REACHED')) {
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
    if (structuralBreached && structuralStop != null && enabled('STRUCTURAL_STOP_BREACHED')) {
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

    // PREMIUM_STOP — option lost premiumStopPct of its value.
    //
    // THE SAME COMPARISON THE BACKEND MAKES, on the same two numbers:
    // `opt_price <= entry * (1 - pct)` (alert_generator.py, via the shared
    // premiumStopThresholdPrice). This used to test the rounded `pnlPct`
    // against `-(pct * 100)`, and the two engines disagreed at the boundary:
    // portfolio.py rounds pnlPct to 2dp, so entry $5.00 at pct 0.30 with a
    // quote of $3.5001 gave pnlPct −29.998 → −30.00, firing an in-app toast
    // for an alert the backend had no record of. Piece 4 made that MORE
    // likely, not less — a derived per-position fraction like 0.7554 puts the
    // threshold on non-round cents far more often than a flat 0.60 did.
    // BOTH of the backend's guards, not one. `alert_generator.py` tests
    // `opt_price is not None and pos.entry_price > 0`, and the frontend has no
    // `None` to test: `portfolioStore.fromBackend` coerces a missing quote to
    // `currentPrice: p.currentPrice ?? 0`, and the backend itself writes
    // `quote.get("price") or 0.0` when the fetch came back empty. So a failed
    // option-quote fetch — market closed, broker down, an OCC symbol the
    // provider does not know — reaches here as a price of 0, and `0 <= entry x
    // (1 - pct)` is TRUE FOR EVERY POSITION.
    //
    // That is a regression this comparison introduced, not a pre-existing
    // hazard: the `pnlPct <= -(pct * 100)` test it replaced read `0 <= -60` on
    // the same input and stayed silent. Unguarded, every position with a dead
    // quote raised a Critical toast on each 30s cycle, reading "down 0.0%",
    // with no backend alert behind it — the exact divergence this change was
    // made to close. `> 0` is the frontend spelling of `is not None`: a long
    // option quoted at zero is not a live quote either.
    //
    // STOP-SEMANTICS-2026-10-02: a SHORT stock (Bearish `|STOCK`) loses on a
    // rise, so its stop fires at `price >= entry * (1 + pct)`. Every other
    // position keeps the fall-side rule. A short's reason is price-only and
    // identical to the backend's, because `pnlPct` is not direction-aware (a
    // short that rose 12% reads +12%).
    const resolvedPremiumStopPct = resolvePremiumStopPct(p.premiumStopPct, globalPremiumStopPct);
    const shortStock = isShortStockPosition(p.contract, p.direction);
    const premiumStopPrice = percentStopThresholdPrice(p.entryPrice, resolvedPremiumStopPct, shortStock);
    if (
      p.entryPrice > 0 && p.currentPrice > 0
      && (shortStock ? p.currentPrice >= premiumStopPrice : p.currentPrice <= premiumStopPrice)
      && enabled('PREMIUM_STOP')
    ) {
      out.push({
        recId: p.recId,
        kind: 'Critical',
        symbol: p.symbol,
        alertType: 'PREMIUM_STOP',
        reason: shortStock
          ? `Stock stop — ${p.symbol} at $${p.currentPrice.toFixed(2)}`
          : `Premium stop — ${p.symbol} down ${p.pnlPct.toFixed(1)}%`,
        // Both now in scope, and both are what the backend records for the
        // same alert (`alert_generator.py`: `price=opt_price,
        // reference_value=threshold_price`). Leaving them undefined gave
        // position_alert_history rows two different shapes for one alert type
        // depending on which engine wrote them.
        price: p.currentPrice,
        // Rounded to 4dp because that is literally what the backend stores
        // (`reference_value=round(threshold_price, 4)`). Writing the unrounded
        // float here gave one alert type two shapes in position_alert_history
        // -- 2.6816 from the backend, 2.68164 from here -- decided by nothing
        // more than which engine happened to fire first. `pythonRound4`, not
        // `Math.round(x * 1e4) / 1e4`: the latter disagrees with Python's
        // round() on near-halves and on exact ties (see its doc).
        referenceValue: pythonRound4(premiumStopPrice),
        // The RESOLVED fraction, the same one the comparison above used and
        // the same one the backend logs as `thresholdPct` -- never the global,
        // which would misreport why a pinned position fired
        // (ALERT-THRESHOLD-STAMP-2026-09-05). Unrounded: the Alerts page
        // trims it for display through premiumStopPctLabel, and a
        // server-derived fraction like 0.7554 must not lose precision on the
        // way into storage the way the label's old Math.round did.
        premiumStopPct: resolvedPremiumStopPct,
        // The side rule it FIRED under; also part of the alert store's dedup
        // key, so a short's rise-side fire never inherits fall-side state.
        stopSide: premiumStopSide(p.contract, p.direction),
        direction: p.direction,
        contract: p.contract,
      });
    }

    // TIME_STOP — an option within 3 days of expiry. Stock positions carry no
    // expiry, but dteRemaining defaults/coerces to 0 for them everywhere
    // upstream (paperTrade.ts's buildPaperStockPosition, portfolioStore.ts's
    // `?? 0` sync, and the backend schema default — portfolio.py's router only
    // overwrites it from a contract's expiry for an options-shaped, 4-part
    // contract string) — so `dteRemaining <= 3` is unconditionally true for
    // every stock position, which is why a stock position takes the hold rule
    // below instead (STOCKS-HORIZON-T1 H6). Mirrors the backend's own
    // alert_generator.py: parse_expiry_from_contract returns None for a
    // `|STOCK` contract, and the hold branch runs instead.
    if (isStock) {
      const hold = p.holdMaxDays;
      const held = hold != null ? daysHeld(p.entryDate) : null;
      if (hold != null && held != null && held >= hold && enabled('TIME_STOP')) {
        out.push({
          recId: p.recId,
          kind: 'Action',
          symbol: p.symbol,
          alertType: 'TIME_STOP',
          reason: `Time stop — ${p.symbol} held ${held}d (hold ${hold}d)`,
          referenceValue: held,
          direction: p.direction,
          contract: p.contract,
        });
      }
    } else if (p.dteRemaining <= TIME_STOP_DTE && enabled('TIME_STOP')) {
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
    if (p.nextEventDays != null && p.nextEventDays <= 3 && enabled('EVENT_RISK')) {
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
