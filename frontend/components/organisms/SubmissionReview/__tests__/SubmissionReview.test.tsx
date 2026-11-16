import '@testing-library/jest-dom';
import { render, screen, within } from '@testing-library/react';
import { SubmissionReview, SubmissionReviewWarnings } from '@/components/organisms/SubmissionReview';
import { buildSubmissionDraft, type SubmissionInputs } from '@/lib/submissionDraft';
import type { ExitPlan, MethodPick, TradeCardData } from '@/types/domain';

/* #581 — the review renders a draft and nothing else. Every fallback text is
 * the existing server rule (services/picked_method.py seed_tp_from_pick): a
 * request with no positive stock-price target starts the target alert on the
 * live first Ladder target; an Arithmetic target maps to an attached plan row
 * or degrades to the Ladder. The EFFECTIVE alert is never resolved here. */

const card: TradeCardData = {
  symbol: 'AAA', company: 'AAA Inc.', price: 150, direction: 'Bullish', status: 'PASS',
  stockScore: 80, stockConfidence: 'PASS',
  stockBreakdown: { trend: 80, pullback: 80, trigger: 80, event: 80, volatility: 80 },
  contract: 'AAA 150C 05/15', contractScore: 70, contractConfidence: 'PASS',
  contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 60 },
  contractDetails: { strike: 150, expiry: '2026-05-15', right: 'C', mid: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 },
  entry: { limit: 2.5, maxFill: 2.63, orderType: 'Limit' },
  exit: { invalidation: 140, premiumStop: 1.5, timeStopDays: 10, target: 160, targets: [] },
  rrRatio: 2, rrModel: 'Heston repriced', finalStatus: 'PASS',
};
const plan = (rows: Array<[number, number]>): ExitPlan => ({
  computedAt: '2026-09-14T10:00:00Z',
  stop: { price: 131 } as any,
  targets: rows.map(([rrRatio, price]) => ({ rrRatio, price })) as any,
  atr: 4,
} as ExitPlan);
const pick = (o: Partial<MethodPick>): MethodPick => ({
  method: 'ladder', rowStockPrice: 160, rowOptionPrice: null, stopBasis: 'stock', pickedAt: '2026-09-14T10:00:00.000Z', ...o,
});
const inputs = (o: Partial<SubmissionInputs>): SubmissionInputs => ({
  card, contracts: 1, livePrice: null, invalidation: 140, invalidationIsUserSet: false, entryLimit: 2.5,
  premiumStopDollar: null, structuralStop: null, exitPlan: null, maxLossOverride: null, pick: null, ...o,
});
function show(o: Partial<SubmissionInputs>, broker: string | null = 'ibkr_paper') {
  render(<SubmissionReview draft={buildSubmissionDraft(inputs(o), { broker, globalPremiumStopPct: 0.6 })} generation={4} />);
  return within(screen.getByRole('region', { name: 'Submission review' }));
}
const value = (r: ReturnType<typeof show>, label: string) => r.getByText(label, { selector: 'dt' }).nextElementSibling as HTMLElement;
const NO_TP_ORDER = /no option-price take-profit order is placed/i;

