/**
 * #583 (TC-REVIEW-08) — THE BROKER REVIEW AND ITS OUTCOME.
 *
 * Step 7's direct sends (Place Limit, Right Now — Market) still save first and
 * send second (P1b-i). What changed is what happens before the save: the page
 * asks the server what it would store (#582 `previewPosition`), shows that row
 * beside the exact broker request, and only a confirmation saves (with the
 * reviewed fingerprint) and dispatches.
 *
 * THE CAPTURED REQUEST. `captureBrokerRequest` freezes ONE object: the #581
 * draft's order at the quantity the server resolved, plus the durable attempt
 * identity. The review renders that object (its readable rows and its exact
 * JSON) and the send posts that same object. Nothing rebuilds it later: a
 * change to the card, the quote or the broker marks the review stale and asks
 * for a refresh.
 *
 * RETRY IDENTITY. `attempt_id` is derived from the saved row's recId, and
 * `saved_rec_id` is that recId, so any resend of the same saved row reaches
 * the backend's existing durable-attempt claim (`routers/broker._submit` →
 * `BrokerAttemptService.claim_production`), which replays a stored result
 * instead of placing a second order, and binds the row's `prepared_order`
 * marker (exposure credit) to that attempt. No second dispatch mechanism.
 *
 * THE OUTCOME. The broker endpoints answer `order_id`, `status`, `broker` and
 * `deduped` — never a fill price or a filled quantity. `outcomeLines` shows
 * those facts and says the execution fields are unavailable; an acceptance is
 * never a fill, and the saved tracking quote is never presented as one.
 */

import type { OptionOrderRequest } from './submissionDraft';
import { normaliseStatus, isAcceptedNotFilled, UNUSABLE_ORDER_IDS } from './directOrder';

/* ── The captured request ────────────────────────────────────────────────── */

export interface CapturedBrokerRequest extends OptionOrderRequest {
  /** Durable attempt id: one per saved row, stable across any resend. */
  readonly attempt_id: string;
  /** The saved Portfolio row this order belongs to. */
  readonly saved_rec_id: string;
}

/** One attempt id per saved row. Options carry `opt-`, stocks `stk-`. */
export function attemptIdFor(recId: string): string {
  return `opt-${recId}`;
}

/** The exact request a direct send posts: the draft's order at the reviewed
 *  quantity, with the saved row's attempt identity. Frozen; key order kept. */
export function captureBrokerRequest(order: Readonly<OptionOrderRequest>, quantity: number, recId: string): Readonly<CapturedBrokerRequest> {
  return Object.freeze({ ...order, quantity, attempt_id: attemptIdFor(recId), saved_rec_id: recId });
}

/* ── Destination ─────────────────────────────────────────────────────────── */

/** The mode the broker key itself states. The backend accepts paper keys only. */
export function brokerModeOf(broker: string): 'Paper' | 'Unknown' {
  return /_paper$/.test(broker) ? 'Paper' : 'Unknown';
}

const money = (x: number | null | undefined): string => (x == null || !Number.isFinite(x) ? '—' : `$${x.toFixed(2)}`);

export function orderTypeText(req: Pick<OptionOrderRequest, 'order_type'>): string {
  return req.order_type === 'LMT' ? 'Limit' : 'Market';
}

/** The final action: it names the destination and the reviewed order. */
export function confirmLabelFor(brokerLabel: string, req: Readonly<OptionOrderRequest>): string {
  const what = req.order_type === 'LMT' ? `Limit ${req.quantity} @ ${money(req.limit_price)}` : `Market ${req.quantity}`;
  return `Send to ${brokerLabel} — ${what}`;
}

/** One line for the request, as sent. */
export function requestSummary(label: string, brokerLabel: string, req: Readonly<OptionOrderRequest>): string {
  const type = req.order_type === 'LMT' ? `Limit ${money(req.limit_price)}` : 'Market';
  return `${req.action} to ${req.effect === 'OPEN' ? 'open' : 'close'} ${req.quantity} × ${label} · ${type} · ${req.tif} · ${brokerLabel}`;
}

/* ── Outcome ─────────────────────────────────────────────────────────────── */

/** The only facts a broker response supplies. */
export interface BrokerResponseFacts {
  orderId: string | null;
  status: string | null;
  broker: string | null;
  deduped: boolean;
}

export function responseFacts(res: unknown): BrokerResponseFacts {
  const r = (res && typeof res === 'object' ? res : {}) as Record<string, unknown>;
  const text = (v: unknown) => (typeof v === 'string' && v.trim() !== '' ? v.trim() : null);
  const id = text(r.order_id);
  return {
    orderId: id != null && !UNUSABLE_ORDER_IDS.has(id.toLowerCase()) ? id : null,
    status: text(r.status),
    broker: text(r.broker),
    deduped: r.deduped === true,
  };
}

