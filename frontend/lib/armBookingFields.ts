import type { ArmBookingFields } from '@/lib/api';
import type { ExitPlan, MaxLossOverride, TargetLevel } from '@/types/domain';

/** O4 step 6 — what the caller resolves; `armBookingFieldsFrom` maps it onto
 *  the wire. Camel-cased because it is read off the card and the Step-7 page;
 *  the wire is snake_case. */
export interface ArmBookingInputs {
  /** The SAME value the arm button's stop gate reads -- AutoTradeArm hoists it
   *  to one local so the gate and the payload cannot be two readings. */
  stop: number | null | undefined;
  stopIsUserSet: boolean;
  /** `card.price` -- the scan-time underlying the booking re-anchors against. */
  scanStockPrice: number | null | undefined;
  structuralStop: number | null | undefined;
  exitPlan: ExitPlan | null | undefined;
  targets: TargetLevel[] | null | undefined;
  /** `card.contractDetails?.dte`. */
  dteTotal: number | null | undefined;
  premiumStopDollar: number | null | undefined;
  maxLossOverride: MaxLossOverride | null | undefined;
  tradeCardSnapshot: Record<string, unknown> | null | undefined;
}

function positiveOrNull(v: number | null | undefined): number | null {
  return v != null && Number.isFinite(v) && v > 0 ? v : null;
}

/** The ten booking fields, snake_case, every key present.
 *
 *  Each rule mirrors the card path's `toBackendPayload` (lib/portfolioStore.ts)
 *  so an armed trade and a sent trade describe one card the same way, AND
 *  meets the arm endpoint's bounds (O4 step 3 §2.1), which are tighter than
 *  the create schema's: a price field is `gt=0` there, so an absent price is
 *  sent as null -- a 0 would 422 the whole arm. `targets` is a list, never
 *  null. `dte_total` is a non-negative integer or null: the arm refuses
 *  `24.5`, and unlike the card path's `?? 24` this does not invent a DTE for a
 *  live booking.
 *
 *  Always-present keys rather than omitted ones, for the reason
 *  `armPickedFieldsFrom` gives: a caller that forgets to spread this in then
 *  fails a test instead of silently arming with nothing to book. */
export function armBookingFieldsFrom(i: ArmBookingInputs): ArmBookingFields {
  const dte = i.dteTotal;
  return {
    stop:                positiveOrNull(i.stop),
    stop_is_user_set:    i.stopIsUserSet === true,
    scan_stock_price:    positiveOrNull(i.scanStockPrice),
    structural_stop:     positiveOrNull(i.structuralStop),
    exit_plan:           i.exitPlan ?? null,
    targets:             i.targets ?? [],
    dte_total:           dte != null && Number.isInteger(dte) && dte >= 0 ? dte : null,
    premium_stop_dollar: positiveOrNull(i.premiumStopDollar),
    max_loss_override:   i.maxLossOverride ?? null,
    trade_card_snapshot: i.tradeCardSnapshot ?? null,
  };
}

/** How a FAILED `POST /auto-trade/fire` must be read (O4 step 6 §5.3).
 *
 *  'refused' -- the backend answered 400 before any broker call: not armed, a
 *  headwind / cap / daily-loss refusal, or "Order not submitted". Nothing was
 *  placed by this request.
 *
 *  'unknown' -- everything else. `fire()` raises "Order failed: ..." (also a
 *  400) when the broker call WAS made and errored, so that submission may have
 *  landed; a 5xx or a transport failure (fetch `TypeError`, a dropped
 *  connection while the booking's quote fetch runs) may have reached the
 *  broker too. The caller must not present these as a plain failure the user
 *  can retry: the order may be live.
 *
 *  Coupled to two strings on purpose, pinned by this module's tests:
 *  `apiError`'s "API <path> → <status>: <detail>" (lib/api.ts) and `fire()`'s
 *  "Order failed:" prefix (backend services/auto_trader.py). */
export function classifyFireFailure(e: unknown): 'refused' | 'unknown' {
  if (!(e instanceof Error) || e instanceof TypeError) return 'unknown';
  const m = /^API \S+ → (\d{3})(?:: ([\s\S]*))?$/.exec(e.message);
  if (!m) return 'unknown';
  if (m[1] !== '400') return 'unknown';
  return (m[2] ?? '').startsWith('Order failed:') ? 'unknown' : 'refused';
}