describe('SubmissionReview — target-alert fallback display', () => {
  it('unreachable Monte Carlo target: no stock target sent, live-Ladder fallback, premium is record-only', () => {
    const r = show({ pick: pick({ method: 'monte_carlo', rowStockPrice: null, rowOptionPrice: 6.24 }) });
    expect(value(r, 'Method')).toHaveTextContent('Monte Carlo');
    expect(value(r, 'Recorded stock target')).toHaveTextContent('None sent');
    expect(value(r, 'Recorded option target')).toHaveTextContent('$6.24/share (record only — never a take-profit order)');
    expect(value(r, 'Intended basis')).toHaveTextContent('Live Ladder fallback');
    expect(value(r, 'Effective target alert')).toHaveTextContent('Unresolved until server review');
    expect(r.getByText(/no stock-price equivalent/)).toBeInTheDocument();
    expect(r.getByText(NO_TP_ORDER)).toBeInTheDocument();
  });

  it('Barrier Race: an option premium only, live-Ladder fallback, never a TP order', () => {
    const r = show({ pick: pick({ method: 'barrier_race', rowStockPrice: null, rowOptionPrice: 7.25 }) });
    expect(value(r, 'Method')).toHaveTextContent('Barrier Race');
    expect(value(r, 'Intended basis')).toHaveTextContent('Live Ladder fallback');
    expect(r.getByText(/Barrier Race rows carry an option premium and no stock level/)).toBeInTheDocument();
    expect(r.getByText(NO_TP_ORDER)).toBeInTheDocument();
  });

  it('ambiguous Arithmetic target: equal rows with different R multiples degrade to the Ladder', () => {
    const r = show({ pick: pick({ method: 'arithmetic', rowStockPrice: 170 }), exitPlan: plan([[2, 170], [3, 170]]) });
    expect(value(r, 'Intended basis')).toHaveTextContent('Live Ladder fallback');
    expect(r.getByText(/match the recorded target equally/)).toBeInTheDocument();
  });

  it('unmappable Arithmetic target (no plan attached) degrades to the Ladder', () => {
    const r = show({ pick: pick({ method: 'arithmetic', rowStockPrice: 170 }) });
    expect(value(r, 'Intended basis')).toHaveTextContent('Live Ladder fallback');
    expect(r.getByText(/No Arithmetic plan is attached/)).toBeInTheDocument();
  });

  it('mapped Arithmetic and reachable Monte Carlo targets are REQUESTED, not promised', () => {
    let r = show({ pick: pick({ method: 'arithmetic', rowStockPrice: 185 }), exitPlan: plan([[2, 170], [3, 185]]) });
    expect(value(r, 'Intended basis')).toHaveTextContent('Arithmetic 3:1 row at $185.00 stock (requested)');
    expect(value(r, 'Effective target alert')).toHaveTextContent('Unresolved until server review');
    document.body.innerHTML = '';
    r = show({ pick: pick({ method: 'monte_carlo', rowStockPrice: 197.5, rowOptionPrice: 6.24 }) });
    expect(value(r, 'Intended basis')).toHaveTextContent('Monte Carlo stock level $197.50 (requested)');
  });

  it('Ladder row: the live Ladder, no fixed price stored', () => {
    const r = show({ pick: pick({}) });
    expect(value(r, 'Intended basis')).toHaveTextContent('Live Ladder — follows the first Ladder target');
  });

  it('carries its generation and fingerprint for parity checks', () => {
    show({ pick: pick({}) });
    const region = screen.getByRole('region', { name: 'Submission review' });
    expect(region).toHaveAttribute('data-generation', '4');
    expect(region.getAttribute('data-fingerprint')).toBeTruthy();
  });

  it('Tastytrade paper: the market route shows the existing refusal', () => {
    const r = show({ pick: pick({}) }, 'tastytrade_paper');
    expect(value(r, 'Right Now — Market')).toHaveTextContent(/limit orders only/);
  });
});

/* #609 (TC-ALIGN-06) — the review reads destination-first. What is sent and
 * where comes first, in three visible groups; generation, provenance and the
 * long resolution explanations sit in ONE native closed disclosure that stays
 * in the DOM; every warning, refusal and provisional label stays visible. */
