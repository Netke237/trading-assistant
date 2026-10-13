/*
 * P1b-i (P1-CARD-SAVE-FIRST-SEND-TRIMMED-2026-09-25) — pure helpers for Step 7's
 * two direct sends (Place Limit, Right Now — Market). They live outside
 * `page.tsx` because a Next.js page file may only export its route symbols, and
 * every rule here is pinned by `__tests__/directOrder.test.ts`.
 *
 * The page saves the position FIRST and then sends the order. When the order
 * fails, `classifyDirectFailure` decides whether the saved row may be deleted:
 * ONLY when the failure provably happened before the broker received the order.
 * Anything it does not recognise keeps the row and raises an ORDER-UNKNOWN note
 * — a tracked row with no order is recoverable, an untracked live order is not.
 */

import { contractLabel, type TradeCardData } from '@/types/domain';
import type { DirectSendNote } from '@/lib/directSendNotesStore';
import { parseApiError } from '@/lib/apiError';

/** Why a direct send is refused before anything is saved, or null. */
export function directOrderBlock(orderType: 'LMT' | 'MKT', broker: string | null): string | null {
  // TastytradePaperAdapter refuses non-limit orders (tastytrade_paper.py).
  if (orderType === 'MKT' && broker === 'tastytrade_paper') {
    return 'Tastytrade paper accepts limit orders only — use Place Limit.';
  }
  return null;
}

/** The label a broker shows under. Shared by the position's `sourceLabel` and
 *  the notes, so the two can never name different brokers. */
export function brokerLabelFor(broker: string): string {
  // STOCK-SENDS (R1-1): the stock paths also offer Alpaca. Without its own
  // label an ORDER-UNKNOWN note would send the user to IBKR before Remove.
  return broker === 'tradier_paper' ? 'Tradier Paper'
    : broker === 'tastytrade_paper' ? 'Tastytrade Paper'
    : broker === 'alpaca_paper' ? 'Alpaca Paper'
    : 'IBKR Paper';
}

/** The human contract label every direct-send message carries, so a result
 *  that lands after Prev/Next is still true on whichever card is showing. */
export function contractLabelFor(card: TradeCardData): string {
  const cd = card.contractDetails;
  if (cd?.strike != null && cd.expiry && cd.right) {
    return contractLabel({ symbol: card.symbol, strike: cd.strike, right: cd.right, expiry: cd.expiry });
  }
  return card.contract;
}

/** The reason text for a thrown error: the detail after `→ NNN: ` when there is
 *  one, else `String(e)`. Never undefined. */
export function whyOf(e: unknown): string {
  const { detail, text } = parseApiError(e);
  return detail ?? text;
}

/** A thrown `→ 404` from `api.ts`. */
export function isNotFound(e: unknown): boolean {
  return parseApiError(e).status === 404;
}

/** 2xx statuses that are NOT dead on arrival for every adapter (the broker
 *  received the order; IBKR `Inactive` also covers held orders that can still
 *  be transmitted). They keep the row. */
const TERMINAL_KEEP = new Set(['inactive', 'error', 'canceled', 'cancelled', 'expired', 'removed', 'partially removed']);

export function normaliseStatus(status: unknown): string {
  // Defensive: an Enum repr must never slip past as unknown-and-safe.
  return String(status ?? '').trim().toLowerCase().replace(/^orderstatus\./, '');
}

const ACCEPTED_NOT_FILLED = new Set([
  'accepted', 'presubmitted', 'submitted', 'pending', 'pendingsubmit', 'pendingnew', 'new',
]);

/** Accepted, pending, and submitted broker statuses are not fills. */
export function isAcceptedNotFilled(status: unknown): boolean {
  const token = normaliseStatus(status).replace(/[\s_]/g, '');
  return ACCEPTED_NOT_FILLED.has(token);
}

export type DirectOutcome =
  | { verdict: 'placed'; orderId: string }
  | { verdict: 'delete'; why: string }
  | { verdict: 'keep'; why: string; orderId: string | null };

/** Classify a direct send's broker outcome: a thrown error, or a 2xx body. */
export function classifyDirectFailure(
  input: { thrown: unknown } | { response: unknown },
): DirectOutcome {
  if ('thrown' in input) {
    const { status, detail } = parseApiError(input.thrown);
    const why = whyOf(input.thrown);
    const d = detail ?? '';
    const preSubmit =
      status === 422
      || (status === 503 && d.startsWith('Broker credentials unavailable'))
      || (status === 400 && (d.startsWith('live trading via') || d.startsWith('Unknown broker')))
      // A PREFIX match: other adapters echo broker text into their 502s.
      || (status === 502 && d.startsWith('IBKR did not place the order:'));
    return preSubmit ? { verdict: 'delete', why } : { verdict: 'keep', why, orderId: null };
  }
  const res = (input.response ?? {}) as { order_id?: unknown; status?: unknown };
  const rawStatus = String(res.status ?? '');
  const status = normaliseStatus(res.status);
  const id = typeof res.order_id === 'string' ? res.order_id.trim() : '';
  const usableId = id !== '' && id.toLowerCase() !== 'unknown' ? id : null;
  if (status === 'rejected') return { verdict: 'delete', why: `broker status ${rawStatus}` };
  if (TERMINAL_KEEP.has(status)) return { verdict: 'keep', why: `broker status ${rawStatus}`, orderId: usableId };
  if (usableId == null) {
    return { verdict: 'keep', why: `broker reply had no usable order ID${rawStatus ? ` (status ${rawStatus})` : ''}`, orderId: null };
  }
  return { verdict: 'placed', orderId: usableId };
}

/** The persistent note's text, rendered from its fields (plan A2). */
export function directSendNoteText(n: DirectSendNote): string {
  const rec = `(rec_id ${n.recId})`;
  switch (n.kind) {
    case 'order-unknown': {
      const idPart = n.orderId ? ` (broker order ID ${n.orderId})` : '';
      return `${n.label}: order status UNKNOWN${idPart} ${rec}. Check ${n.brokerLabel} first. If an order exists there, keep this position. If none does, press Remove.`;
    }
    case 'save-unconfirmed':
      return `${n.label}: NO order was sent, but Portfolio may still have saved this send ${rec}. Press Remove to delete that saved row.`;
    case 'not-removed':
      return `${n.label}: NO order was placed, but its tracked position could not be removed ${rec}. Press Remove to try again.`;
  }
}

/** The Remove button's confirm text (plan A3.1). */
export function removeConfirmText(n: DirectSendNote): string {
  if (n.kind === 'order-unknown') {
    return `Delete the tracked ${n.label} position (rec_id ${n.recId})? Do this ONLY if ${n.brokerLabel} shows no order for it. If an order exists, deleting leaves that order untracked.`;
  }
  return `Delete the saved ${n.label} row (rec_id ${n.recId})? No order was placed for it.`;
}
