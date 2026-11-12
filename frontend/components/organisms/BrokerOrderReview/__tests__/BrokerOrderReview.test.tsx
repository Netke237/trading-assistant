import '@testing-library/jest-dom';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { BrokerOrderReview, type BrokerOrderReviewData } from '@/components/organisms/BrokerOrderReview';
import type { ReviewLine } from '@/lib/trackingReview';

/* #609 (TC-ALIGN-06) — the broker review reads destination-first: where the
 * order goes and what it asks for, the actual position settings (in-app
 * alerts, never broker orders) and the target-alert basis are visible; mode,
 * time in force and the exact request JSON sit in one closed disclosure. The
 * re-review and changed-value warnings stay visible and still block sending. */

const line = (key: string, label: string, requested: string, effective: string, note: string | null = null): ReviewLine =>
  ({ key, label, requested, effective, adjusted: note != null, note });

function data(o: Partial<Record<keyof BrokerOrderReviewData | 'expiry', unknown>> = {}): BrokerOrderReviewData {
  const d = {
    label: 'AAA 150C 05/15/26',
    brokerLabel: 'IBKR Paper',
    account: 'DU123',
    expiry: '2026-05-15',
    request: Object.freeze({
      broker: 'ibkr_paper', symbol: 'AAA', option_symbol: 'AAA|150|2026-05-15|C', action: 'BUY', effect: 'OPEN',
      quantity: 2, order_type: 'LMT', limit_price: 2.5, tif: 'DAY', attempt_id: 'opt-REC-1', saved_rec_id: 'REC-1',
    }),
    requestedQuantity: 3,
    quantityNote: 'reduced to fit the exposure limit',
    marketMid: 2.55,
    savedEntry: 2.6,
    lines: [
      line('contract', 'Contract', 'AAA|150|2026-05-15|C', 'AAA|150|2026-05-15|C'),
      line('qty', 'Quantity', '3', '2', 'reduced to fit the exposure limit'),
      line('entry', 'Tracked entry price', '$2.50/share', '$2.60/share · save-time live quote', 're-quoted at save'),
      line('stop', 'Stock stop', '$140.00 · plan level', '$141.00', 're-anchored to the live underlying'),
      line('structuralStop', 'Structural stop', 'Unset', 'Unset'),
      line('premiumStop', 'Premium stop', 'Inherits global 60.0%', 'Inherits global 60.0%'),
      line('targets', 'Ladder targets', '$160.00', '$161.00'),
      line('targetAlert', 'Target alert', 'Live Ladder', 'Live Ladder'),
      line('value', 'Est. position value', '$500', '$520'),
    ],
    changedSinceReview: null,
    ...o,
  };
  return d as BrokerOrderReviewData;
}

function show(d = data(), stale: string[] = []) {
  const onConfirm = jest.fn();
  const onRefresh = jest.fn();
  render(<BrokerOrderReview data={d} stale={stale} busy={false} onConfirm={onConfirm} onCancel={jest.fn()} onRefresh={onRefresh} />);
  const region = screen.getByRole('region', { name: 'Broker order review' });
  return { r: within(region), region, onConfirm, onRefresh };
}
const dd = (scope: ReturnType<typeof within>, label: string) => scope.getByText(label, { selector: 'dt' }).nextElementSibling as HTMLElement;
const detailsOf = (region: HTMLElement) => region.querySelector('details[data-review-details]') as HTMLDetailsElement;

