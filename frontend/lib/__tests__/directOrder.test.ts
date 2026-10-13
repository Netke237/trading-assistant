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
