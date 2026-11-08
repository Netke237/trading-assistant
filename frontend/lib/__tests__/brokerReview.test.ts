import {
  attemptIdFor, brokerModeOf, captureBrokerRequest, confirmLabelFor, outcomeLines, responseFacts,
  type DirectOrderOutcome,
} from '@/lib/brokerReview';
import type { OptionOrderRequest } from '@/lib/submissionDraft';

/*
 * #583 (TC-REVIEW-08) — the pure half of the broker review: the captured
 * request the review shows and the send posts, its durable attempt identity,
 * and the outcome facts a broker response actually supplies.
 */

const ORDER: OptionOrderRequest = Object.freeze({
  broker: 'ibkr_paper', symbol: 'AAA', option_symbol: 'AAA|150|2026-05-15|C',
  action: 'BUY', effect: 'OPEN', quantity: 4, order_type: 'LMT', limit_price: 2.5, tif: 'DAY',
}) as OptionOrderRequest;

describe('captureBrokerRequest', () => {
  it('is the draft order at the reviewed quantity plus the durable attempt identity, frozen', () => {
    const req = captureBrokerRequest(ORDER, 2, 'REC-1');
    expect(JSON.stringify(req)).toBe(JSON.stringify({
      broker: 'ibkr_paper', symbol: 'AAA', option_symbol: 'AAA|150|2026-05-15|C',
      action: 'BUY', effect: 'OPEN', quantity: 2, order_type: 'LMT', limit_price: 2.5, tif: 'DAY',
      attempt_id: 'opt-REC-1', saved_rec_id: 'REC-1',
    }));
    expect(Object.isFrozen(req)).toBe(true);
    expect(ORDER.quantity).toBe(4);
  });

  it('derives one stable attempt id per saved row', () => {
    expect(attemptIdFor('REC-1')).toBe('opt-REC-1');
    expect(captureBrokerRequest(ORDER, 1, 'REC-1').attempt_id).toBe(captureBrokerRequest(ORDER, 3, 'REC-1').attempt_id);
  });
});

describe('destination', () => {
  it('names only the mode the broker key states', () => {
    expect(brokerModeOf('ibkr_paper')).toBe('Paper');
    expect(brokerModeOf('tradier_paper')).toBe('Paper');
    expect(brokerModeOf('mystery')).toBe('Unknown');
  });

  it('the final action names the destination and the reviewed order', () => {
    expect(confirmLabelFor('IBKR Paper', captureBrokerRequest(ORDER, 2, 'R'))).toBe('Send to IBKR Paper — Limit 2 @ $2.50');
    expect(confirmLabelFor('Tradier Paper', captureBrokerRequest({ ...ORDER, order_type: 'MKT', limit_price: null }, 1, 'R')))
      .toBe('Send to Tradier Paper — Market 1');
  });
});

describe('responseFacts', () => {
  it('reads only order id, status, broker and deduplication', () => {
    expect(responseFacts({ order_id: ' ORD-1 ', status: 'Submitted', broker: 'ibkr_paper', deduped: true, fill_price: 9 }))
      .toEqual({ orderId: 'ORD-1', status: 'Submitted', broker: 'ibkr_paper', deduped: true });
    expect(responseFacts({ order_id: 'unknown', status: '' })).toEqual({ orderId: null, status: null, broker: null, deduped: false });
    expect(responseFacts(null)).toEqual({ orderId: null, status: null, broker: null, deduped: false });
  });
});

describe('outcomeLines', () => {
  const base = (over: Partial<DirectOrderOutcome>): DirectOrderOutcome => ({
    label: 'AAA 150C 05/15/26',
    brokerLabel: 'IBKR Paper',
    request: captureBrokerRequest(ORDER, 2, 'REC-1'),
    response: { orderId: 'ORD-1', status: 'Submitted', broker: 'ibkr_paper', deduped: false },
    verdict: 'placed',
    recorded: { quantity: 2, entryPrice: 2.61 },
    ...over,
  });
  const value = (o: DirectOrderOutcome, key: string) => outcomeLines(o).find((l) => l.key === key)?.value;

  it('accepted: says it is not a fill and never reports a fill price or quantity', () => {
    const o = base({});
    expect(value(o, 'status')).toMatch(/Submitted.*not a fill/);
    expect(value(o, 'fillPrice')).toMatch(/^Unavailable/);
    expect(value(o, 'filledQty')).toMatch(/^Unavailable/);
    expect(value(o, 'recorded')).toMatch(/2 contracts.*\$2\.61.*not a fill/);
    expect(value(o, 'quantity')).toMatch(/requested 2 = recorded 2/);
  });

  it('a Filled status is reported as the broker\'s word, without inventing its numbers', () => {
    const o = base({ response: { orderId: 'ORD-1', status: 'Filled', broker: 'ibkr_paper', deduped: false } });
    expect(value(o, 'status')).toMatch(/Filled.*no fill price or filled quantity/);
    expect(value(o, 'fillPrice')).toMatch(/^Unavailable/);
  });

  it.each(['PartiallyFilled', 'partially_filled', 'Held'])('%s: reported as the broker said it, never called "not a fill"', (status) => {
    const o = base({ response: { orderId: 'ORD-1', status, broker: 'ibkr_paper', deduped: false } });
    expect(value(o, 'status')).toContain(status);
    expect(value(o, 'status')).not.toMatch(/not a fill/);
    expect(value(o, 'status')).toMatch(/check IBKR Paper/);
    expect(value(o, 'fillPrice')).toMatch(/^Unavailable/);
    expect(value(o, 'filledQty')).toMatch(/^Unavailable/);
  });

  it('a duplicate says no second order was sent', () => {
    expect(value(base({ response: { orderId: 'ORD-1', status: 'Submitted', broker: 'ibkr_paper', deduped: true } }), 'deduped'))
      .toMatch(/no second order/);
  });

  it('a broker that answers under another name is flagged, not hidden', () => {
    expect(value(base({ response: { orderId: 'ORD-1', status: 'Submitted', broker: 'tradier_paper', deduped: false } }), 'broker'))
      .toMatch(/differs from the request \(ibkr_paper\)/);
  });

  it('rejected and unknown outcomes', () => {
    const rejected = base({ verdict: 'delete', recorded: null, response: { orderId: 'ORD-R', status: 'Rejected', broker: 'ibkr_paper', deduped: false } });
    expect(value(rejected, 'status')).toMatch(/^Not placed — broker status Rejected/);
    expect(value(rejected, 'recorded')).toMatch(/Removed/);
    expect(value(base({ verdict: 'delete', recorded: null, response: null }), 'status')).toMatch(/^Not placed — refused before the broker received it/);
    const unknown = base({ verdict: 'keep', response: null });
    expect(value(unknown, 'status')).toMatch(/^Unknown — no usable broker answer; check IBKR Paper/);
    expect(value(unknown, 'orderId')).toBe('Not reported');
  });
});
