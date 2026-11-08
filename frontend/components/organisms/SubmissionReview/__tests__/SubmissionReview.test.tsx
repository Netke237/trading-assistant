import '@testing-library/jest-dom';
import { render, screen, within } from '@testing-library/react';
import { SubmissionReview } from '@/components/organisms/SubmissionReview';
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