export interface DirectOrderOutcome {
  label: string;
  brokerLabel: string;
  /** The captured request that was posted. */
  request: Readonly<CapturedBrokerRequest>;
  /** Null when the call threw (no body). */
  response: BrokerResponseFacts | null;
  /** `classifyDirectFailure`'s verdict. Its reason text is the page's banner;
   *  the outcome repeats only the response's own facts. */
  verdict: 'placed' | 'keep' | 'delete';
  /** The saved Portfolio row, or null when it was removed. */
  recorded: { quantity: number; entryPrice: number | null } | null;
}

export interface OutcomeLine { key: string; label: string; value: string; tone: 'pass' | 'caution' | 'reject' | 'secondary' }

const FILLED = new Set(['filled', 'fill']);
const UNAVAILABLE = 'Unavailable — the broker response does not report it';

function statusLine(o: DirectOrderOutcome): Pick<OutcomeLine, 'value' | 'tone'> {
  const raw = o.response?.status ?? '';
  if (o.verdict === 'delete') {
    return { value: raw ? `Not placed — broker status ${raw}` : 'Not placed — refused before the broker received it', tone: 'reject' };
  }
  if (o.verdict === 'keep') {
    return { value: `Unknown — ${raw ? `broker status ${raw}` : 'no usable broker answer'}; check ${o.brokerLabel}`, tone: 'caution' };
  }
  if (FILLED.has(normaliseStatus(raw))) {
    return { value: `${raw} (as reported) — the response has no fill price or filled quantity; check ${o.brokerLabel}`, tone: 'pass' };
  }
  if (isAcceptedNotFilled(raw)) return { value: `${raw} — accepted or pending at the broker, not a fill`, tone: 'pass' };
  // Any other word (a partial fill, a hold, a vocabulary this file has not
  // seen) is the broker's: repeated, never interpreted.
  return raw
    ? { value: `${raw} (as reported) — the response has no fill price or filled quantity; check ${o.brokerLabel}`, tone: 'caution' }
    : { value: 'Not reported', tone: 'secondary' };
}

function contracts(n: number): string {
  return `${n} contract${n === 1 ? '' : 's'}`;
}

/** The outcome, line by line: the request, the response facts, the execution
 *  fields the response does not supply, and the recorded row. */
export function outcomeLines(o: DirectOrderOutcome): OutcomeLine[] {
  const req = o.request;
  const res = o.response;
  const lines: OutcomeLine[] = [
    { key: 'requested', label: 'Requested', value: requestSummary(o.label, o.brokerLabel, req), tone: 'secondary' },
    { key: 'status', label: 'Broker status', ...statusLine(o) },
    { key: 'orderId', label: 'Order ID', value: res?.orderId ?? 'Not reported', tone: 'secondary' },
  ];
  const answered = res?.broker ?? null;
  lines.push({
    key: 'broker', label: 'Broker (as answered)',
    value: answered == null ? 'Not reported'
      : answered === req.broker ? answered
      : `${answered} — differs from the request (${req.broker})`,
    tone: answered != null && answered !== req.broker ? 'caution' : 'secondary',
  });
  lines.push({
    key: 'deduped', label: 'Deduplicated',
    value: res == null ? 'Not reported'
      : res.deduped ? 'Yes — the server returned the stored result of this attempt; no second order was sent'
      : 'No',
    tone: 'secondary',
  });
  lines.push({ key: 'attempt', label: 'Attempt', value: `${req.attempt_id} · saved row ${req.saved_rec_id}`, tone: 'secondary' });
  lines.push({ key: 'fillPrice', label: 'Fill price', value: UNAVAILABLE, tone: 'secondary' });
  lines.push({ key: 'filledQty', label: 'Filled quantity', value: UNAVAILABLE, tone: 'secondary' });
  if (o.recorded) {
    lines.push({
      key: 'recorded', label: 'Recorded position',
      value: `${contracts(o.recorded.quantity)} · tracking entry ${money(o.recorded.entryPrice)} (a quote, not a fill) · rec_id ${req.saved_rec_id}`,
      tone: 'secondary',
    });
    lines.push({
      key: 'quantity', label: 'Quantity check',
      value: o.recorded.quantity === req.quantity
        ? `requested ${req.quantity} = recorded ${o.recorded.quantity}`
        : `requested ${req.quantity} ≠ recorded ${o.recorded.quantity}`,
      tone: o.recorded.quantity === req.quantity ? 'secondary' : 'caution',
    });
  } else {
    lines.push({ key: 'recorded', label: 'Recorded position', value: 'Removed — no order was placed for it', tone: 'secondary' });
  }
  return lines;
}
