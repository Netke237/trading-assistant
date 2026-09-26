/*
 * STOCK-SENDS-SAVE-FIRST-THEN-REAL-SHARES (plan B1, Q2) — the ONE save-first
 * flow for every stock broker send: the Step-7 position card, StockPositionCard
 * and StockSendDialog's auto-send. It is P1b-i's options flow
 * (step-7-trade-card/page.tsx placeDirectOrder) step for step:
 *
 *   guard → local duplicate check → SAVE → (refused | unconfirmed → stop, no
 *   order) → send the quantity the save APPROVED → classify → auto-delete only
 *   a provably pre-submit failure, else keep the row with an ORDER-UNKNOWN note.
 *
 * Why save first: since Part A the save can RESIZE a stock (risk at the stop,
 * STOCK-RISK-AT-STOP-2026-09-26). Sending first would put the full size at the
 * broker while the books hold the smaller one.
 *
 * It never touches React state: it returns an outcome, and each caller maps it
 * onto its own UI. Notes go to the shared directSendNotesStore, so they outlive
 * the component that sent them.
 */

import { api } from '@/lib/api';
import {
  applyPersistedPosition, persistPosition, usePortfolioStore,
} from '@/lib/portfolioStore';
import { useDirectSendNotesStore } from '@/lib/directSendNotesStore';
import {
  brokerLabelFor, classifyDirectFailure, directOrderBlock, dropLocal, removeTrackedRow,
  type DirectOutcome,
} from '@/lib/directOrder';
import { scaleRungShares } from '@/lib/paperTrade';
import type { PortfolioPosition } from '@/types/domain';

export type StockSendArgs = {
  /** buildPaperStockPosition(...) + picks, with `source: 'broker'`. */
  pos: PortfolioPosition;
  broker: string;
  orderType: 'LMT' | 'MKT';
  limitPrice: number | null;
  action: 'BUY' | 'SELL';
};

export type StockSendOutcome =
  | { kind: 'blocked'; message: string }       // refused locally; nothing saved, no order
  | { kind: 'refused'; message: string }       // the server said no; nothing written
  | { kind: 'unconfirmed'; message: string }   // offline / bare 5xx / unparsed 2xx; SAVE-UNCONFIRMED note
  | { kind: 'removed'; message: string }       // pre-submit broker failure; the row was deleted
  | { kind: 'not-removed'; message: string }   // pre-submit failure; the delete failed; NOT-REMOVED note
  | { kind: 'unknown'; message: string }       // row kept + ORDER-UNKNOWN note
  | { kind: 'placed'; orderId: string; qty: number; message: string | null };

/** The label every stock message carries, so a result that lands after the
 *  user moved on is still true wherever it shows. */
export function stockLabelFor(symbol: string): string {
  return `${symbol} stock`;
}

