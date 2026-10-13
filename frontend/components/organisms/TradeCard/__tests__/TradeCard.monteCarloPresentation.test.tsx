/** OPT-PRES-06: preserve returned MC targets and their own request basis. */
import '@testing-library/jest-dom';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { TradeCard } from '@/components/organisms/TradeCard';
import type { BarrierRace, FirstPassageContext, FirstPassageEstimate, TradeCardData } from '@/types/domain';

jest.mock('@/lib/api', () => ({ api: { getStructuralStop: jest.fn(), getStockQuote: jest.fn(), getContractQuote: jest.fn(), getFirstPassageEstimate: jest.fn(), getExitPlan: jest.fn() } }));
jest.mock('@/components/organisms/InlineChartPanel', () => ({ InlineChartPanel: () => <div /> }));
jest.mock('@/components/molecules/SymbolHeader', () => ({ SymbolHeader: () => <div /> }));
jest.mock('@/components/molecules/ScoreCardPanel', () => ({ ScoreCardPanel: () => <div /> }));
jest.mock('@/components/molecules/LabeledStatusBadge', () => ({ LabeledStatusBadge: () => <div /> }));
const card: TradeCardData = {
  symbol: 'AAPL', company: 'Apple', price: 185.2, direction: 'Bullish', status: 'PASS', stockScore: 82, stockConfidence: 'PASS',
  stockBreakdown: { trend: 85, pullback: 78, trigger: 72, event: 90, volatility: 65 },
  contract: 'AAPL 190C 05/15', contractScore: 70, contractConfidence: 'PASS',
  contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 60 },
  contractDetails: { strike: 190, expiry: '2026-05-15', right: 'C', mid: 5.2, delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 },
  entry: { limit: 5.2, maxFill: 5.4, orderType: 'Limit' },
  exit: { invalidation: 179.64, premiumStop: 3.12, timeStopDays: 10, target: 200.02, targets: [] },
  rrRatio: 2.5, rrModel: 'Heston repriced', finalStatus: 'PASS',
};
const estimate = (): FirstPassageEstimate => ({
  targets: [
    { pct: 0.25, optionPrice: 5, stockPrice: 195, probability: 0.6, expectedDays: 8 },
    { pct: 0.5, optionPrice: 6, stockPrice: null, probability: 0, expectedDays: null },
    { pct: 0.75, optionPrice: 7, stockPrice: 205, probability: 0.2, expectedDays: 16 },
  ], invalidation: { probability: 0.3, expectedDays: 4 },
});
const context: FirstPassageContext = { premium: 4, delta: 0.45, targetPct: { t1: 0.25, t2: 0.5, t3: 0.75 } };
const show = (ctx: FirstPassageContext | null = context, fp = estimate(), overrides: Partial<TradeCardData> = {}) => {
  render(<TradeCard data={{ ...card, ...overrides, exit: { ...card.exit, ...overrides.exit, firstPassage: fp, firstPassageContext: ctx } }} contracts={2} initialEntryLimit={8} liveMid={9} liveStockPrice={210} />);
  return within(screen.getByText('Monte Carlo Profit Target').closest('section')!);
};
beforeEach(() => { localStorage.clear(); jest.clearAllMocks(); });
it('shows the captured estimate basis, all returned premiums and outcomes rather than scan/order/live prices', () => {
  const region = show();
  expect(region.getByText('$190.00 Call')).toBeVisible();
  expect(region.getByText('Scan stock reference')).toBeVisible();
  expect(region.getByText('$185.20')).toBeVisible();
  expect(region.getByText(/Stored Monte Carlo run stock entry: unavailable/)).toBeVisible();
  expect(region.getByText('Captured request premium (rounded to cents)')).toBeVisible();
  expect(region.getByText('$4.00/share')).toBeVisible();
  expect(region.getByText('$8.00/share')).toBeVisible();
  expect(region.getByText(/2 entered contracts × 100 shares.*selected-contract full exit/)).toBeVisible();
  for (const amount of ['$200.00', '$400.00', '$600.00']) expect(region.getByText(amount)).toBeVisible();
  expect(region.getAllByText('Option premium')).toHaveLength(3);
  expect(region.getAllByText('Probability before expiry')).toHaveLength(3);
  expect(region.getByText('~8 calendar days')).toBeVisible();
  expect(region.getByText('Unavailable — no conditional median')).toBeVisible();
  expect(region.getByText('not reachable')).toBeVisible();
  expect(region.getAllByText('Structural level found')).toHaveLength(3);
  expect(region.getByText(/GBM simulated stock paths.*Black-Scholes option repricing/)).toBeVisible();
  expect(region.getByText(/even if a stop is also reached/)).toBeVisible();
  expect(region.getByText(/calendar-day steps to expiry.*24 DTE/)).toBeVisible();
  expect(region.getByText(/Monte Carlo does not propose a stop/)).toBeVisible();
  expect(region.queryByText(/Heston/)).not.toBeInTheDocument();
});
it.each([null, { ...context, premium: 0 }, { ...context, premium: NaN }])('does not invent dollar outcomes with absent/invalid request premium %p', (ctx) => {
  const region = show(ctx);
  expect(region.getAllByText('Unavailable — estimate premium basis missing')).toHaveLength(4);
  expect(region.queryByText('$200.00')).not.toBeInTheDocument();
});
it('uses only the same-result echoed race premium when restored request context is absent', () => {
  const fp = estimate();
  fp.race = { premiumUsed: 4.12, outcomes: [], premiumStopPrice: 2.47, premiumStopPct: 0.4, stockStopPrice: 180, ivSolved: true, nPaths: 2000 } satisfies BarrierRace;
  const region = show(null, fp, { spreadType: 'bear_put' });
  expect(region.getByText('Same-estimate echoed premium')).toBeVisible();
  expect(region.getByText('$4.12/share')).toBeVisible();
  expect(region.getByText('$176.00')).toBeVisible();
  expect(region.getByText(/Selected-contract basis only; this is not a whole-spread outcome/)).toBeVisible();
  expect(region.queryByText('$180.00')).not.toBeInTheDocument(); // restored race barrier remains guarded
});
it('rounds the printed request basis and returned premium consistently without rebuilding target prices', () => {
  const fp = estimate(); fp.targets = [{ ...fp.targets[0], optionPrice: 5.17 }];
  const region = show({ ...context, premium: 4.125 }, fp);
  expect(region.getByText('$4.13/share')).toBeVisible();
  expect(region.getByText('$208.00')).toBeVisible();
  expect(region.queryByText('$5.16')).not.toBeInTheDocument();
});
it('restores T1/T2/T3 inputs and retains their clamps without changing saved result rows', () => {
  const region = show();
  const t1 = region.getByRole('spinbutton', { name: 'T1 profit target %' });
  expect(t1).toHaveValue(25);
  expect(region.getByRole('spinbutton', { name: 'T2 profit target %' })).toHaveValue(50);
  expect(region.getByRole('spinbutton', { name: 'T3 profit target %' })).toHaveValue(75);
  expect(t1).toHaveAttribute('min', '1'); expect(t1).toHaveAttribute('max', '500');
  fireEvent.change(t1, { target: { value: '900' } }); expect(t1).toHaveValue(500);
  fireEvent.change(t1, { target: { value: '-10' } }); expect(t1).toHaveValue(1);
  expect(region.getByText('T25%')).toBeVisible();
  expect(region.getByText('$200.00')).toBeVisible();
});
const echo = (premiumUsed: number): BarrierRace => ({ premiumUsed, outcomes: [], premiumStopPrice: 2.47, premiumStopPct: 0.4, stockStopPrice: 180, ivSolved: true, nPaths: 2000 });
it('uses server-rounded cents at a half-cent captured request premium', () => {
  const fp = estimate(); fp.targets = [{ ...fp.targets[0], optionPrice: 5.17 }]; fp.race = echo(4.12);
  const region = show({ ...context, premium: 4.125 }, fp);
  expect(region.getByText('Same-estimate echoed premium')).toBeVisible();
  expect(region.getByText('$4.12/share')).toBeVisible();
  expect(region.getByText('$210.00')).toBeVisible();
  expect(region.getByText(/Captured request premium: \$4.125\/share/)).toBeVisible();
  expect(region.queryByText('$4.13/share')).not.toBeInTheDocument();
});
it.each([3.5, 0, NaN])('guards mismatched or invalid same-estimate echo %p', (premiumUsed) => {
  const fp = estimate(); fp.race = echo(premiumUsed);
  const region = show(context, fp);
  expect(region.getAllByText('Unavailable — estimate premium basis missing')).toHaveLength(4);
  expect(region.getAllByText('Option premium')).toHaveLength(3);
});
it('allows the valid server half-cent echo despite binary floating residue', () => {
  const fp = estimate(); fp.race = echo(2.67); fp.targets = [{ ...fp.targets[0], optionPrice: 3.21 }];
  const region = show({ ...context, premium: 2.675 }, fp);
  expect(region.getByText('$2.67/share')).toBeVisible();
  expect(region.getByText('$108.00')).toBeVisible();
});
it('preserves missing returned prices and medians instead of printing nonfinite values', () => {
  const fp = estimate(); fp.targets = [{ ...fp.targets[0], optionPrice: NaN, stockPrice: NaN, probability: NaN, expectedDays: NaN }];
  const region = show(context, fp);
  expect(region.getAllByText('Unavailable')).toHaveLength(4);
  expect(region.getByText('Unavailable — no conditional median')).toBeVisible();
});
it('matches the primary execution loss amount on the live global basis, separately from the old scan seed', () => {
  const region = show();
  const loss = within(region.getByText('Execution premium-stop loss amount').closest('div')!);
  expect(loss.getByText('$5.40/share · global 60%')).toBeVisible();
  expect(loss.queryByText(/3.12/)).not.toBeInTheDocument();
});
it('uses the primary low-premium global/pinned rules for execution loss amount', () => {
  const { rerender } = render(<TradeCard data={card} liveMid={0.01} />);
  let region = within(screen.getByText('Monte Carlo Profit Target').closest('section')!);
  expect(region.getByText('Global loss allowance: 60% (fill-derived)')).toBeVisible();
  rerender(<TradeCard data={{ ...card, contract: 'AAPL 200C 05/15' }} liveMid={0.01} initialPremiumStop={0.005} />);
  region = within(screen.getByText('Monte Carlo Profit Target').closest('section')!);
  expect(region.getByText('$0.01/share · pinned')).toBeVisible();
});
