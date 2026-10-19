import { stockExecutionBlock, stockExecutionIdentity, useStockOrderOwnershipStore } from './stockExecutionSession';
import { useScanStore } from './scanStore';
import { BEARISH_UNVALIDATED_MESSAGE } from './unvalidated';
import { EARNINGS_VETO_MESSAGE } from './earningsGate';
/*
 * STOCK-SENDS (phase STOCK-SENDS-SAVE-FIRST-THEN-REAL-SHARES, Part A) — the ONE
 * way a Stocks-mode path sends a broker order: SAVE the position first, then send
 * the order at the quantity the save approved. Plan:
 * docs/superpowers/plans/2026-09-27-stock-sends-save-first-real-shares-plan.md §A1.
 *
 * It mirrors Step 7 options' `placeDirectOrder` (P1b-i) step for step and reuses
 * its pure helpers, so a stock send and an option send classify a broker reply,
 * remove a row and leave notes identically. The old order (send, then save) left
 * a full-size order at the broker whenever Portfolio refused or resized the row.
 *
 * Callers: step-7-position-card `submit()`, StockPositionCard `submit()`,
 * StockSendDialog's auto-send branch.
 */

import { api } from '@/lib/api';
import {
  usePortfolioStore, persistPosition, applyPersistedPosition,
} from '@/lib/portfolioStore';
import { useDirectSendNotesStore, type DirectSendNote } from '@/lib/directSendNotesStore';
import {
  brokerLabelFor, classifyDirectFailure, directOrderBlock, isNotFound, removeConfirmText, whyOf,
  type DirectOutcome,
} from '@/lib/directOrder';
import type { PortfolioPosition } from '@/types/domain';

type AddPosition = (p: PortfolioPosition, opts?: { skipPost?: boolean }) => unknown;

export type StockSendOutcome =
  /** Saved and placed. `qty` is the quantity sent; `resizedFrom` the quantity
   *  asked for when Portfolio resized the save, else null. */
  | { kind: 'placed'; orderId: string; qty: number; resizedFrom: number | null; message: string }
  /** Nothing saved, no order. Safe to retry. */
  | { kind: 'refused'; message: string }
  /** Opening refusal saves nothing. After a save, the broker provably never
   *  received the order, and the row was removed
   *  (or a NOT-REMOVED note says it could not be). No order exists. */
  | { kind: 'not-placed'; message: string }
  /** A note was pushed. `qty` is the quantity SENT (null when the save was
   *  unconfirmed and nothing was sent). NOT safe to retry when `qty != null`:
   *  an order may be live. */
  | { kind: 'unknown'; message: string; qty: number | null; resizedFrom: number | null };

/** `"AAPL 100 sh"` — every stock send message and note names the symbol and the
 *  quantity, so a result landing after Prev/Next is still true on any screen. */
export function stockSendLabel(symbol: string, qty: number): string {
  return `${symbol} ${qty} sh`;
}

/** Drop one row from the local store by rec_id (a sync may have copied it in
 *  between the save and the broker's answer). Same body as step-7-trade-card's. */
export function dropLocal(recId: string): void {
  usePortfolioStore.setState((s) => ({ positions: s.positions.filter((p) => p.recId !== recId) }));
}

/** Hard-DELETE one tracked row by rec_id, then drop it locally, and again after
 *  a forced sync (a GET that started before the DELETE can write it back). Same
 *  body as step-7-trade-card's. Throws what the DELETE threw -- except a `→ 404`
 *  when `notFoundIsFinal`. */
export async function removeTrackedRow(recId: string, notFoundIsFinal: boolean): Promise<void> {
  try {
    await api.deletePortfolioPosition(recId);
  } catch (e) {
    if (!(notFoundIsFinal && isNotFound(e))) throw e;
  }
  dropLocal(recId);
  void usePortfolioStore.getState().syncFromBackend(true).then(() => dropLocal(recId));
}

function addNote(n: Omit<DirectSendNote, 'status' | 'removing'>): void {
  useDirectSendNotesStore.getState().addNote(n);
}

/** A note's Remove button: confirm, then hard-DELETE exactly that note's
 *  rec_id. Same logic as step-7-trade-card's `removeNoteRow`. */