export async function placeStockOrderSaveFirst(args: StockSendArgs): Promise<StockSendOutcome> {
  const { pos, broker, orderType, limitPrice, action } = args;
  const label = stockLabelFor(pos.symbol);
  const brokerLabel = brokerLabelFor(broker);
  const recId = pos.recId;
  const addNote = useDirectSendNotesStore.getState().addNote;
  const addPosition = usePortfolioStore.getState().addPosition;

  const blocked = directOrderBlock(orderType, broker);
  if (blocked) return { kind: 'blocked', message: blocked };

  // The backend would refuse anyway; refusing locally means a SAVE-UNCONFIRMED
  // note can only ever point at a row THIS send created.
  if (usePortfolioStore.getState().positions.some((p) => p.contract === pos.contract)) {
    return {
      kind: 'blocked',
      message: `${label}: No order was sent — a position for this stock is already tracked in Portfolio. Close or edit that one instead.`,
    };
  }

  const saved = await persistPosition(pos);
  const bare5xx = !saved.ok && !saved.offline && /^HTTP 5\d\d$/.test(saved.detail ?? '');
  const unparsed2xx = saved.ok && saved.entryPrice == null;
  if (saved.offline || bare5xx || unparsed2xx) {
    // The create may still commit AFTER a delete lands, so the note is pushed
    // whatever the delete answers; applyPersistedPosition is never called here
    // (its offline branch would re-POST).
    addNote({ recId, kind: 'save-unconfirmed', label, brokerLabel, orderId: null });
    dropLocal(recId);
    try { await removeTrackedRow(recId, false); } catch { /* best effort; the note stays */ }
    return {
      kind: 'unconfirmed',
      message: unparsed2xx
        ? `${label}: Portfolio saved it but its reply could not be read, so NO order was sent.`
        : `${label}: Portfolio tracking could not be confirmed, so NO order was sent.`,
    };
  }
  if (!saved.ok) {
    // Every server refusal happens before the commit: nothing was written.
    const detail = saved.detail ?? 'not saved';
    return {
      kind: 'refused',
      message: /already exists/.test(detail)
        ? `${label}: No order was sent — a position for this stock is already tracked in Portfolio. Close or edit that one instead.`
        : `${label}: No order was sent — ${detail.replace(/\.$/, '')}.`,
    };
  }

  // Confirmed save. Everything from here is inside this try/catch: nothing
  // after the save may escape without the row getting its note.
  const requested = Math.max(1, pos.contracts ?? 1);
  const orderQty = saved.adjustedQty ?? requested;
  const resized = orderQty !== requested;
  // Q2: the local row carries the rungs the writer stored, BEFORE it enters
  // the store, in every branch that adds it.
  const booked: PortfolioPosition = {
    ...pos, contracts: orderQty, targets: scaleRungShares(pos.targets, orderQty) ?? pos.targets,
  };
  const sizeNote = resized
    ? `${label}: Portfolio sized it to ${orderQty} shares to fit your exposure limit; the order was sent for ${orderQty}.`
    : null;

  const keepRow = (why: string, orderId: string | null): StockSendOutcome => {
    // Note FIRST, row second: a throw can never leave a row without its note.
    addNote({ recId, kind: 'order-unknown', label, brokerLabel, orderId });
    let message = `${label}: Order status UNKNOWN (${why}).`;
    try {
      applyPersistedPosition(saved, booked, addPosition);
    } catch (e) {
      message += ` The local view failed to update: ${String(e)}`;
    }
    return { kind: 'unknown', message };
  };

  try {
    let outcome: DirectOutcome;
    try {
      const res = await api.postStockOrder({
        broker,
        symbol:      pos.symbol,
        action,
        effect:      'OPEN',
        quantity:    orderQty,
        order_type:  orderType,
        limit_price: limitPrice,
        tif:         'DAY',
      });
      outcome = classifyDirectFailure({ response: res });
    } catch (e) {
      outcome = classifyDirectFailure({ thrown: e });
    }

    if (outcome.verdict === 'delete') {
      try {
        await removeTrackedRow(recId, true);
        return { kind: 'removed', message: `${label}: Order NOT placed: ${outcome.why}. The tracked position was removed.` };
      } catch {
        addNote({ recId, kind: 'not-removed', label, brokerLabel, orderId: null });
        return { kind: 'not-removed', message: `${label}: Order NOT placed: ${outcome.why}.` };
      }
    }
    if (outcome.verdict === 'keep') return keepRow(outcome.why, outcome.orderId);

    const orderId = outcome.orderId;
    let message = sizeNote;
    try {
      applyPersistedPosition(
        saved,
        { ...booked, sourceLabel: `${brokerLabel} — ${orderType === 'LMT' ? 'Limit' : 'Market'} (ID: ${orderId})` },
        addPosition,
      );
    } catch (e) {
      message = `${label}: Order placed (ID ${orderId}) but the local view failed to update: ${String(e)}`;
    }
    return { kind: 'placed', orderId, qty: orderQty, message };
  } catch (e) {
    // Unreachable by design; if reached, the order's fate is unknown.
    return keepRow(String(e), null);
  }
}