describe('SubmissionReview — concise destination-first arrangement (#609)', () => {
  const group = (r: ReturnType<typeof show>, name: string) => within(r.getByRole('group', { name }));
  const details = () => screen.getByRole('region', { name: 'Submission review' }).querySelector('details[data-review-details]') as HTMLDetailsElement;
  const outsideDetails = (el: HTMLElement) => expect(details().contains(el)).toBe(false);

  it('shows destination, contract with full expiry, quantity, order basis, actual exits and target-alert basis first', () => {
    const r = show({ pick: pick({ method: 'monte_carlo', rowStockPrice: 197.5, rowOptionPrice: 6.24 }), contracts: 2 });
    const dest = group(r, 'Destination and request');
    for (const label of ['Track basket', 'Place Limit', 'Right Now — Market', 'Contract', 'Expiry', 'Quantity', 'Entry limit', 'Entry basis sent']) {
      expect(dest.getByText(label, { selector: 'dt' })).toBeVisible();
    }
    expect(dest.getByText('Track basket', { selector: 'dt' }).nextElementSibling).toHaveTextContent('Portfolio row only — no broker order');
    expect(dest.getByText('Place Limit', { selector: 'dt' }).nextElementSibling).toHaveTextContent('IBKR Paper · BUY to open 2 × AAA|150|2026-05-15|C · LMT $2.50 · DAY');
    expect(dest.getByText('Contract', { selector: 'dt' }).nextElementSibling).toHaveTextContent('AAA|150|2026-05-15|C');
    expect(dest.getByText('Expiry', { selector: 'dt' }).nextElementSibling).toHaveTextContent('2026-05-15 · 24 DTE');
    expect(dest.getByText('Quantity', { selector: 'dt' }).nextElementSibling).toHaveTextContent('2 contracts × 100 = 200 shares');

    const settings = group(r, 'Position settings');
    for (const label of ['Stock stop', 'Premium stop', 'Time-exit alert']) {
      expect(settings.getByText(label, { selector: 'dt' })).toBeVisible();
    }
    expect(settings.getByText('Stock stop', { selector: 'dt' }).nextElementSibling).toHaveTextContent('$140.00 stock');
    expect(settings.getByText('Time-exit alert', { selector: 'dt' }).nextElementSibling).toHaveTextContent('≤3 days to expiry');
    expect(settings.getByText(/No protective stop-loss or take-profit order is sent to a broker/)).toBeVisible();

    const target = group(r, 'Target alert basis');
    for (const label of ['Method', 'Judged on', 'Intended basis', 'Effective target alert']) {
      expect(target.getByText(label, { selector: 'dt' })).toBeVisible();
    }
    expect(target.getByText('Intended basis', { selector: 'dt' }).nextElementSibling).toHaveTextContent('Monte Carlo stock level $197.50 (requested)');
  });

  it('folds generation, attached-plan provenance and long explanations into one closed disclosure kept in the DOM', () => {
    const r = show({ pick: pick({ method: 'arithmetic', rowStockPrice: 185 }), exitPlan: plan([[2, 170], [3, 185]]) });
    const d = details();
    expect(d).not.toBeNull();
    expect(d.open).toBe(false);
    expect(d.querySelector('summary')).toHaveTextContent('Technical details and provenance');
    const inside = within(d);
    expect(inside.getByText(/Draft generation 4/)).not.toBeVisible();
    expect(inside.getByText('Arithmetic plan attached', { selector: 'dt' })).not.toBeVisible();
    expect(value(r, 'Arithmetic plan attached')).toHaveTextContent('Yes — computed 2026-09-14T10:00:00Z');
    expect(inside.getByText(/re-fetches the option quote when clicked/)).not.toBeVisible();
    expect(inside.getByText(/The server decides the effective alert price when it saves the position/)).not.toBeVisible();
    expect(inside.getByText(/calculation results; they are not submitted/)).not.toBeVisible();
  });

  it('keeps provisional, unresolved, fallback and blocked-route warnings visible outside the disclosure', () => {
    const noExpiry: TradeCardData = { ...card, contractDetails: { ...card.contractDetails!, expiry: undefined as unknown as string } };
    const r = show({ card: noExpiry, pick: pick({ method: 'barrier_race', rowStockPrice: null, rowOptionPrice: 7.25 }) });
    const refusals = r.getAllByText(/refused before sending: This contract has no expiry date/);
    expect(refusals).toHaveLength(2);
    for (const el of refusals) { expect(el).toBeVisible(); outsideDetails(el); }
    expect(value(r, 'Expiry')).toHaveTextContent('Not supplied');
    expect(value(r, 'Expiry')).toBeVisible();
    const provisional = value(r, 'Entry basis sent');
    expect(provisional).toHaveTextContent('provisional; the server re-quotes at save (not a fill)');
    expect(provisional).toBeVisible();
    expect(value(r, 'Effective target alert')).toHaveTextContent('Unresolved until server review');
    expect(value(r, 'Effective target alert')).toBeVisible();
    const fallback = r.getByText(/Barrier Race rows carry an option premium and no stock level/);
    expect(fallback).toBeVisible();
    outsideDetails(fallback);
  });

  it('keeps the no-method block and the spread notice visible', () => {
    const spread: TradeCardData = {
      ...card, spreadType: 'bear_call',
      legs: [
        { action: 'SELL', qty: 1, strike: 150, right: 'C', expiry: '2026-05-15', bid: 2.4, ask: 2.6 },
        { action: 'BUY', qty: 1, strike: 155, right: 'C', expiry: '2026-05-15', bid: 1.1, ask: 1.3 },
      ] as never,
    };
    const r = show({ card: spread, pick: null });
    expect(r.getByText('Sending stays blocked until a method is chosen.')).toBeVisible();
    expect(r.getByText(/only the selected contract is submitted/)).toBeVisible();
  });

  it('names the selected-target review, not the removed Final Recommendation', () => {
    show({ pick: pick({}) });
    const region = screen.getByRole('region', { name: 'Submission review' });
    expect(region).not.toHaveTextContent(/Final Recommendation/);
    expect(within(details()).getByText(/Your selected target/)).toBeInTheDocument();
  });
});