export async function removeNoteRow(note: DirectSendNote, confirm: (text: string) => boolean = window.confirm): Promise<void> {
  if (note.removing) return;
  if (!confirm(removeConfirmText(note))) return;
  const { patchNote, removeNote } = useDirectSendNotesStore.getState();
  patchNote(note.recId, { removing: true, status: null });
  try {
    // A 404 is final only when the server had already answered this send's save
    // before the note existed. On SAVE-UNCONFIRMED the create may still be in flight.
    await removeTrackedRow(note.recId, note.kind !== 'save-unconfirmed');
    removeNote(note.recId);
  } catch (e) {
    patchNote(note.recId, {
      removing: false,
      status: note.kind === 'save-unconfirmed' && isNotFound(e)
        ? 'Not found yet — the save may still be finishing. Press Remove again in a few seconds.'
        : `Remove failed: ${whyOf(e)}. Try again.`,
    });
  }
}

type StockSendArgs = {
  /** Built by `buildPaperStockPosition`: contract `SYM|STOCK`, `recId` set,
   *  `contracts` = the shares asked for. */
  pos: PortfolioPosition;
  broker: string;
  orderType: 'LMT' | 'MKT';
  limitPrice: number | null;
  action: 'BUY' | 'SELL';
  addPosition: AddPosition;
  /** STOCKS-HORIZON-P0B B7 — the caller's `stockEarningsGate(...).veto` for
   *  this card: earnings inside the scan's veto window max(reject_days, hold).
   *  Required, so no caller can forget it; refuses the ORDER even if a
   *  disabled button is bypassed (Step 7's belt-and-braces early return). */
  earningsVeto: boolean;
};

export async function sendStockSaveFirst(args: StockSendArgs): Promise<StockSendOutcome> {
  if (args.action === 'SELL') return { kind: 'not-placed', message: BEARISH_UNVALIDATED_MESSAGE };
  // Nothing saved, nothing claimed, no broker request.
  if (args.earningsVeto) return { kind: 'refused', message: EARNINGS_VETO_MESSAGE };
  const validationBlock = stockExecutionBlock();
  if (validationBlock) return { kind: 'refused', message: validationBlock };
  const ownership = useStockOrderOwnershipStore.getState();
  const identity = stockExecutionIdentity(useScanStore.getState(), args.pos.symbol);
  if (!ownership.claim(args.pos.symbol, {
    identity,
    recId: args.pos.recId, status: 'in-flight',
  })) return { kind: 'refused', message: `${args.pos.symbol}: a previous stock send is in flight, placed or unresolved. Reconcile that order before sending again.` };
  try {
    const outcome = await performStockSaveFirst(args, identity);
    const hasNote = useDirectSendNotesStore.getState().notes.some(n => n.recId === args.pos.recId);
    ownership.finish(args.pos.symbol, args.pos.recId,
      outcome.kind === 'placed' ? 'placed' : outcome.kind === 'unknown' || hasNote ? 'unknown' : null,
      outcome.message);
    return outcome;
  } catch (error) {
    ownership.finish(args.pos.symbol, args.pos.recId, null, String(error));
    throw error;
  }
}

