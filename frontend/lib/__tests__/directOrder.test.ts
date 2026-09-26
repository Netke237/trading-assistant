import {
  brokerLabelFor,
  classifyDirectFailure, directOrderBlock, directSendNoteText, isNotFound, removeConfirmText, whyOf,
} from '@/lib/directOrder';
import type { DirectSendNote } from '@/lib/directSendNotesStore';

/*
 * P1b-i §2.1 / §2.5 — the rules that decide whether a direct send's saved row
 * may be deleted. The row is deleted ONLY when the failure provably happened
 * before the broker received the order; everything else keeps it.
 */

const thrown = (status: number, detail: string) =>
  classifyDirectFailure({ thrown: new Error(`API /broker/option-order → ${status}: ${detail}`) });
const replied = (response: unknown) => classifyDirectFailure({ response });

describe('directOrderBlock (plan test 12, unit)', () => {
  it('refuses a Market order on Tastytrade paper', () => {
    expect(directOrderBlock('MKT', 'tastytrade_paper')).toBe('Tastytrade paper accepts limit orders only — use Place Limit.');
  });
  it('lets a Limit order on Tastytrade, and a Market order elsewhere, through', () => {
    expect(directOrderBlock('LMT', 'tastytrade_paper')).toBeNull();
    expect(directOrderBlock('MKT', 'ibkr_paper')).toBeNull();
  });
});

describe('classifyDirectFailure — provably pre-submit throws delete the row', () => {
  it.each([
    [422, 'quantity: Input should be greater than 0'],
    [503, 'Broker credentials unavailable: ibkr_paper'],
    [400, 'live trading via ibkr is not enabled'],
    [400, 'Unknown broker: foo'],
    [502, 'IBKR did not place the order: it asked for a confirmation'],
  ])('%i %s', (status, detail) => {
    expect(thrown(status, detail)).toEqual({ verdict: 'delete', why: detail });
  });
});

describe('classifyDirectFailure — everything else keeps the row', () => {
  it.each([
    [400, 'Expecting value: line 1 column 1'],
    [502, 'Tradier paper order failed: HTTP 401 unauthorized'],
    // The markers, present but NOT as the prefix (M22).
    [502, 'Tradier paper order failed: HTTP 400 — IBKR did not place the order: x'],
    [400, 'x Unknown broker y'],
    [503, 'x Broker credentials unavailable'],
    [500, 'boom'],
  ])('%i %s', (status, detail) => {
    expect(thrown(status, detail)).toEqual({ verdict: 'keep', why: detail, orderId: null });
  });

  it('a TypeError (network) keeps, and `why` is String(e)', () => {
    const e = new TypeError('Failed to fetch');
    expect(classifyDirectFailure({ thrown: e })).toEqual({ verdict: 'keep', why: 'TypeError: Failed to fetch', orderId: null });
  });

  it('a plain Error keeps, with `why` = String(e)', () => {
    expect(classifyDirectFailure({ thrown: new Error('boom') })).toEqual({ verdict: 'keep', why: 'Error: boom', orderId: null });
  });

  it('a non-Error throw never yields an undefined `why`', () => {
    const r = classifyDirectFailure({ thrown: undefined });
    expect(r.verdict).toBe('keep');
    expect((r as { why: string }).why).toBe('undefined');
  });
});