describe('#610 notices outside the closed inline transport detail', () => {
  it('keeps provisional/server resolution, missing-selection and route refusals visible', () => {
    const draft = buildSubmissionDraft(inputs({ invalidation: null, pick: null }), { broker: 'tastytrade_paper', globalPremiumStopPct: 0.6 });
    const { container } = render(<>
      <details><summary>Request detail</summary><SubmissionReview draft={draft} generation={1} /></details>
      <SubmissionReviewWarnings draft={draft} />
    </>);
    const notices = within(container.querySelector('[data-submission-notices]') as HTMLElement);
    for (const pattern of [/Entry basis is provisional/, /Exit settings are in-app alerts; no protective stop-loss or take-profit order/, /Sending stays blocked until a method is chosen/, /Missing — sending is blocked until a stock stop is set/, /Right Now — Market refused before sending/]) {
      expect(notices.getByText(pattern)).toBeVisible();
    }
    expect(container.querySelector('details')).not.toHaveAttribute('open');
  });

  it('keeps spread and race fallback scope visible without borrowing a stock target', () => {
    const spread: TradeCardData = {
      ...card, spreadType: 'bear_put',
      legs: [
        { action: 'BUY', qty: 1, strike: 150, right: 'P', expiry: '2026-05-15', bid: 2.4, ask: 2.6 },
        { action: 'SELL', qty: 1, strike: 145, right: 'P', expiry: '2026-05-15', bid: 1.1, ask: 1.3 },
      ],
    };
    const draft = buildSubmissionDraft(inputs({ card: spread, pick: pick({ method: 'barrier_race', rowStockPrice: null, rowOptionPrice: 7.25 }) }), { broker: null, globalPremiumStopPct: 0.6 });
    render(<SubmissionReviewWarnings draft={draft} />);
    expect(screen.getByText(/only the selected contract is submitted/)).toBeVisible();
    expect(screen.getByText(/Barrier Race rows carry an option premium and no stock level/)).toBeVisible();
  });
});