describe('BrokerOrderReview — concise destination-first arrangement (#609)', () => {
  it('shows destination, contract with full expiry, quantity, order, actual settings and target-alert basis first', () => {
    const { r } = show();
    const dest = within(r.getByRole('group', { name: 'Destination and request' }));
    expect(dd(dest, 'Destination')).toHaveTextContent('IBKR Paper');
    expect(dd(dest, 'Account')).toHaveTextContent('DU123');
    expect(dd(dest, 'Contract')).toHaveTextContent('AAA 150C 05/15/26 · AAA|150|2026-05-15|C');
    expect(dd(dest, 'Expiry')).toHaveTextContent('2026-05-15');
    expect(dd(dest, 'Quantity')).toHaveTextContent('2 contracts (requested 3 — reduced to fit the exposure limit)');
    expect(dd(dest, 'Order type')).toHaveTextContent('Limit');
    expect(dd(dest, 'Limit price')).toHaveTextContent('$2.50');
    expect(dd(dest, 'Premium outlay (estimate)')).toHaveTextContent('Up to $500.00');
    expect(dd(dest, 'Tracked entry (quote estimate, not a fill)')).toHaveTextContent('$2.60/share · save-time live quote (requested $2.50/share — re-quoted at save)');
    for (const label of ['Destination', 'Contract', 'Expiry', 'Quantity', 'Order type', 'Limit price']) expect(dd(dest, label)).toBeVisible();

    const settings = within(r.getByRole('group', { name: 'Position settings' }));
    expect(dd(settings, 'Stock stop')).toHaveTextContent('$141.00 (requested $140.00 · plan level — re-anchored to the live underlying)');
    expect(dd(settings, 'Premium stop')).toHaveTextContent('Inherits global 60.0%');
    expect(dd(settings, 'Time-exit alert')).toHaveTextContent('≤3 days to expiry');
    expect(settings.getByText(/No stop-loss or take-profit order is sent to the broker/)).toBeVisible();

    const target = within(r.getByRole('group', { name: 'Target alert basis' }));
    expect(dd(target, 'Target alert')).toHaveTextContent('Live Ladder');
    expect(dd(target, 'Ladder targets')).toHaveTextContent('$161.00');
    expect(dd(target, 'Target alert')).toBeVisible();
  });

  it('folds mode, time in force and the exact request into one closed disclosure kept in the DOM', () => {
    const { region } = show();
    const d = detailsOf(region);
    expect(d).not.toBeNull();
    expect(d.open).toBe(false);
    const inside = within(d);
    expect(dd(inside, 'Mode')).toHaveTextContent('Paper');
    expect(dd(inside, 'Time in force')).toHaveTextContent('DAY');
    expect(dd(inside, 'Mode')).not.toBeVisible();
    expect(inside.getByTestId('broker-request')).not.toBeVisible();
    expect(inside.getByTestId('broker-request').textContent).toBe(JSON.stringify(data().request));
  });

  it.each([
    ['DU123', 'DU123', 'As entered in Settings → Brokers; the server sends with its stored credentials and does not echo the account'],
    [null, 'Not set', 'Not set in Settings → Brokers; the server sends with its stored credentials'],
  ])('keeps account %s concise while retaining the credential explanation in technical details', (account, value, explanation) => {
    const { r, region } = show(data({ account }));
    const dest = within(r.getByRole('group', { name: 'Destination and request' }));
    expect(dd(dest, 'Account')).toHaveTextContent(new RegExp(`^${value}$`));
    expect(dd(dest, 'Account')).toBeVisible();
    const technical = detailsOf(region);
    expect(technical.open).toBe(false);
    expect(within(technical).getByText(explanation!)).not.toBeVisible();
    fireEvent.click(within(technical).getByText('Technical details · exact broker request'));
    expect(within(technical).getByText(explanation!)).toBeVisible();
  });

  it('makes the outlay estimate easy to scan and keeps the limit-fill qualification visible', () => {
    const { r } = show();
    const dest = within(r.getByRole('group', { name: 'Destination and request' }));
    const outlay = within(dd(dest, 'Premium outlay (estimate)'));
    expect(outlay.getByText('Up to $500.00', { exact: true })).toBeVisible();
    expect(outlay.getByText(/2 × limit × 100; a buy limit fills at or below it, if at all \(estimate\)/)).toBeVisible();
  });

  it('keeps the changed-since-review and server-change warnings visible and still blocks sending', () => {
    const { r, region, onConfirm, onRefresh } = show(data({ changedSinceReview: ['Tracked entry price'] }), ['limitPrice']);
    const changed = r.getByText(/The server values changed since your review/);
    const stale = r.getByText(/Changed since this review: limit price/);
    for (const el of [changed, stale]) {
      expect(el).toBeVisible();
      expect(detailsOf(region).contains(el)).toBe(false);
    }
    const confirm = r.getByRole('button', { name: /^Send to IBKR Paper/ });
    expect(confirm).toBeDisabled();
    fireEvent.click(confirm);
    expect(onConfirm).not.toHaveBeenCalled();
    fireEvent.click(r.getByRole('button', { name: 'Refresh review' }));
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it('a market review keeps the unknown fill visible beside the request', () => {
    const d = data();
    const { r } = show({ ...d, request: Object.freeze({ ...d.request, order_type: 'MKT', limit_price: null }) } as BrokerOrderReviewData);
    const dest = within(r.getByRole('group', { name: 'Destination and request' }));
    expect(dd(dest, 'Limit price')).toHaveTextContent('fills at the market price, unknown until execution');
    expect(dd(dest, 'Limit price')).toBeVisible();
    expect(dd(dest, 'Premium outlay (estimate)')).toHaveTextContent('the market fill is unknown until execution');
  });
});