async function performStockSaveFirst(args: StockSendArgs, identity: string | null): Promise<StockSendOutcome> {
  const { pos, broker, orderType, limitPrice, action, addPosition } = args;
  // Always set by buildPaperStockPosition; the type is optional.
  const asked = pos.contracts ?? 1;
  const recId = pos.recId;
  const brokerLabel = brokerLabelFor(broker);
  const askedLabel = stockSendLabel(pos.symbol, asked);

  const blocked = directOrderBlock(orderType, broker);
  if (blocked) return { kind: 'refused', message: `${askedLabel}: ${blocked}` };
  // The backend would 409 anyway; refusing locally means a SAVE-UNCONFIRMED note
  // can only ever point at a row THIS send created.
  if (usePortfolioStore.getState().positions.some((p) => p.contract === pos.contract)) {
    return {
      kind: 'refused',
      message: `${askedLabel}: No order was sent — a position for ${pos.symbol} is already tracked in Portfolio. Close or edit that one instead.`,
    };
  }

  const saved = await persistPosition(pos, undefined, { orderType, limitPrice });
  // Unconfirmed: offline; a bare gateway 5xx (the create may still be running);
  // or a 2xx whose body did not parse. No order is sent.
  const bare5xx = !saved.ok && !saved.offline && /^HTTP 5\d\d$/.test(saved.detail ?? '');
  const unparsed2xx = saved.ok && saved.entryPrice == null;
  if (saved.offline || bare5xx || unparsed2xx) {
    addNote({ recId, kind: 'save-unconfirmed', label: askedLabel, brokerLabel, orderId: null });
    dropLocal(recId);
    try { await removeTrackedRow(recId, false); } catch { /* best effort; the note stays */ }
    return {
      kind: 'unknown', qty: null, resizedFrom: null,
      message: unparsed2xx
        ? `${askedLabel}: Portfolio saved it but its reply could not be read, so NO order was sent.`
        : `${askedLabel}: Portfolio tracking could not be confirmed, so NO order was sent.`,
    };
  }
  if (!saved.ok) {
    // Every refusal is raised before the commit or after a rollback: nothing was
    // written, so no delete and no note.
    const detail = saved.detail ?? 'not saved';
    return {
      kind: 'refused',
      message: /already exists/.test(detail)
        ? `${askedLabel}: No order was sent — a position for ${pos.symbol} is already tracked in Portfolio. Close or edit that one instead.`
        : `${askedLabel}: No order was sent — ${detail.replace(/\.$/, '')}.`,
    };
  }

  // Confirmed save. EVERYTHING from here is inside this try: nothing after the
  // save may escape, which would leave a saved row with no note.
  const orderQty = saved.adjustedQty ?? asked;
  const resizedFrom = saved.adjustedQty != null && saved.adjustedQty !== asked ? asked : null;
  const label = stockSendLabel(pos.symbol, orderQty);
  const sized = resizedFrom != null ? ` (Portfolio sized it from ${resizedFrom})` : '';
  const keepRow = (why: string, orderId: string | null): StockSendOutcome => {
    // Note FIRST, row second: a throw can never leave a row without its note.
    addNote({ recId, kind: 'order-unknown', label, brokerLabel, orderId });
    const message = `${label}${sized}: Order status UNKNOWN (${why}).`;
    try {
      applyPersistedPosition(saved, { ...pos, contracts: orderQty }, addPosition);
    } catch (e) {
      return { kind: 'unknown', qty: orderQty, resizedFrom, message: `${message} The local view failed to update: ${String(e)}` };
    }
    return { kind: 'unknown', qty: orderQty, resizedFrom, message };
  };
  try {
    let outcome: DirectOutcome;
    try {
      // Recheck after asynchronous save; permission may have changed while
      // saving. No new broker request follows an unavailable authority.
      const validationBlock = stockExecutionBlock()
        ?? (identity !== null && stockExecutionIdentity(useScanStore.getState(), pos.symbol) !== identity
          ? 'The scan changed while saving. No broker order was sent; review the current candidate.' : null);
      if (validationBlock) {
        try { await removeTrackedRow(recId, true); }
        catch { addNote({ recId, kind: 'not-removed', label, brokerLabel, orderId: null }); }
        return { kind: 'not-placed', message: validationBlock };
      }
      const orderRequest = {
        broker,
        symbol: pos.symbol,
        action,
        effect: 'OPEN' as const,
        quantity: orderQty,
        order_type: orderType,
        limit_price: limitPrice,
        tif: 'DAY' as const,
        attempt_id: `stk-${recId}`,
        savedRecId: recId,
      };
      const res = await api.postStockOrder(orderRequest);
      outcome = classifyDirectFailure({ response: res });
    } catch (e) {
      outcome = classifyDirectFailure({ thrown: e });
    }

    if (outcome.verdict === 'delete') {
      // Provably never received by the broker: remove the saved row.
      try {
        await removeTrackedRow(recId, true);
        return { kind: 'not-placed', message: `${label}: Order NOT placed: ${outcome.why}. The tracked position was removed.` };
      } catch {
        addNote({ recId, kind: 'not-removed', label, brokerLabel, orderId: null });
        return { kind: 'not-placed', message: `${label}: Order NOT placed: ${outcome.why}.` };
      }
    }
    if (outcome.verdict === 'keep') return keepRow(outcome.why, outcome.orderId);

    const orderId = outcome.orderId;
    const message = `${label}${sized}: Order placed (ID ${orderId}).`;
    try {
      applyPersistedPosition(
        saved,
        {
          ...pos,
          contracts: orderQty,
          source: 'broker',
          sourceLabel: `${brokerLabel} — ${orderType === 'LMT' ? 'Limit' : 'Market'} (ID: ${orderId})`,
          orderedAt: new Date().toISOString(),
        },
        addPosition,
      );
    } catch (e) {
      return { kind: 'placed', orderId, qty: orderQty, resizedFrom, message: `${message} The local view failed to update: ${String(e)}` };
    }
    return { kind: 'placed', orderId, qty: orderQty, resizedFrom, message };
  } catch (e) {
    // Unreachable by design (every call above is guarded); if reached, the
    // order's fate is unknown and the row stays with a note.
    return keepRow(String(e), null);
  }
}