describe('classifyDirectFailure — 2xx replies', () => {
  it('a usable id with a live status is placed', () => {
    expect(replied({ order_id: 'ORD-1', status: 'Submitted' })).toEqual({ verdict: 'placed', orderId: 'ORD-1' });
    expect(replied({ order_id: ' ORD-2 ' })).toEqual({ verdict: 'placed', orderId: 'ORD-2' });
  });

  it.each(['Rejected', ' REJECTED ', 'OrderStatus.REJECTED'])('status %j deletes', (status) => {
    expect(replied({ order_id: 'ORD-1', status }).verdict).toBe('delete');
  });

  it.each(['Inactive', 'Error', 'Canceled', 'Cancelled', 'Expired', 'Removed', 'Partially Removed'])(
    'status %j keeps, carrying the id (M29)', (status) => {
      expect(replied({ order_id: 'ORD-9', status })).toEqual({ verdict: 'keep', why: `broker status ${status}`, orderId: 'ORD-9' });
    },
  );

  it.each([
    ['blank id', { order_id: '', status: 'Submitted' }],
    ['"unknown" id', { order_id: ' Unknown ', status: 'Submitted' }],
    ['no id field', { status: 'Submitted' }],
    ['numeric id', { order_id: 42 }],
    ['null body', null],
  ])('%s keeps with no id and never says "undefined"', (_n, body) => {
    const r = replied(body);
    expect(r).toMatchObject({ verdict: 'keep', orderId: null });
    expect(JSON.stringify(r)).not.toMatch(/undefined/);
  });
});

describe('whyOf / isNotFound', () => {
  it('reads the detail after `→ NNN: `, else String(e)', () => {
    expect(whyOf(new Error('API /x → 500: bad'))).toBe('bad');
    expect(whyOf(new Error('API /x → 404'))).toBe('Error: API /x → 404');
  });
  it('recognises a 404 with or without a detail', () => {
    expect(isNotFound(new Error('API /api/portfolio/R → 404: Position not found'))).toBe(true);
    expect(isNotFound(new Error('API /api/portfolio/R → 404'))).toBe(true);
    expect(isNotFound(new Error('API /api/portfolio/R → 500: 404'))).toBe(false);
  });
});

describe('note and confirm texts (plan A2, A3)', () => {
  const base: DirectSendNote = {
    recId: 'REC-1', kind: 'order-unknown', label: 'AAA 150C 05/15/26', brokerLabel: 'IBKR Paper',
    orderId: null, status: null, removing: false,
  };
  it('ORDER-UNKNOWN names the rec_id and the broker, and the id when there is one', () => {
    expect(directSendNoteText(base)).toBe(
      'AAA 150C 05/15/26: order status UNKNOWN (rec_id REC-1). Check IBKR Paper first. If an order exists there, keep this position. If none does, press Remove.',
    );
    expect(directSendNoteText({ ...base, orderId: 'ORD-9' })).toContain('UNKNOWN (broker order ID ORD-9) (rec_id REC-1)');
  });
  it('SAVE-UNCONFIRMED and NOT-REMOVED name the rec_id', () => {
    expect(directSendNoteText({ ...base, kind: 'save-unconfirmed' })).toBe(
      'AAA 150C 05/15/26: NO order was sent, but Portfolio may still have saved this send (rec_id REC-1). Press Remove to delete that saved row.',
    );
    expect(directSendNoteText({ ...base, kind: 'not-removed' })).toBe(
      'AAA 150C 05/15/26: NO order was placed, but its tracked position could not be removed (rec_id REC-1). Press Remove to try again.',
    );
  });
  it('the ORDER-UNKNOWN confirm warns ONLY-if and names the broker', () => {
    expect(removeConfirmText(base)).toContain('ONLY if IBKR Paper shows no order');
    expect(removeConfirmText({ ...base, kind: 'save-unconfirmed' })).toBe(
      'Delete the saved AAA 150C 05/15/26 row (rec_id REC-1)? No order was placed for it.',
    );
  });
});

describe('brokerLabelFor (stock plan R1)', () => {
  it('names each paper broker, Alpaca included', () => {
    expect(brokerLabelFor('ibkr_paper')).toBe('IBKR Paper');
    expect(brokerLabelFor('tradier_paper')).toBe('Tradier Paper');
    expect(brokerLabelFor('tastytrade_paper')).toBe('Tastytrade Paper');
    expect(brokerLabelFor('alpaca_paper')).toBe('Alpaca Paper');
  });
  it('shows an unknown key as itself, never as another broker', () => {
    expect(brokerLabelFor('foo_paper')).toBe('foo_paper');
  });
});
