import { classifyDirectFailure, isAcceptedNotFilled } from '@/lib/directOrder';

describe('accepted broker status is not a fill', () => {
  it('treats accepted and pending statuses as submitted, not filled', () => {
    expect(isAcceptedNotFilled('accepted')).toBe(true);
    expect(isAcceptedNotFilled('PreSubmitted')).toBe(true);
    expect(isAcceptedNotFilled('Submitted')).toBe(true);
    expect(isAcceptedNotFilled('filled')).toBe(false);
    expect(isAcceptedNotFilled('partially_filled')).toBe(false);
  });

  it('does not describe an accepted order id as filled', () => {
    const outcome = classifyDirectFailure({ response: { order_id: 'ORD-1', status: 'accepted' } });
    expect(outcome).toEqual({ verdict: 'placed', orderId: 'ORD-1' });
    expect(JSON.stringify(outcome).toLowerCase()).not.toContain('filled');
  });

  it('still classifies a genuine pre-submit refusal as safe to remove', () => {
    expect(classifyDirectFailure({
      thrown: new Error('API /broker/stock-order → 422: bad qty'),
    }).verdict).toBe('delete');
    expect(classifyDirectFailure({
      thrown: new Error('API /broker/stock-order → 504: Gateway Timeout'),
    }).verdict).toBe('keep');
  });
});

/* #593: tradier_paper.py and ibkr_paper.py build order_id with str(...), so a
   JSON-null id arrives as the text "None" in a 200 body. */
describe('an order id that is only the text of a missing value', () => {
  const NULL_TEXT_IDS = ['None', 'null', 'NONE', ' none '];

  it.each(NULL_TEXT_IDS)('"%s" with a non-terminal status keeps the row with no order id', (id) => {
    const outcome = classifyDirectFailure({ response: { order_id: id, status: 'Submitted' } });
    expect(outcome).toEqual({
      verdict: 'keep',
      why: 'broker reply had no usable order ID (status Submitted)',
      orderId: null,
    });
  });

  it.each(NULL_TEXT_IDS)('"%s" with a terminal keep status carries no order id', (id) => {
    expect(classifyDirectFailure({ response: { order_id: id, status: 'Inactive' } })).toEqual({
      verdict: 'keep',
      why: 'broker status Inactive',
      orderId: null,
    });
  });

  it.each(NULL_TEXT_IDS)('"%s" with status Rejected still deletes the row', (id) => {
    expect(classifyDirectFailure({ response: { order_id: id, status: 'Rejected' } }).verdict).toBe('delete');
  });

  it('a real order id is still placed', () => {
    expect(classifyDirectFailure({ response: { order_id: '12345', status: 'Submitted' } }))
      .toEqual({ verdict: 'placed', orderId: '12345' });
  });

  it('a real order id that merely contains the text is still placed', () => {
    expect(classifyDirectFailure({ response: { order_id: 'none-123', status: 'Submitted' } }))
      .toEqual({ verdict: 'placed', orderId: 'none-123' });
  });
});
