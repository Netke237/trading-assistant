/*
 * P1b-i (P1-CARD-SAVE-FIRST-SEND-TRIMMED-2026-09-25) — helpers for every
 * save-first broker send: Step 7's options sends (Place Limit, Right Now —
 * Market) and, since STOCK-SENDS-SAVE-FIRST-THEN-REAL-SHARES, the three stock
 * sends (lib/stockSaveFirst.ts). Moved here from the Step-7 route folder so the
 * stock components can share them; the route file re-exports them. Every rule
 * here is pinned by `lib/__tests__/directOrder.test.ts`.
 *
 * The page saves the position FIRST and then sends the order. When the order
 * fails, `classifyDirectFailure` decides whether the saved row may be deleted:
 * ONLY when the failure provably happened before the broker received the order.
 * Anything it does not recognise keeps the row and raises an ORDER-UNKNOWN note
 * — a tracked row with no order is recoverable, an untracked live order is not.
 */

import { api } from '@/lib/api';
import { usePortfolioStore } from '@/lib/portfolioStore';
import type { DirectSendNote } from '@/lib/directSendNotesStore';

/** Why a direct send is refused before anything is saved, or null. */
export function directOrderBlock(orderType: 'LMT' | 'MKT', broker: string | null): string | null {
  // TastytradePaperAdapter refuses non-limit orders (tastytrade_paper.py).
  if (orderType === 'MKT' && broker === 'tastytrade_paper') {
    return 'Tastytrade paper accepts limit orders only — use Place Limit.';
  }
  return null;
}

/** The label a broker shows under. Shared by the position's `sourceLabel` and
 *  the notes, so the two can never name different brokers. An unknown key is
 *  shown as itself, NEVER as another broker's name: an ORDER-UNKNOWN note that
 *  says "check IBKR" for an Alpaca order sends the user to the wrong place,
 *  and a Remove there untracks a live order (stock plan R1). */
export function brokerLabelFor(broker: string): string {
  switch (broker) {
    case 'ibkr_paper':       return 'IBKR Paper';
    case 'tradier_paper':    return 'Tradier Paper';
    case 'tastytrade_paper': return 'Tastytrade Paper';
    case 'alpaca_paper':     return 'Alpaca Paper';
    default:                 return broker;
  }
}

/** `api.ts`'s `apiError` throws `API ${path} → ${status}: ${detail}`. */
function parseApiError(e: unknown): { status: number | null; detail: string | null; text: string } {
  const text = String(e);
  const msg = e instanceof Error ? e.message : text;
  const m = /→ (\d{3})(?:: ([\s\S]*))?$/.exec(msg);
  if (!m) return { status: null, detail: null, text };
  return { status: Number(m[1]), detail: m[2] ?? null, text };
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

/** Drop one row from the local store by rec_id. A `syncFromBackend` may have
 *  copied a saved row in between the save and the broker's answer. */
export function dropLocal(recId: string): void {
  usePortfolioStore.setState((s) => ({ positions: s.positions.filter((p) => p.recId !== recId) }));
}

/** Hard-DELETE one tracked row by rec_id, then drop it locally. Shared by the
 *  auto-delete and a note's Remove (plan X1), so neither can skip the last
 *  step: a sync whose GET started BEFORE the DELETE resolves after it and
 *  writes the deleted row back, and a Close on that stale row then books a
 *  phantom closed trade into History. A forced sync chains after the one in
 *  flight, so its GET post-dates the DELETE; the row is dropped again after it.
 *  Throws what the DELETE threw -- except a `→ 404` when `notFoundIsFinal`. */
export async function removeTrackedRow(recId: string, notFoundIsFinal: boolean): Promise<void> {
  try {
    await api.deletePortfolioPosition(recId);
  } catch (e) {
    if (!(notFoundIsFinal && isNotFound(e))) throw e;
  }
  dropLocal(recId);
  void usePortfolioStore.getState().syncFromBackend(true).then(() => dropLocal(recId));
}
