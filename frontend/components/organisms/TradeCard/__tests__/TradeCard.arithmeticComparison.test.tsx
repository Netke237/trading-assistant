/** OPT-PRES-05: actual target rows and matched calculation-premium outcomes. */
import '@testing-library/jest-dom';
import { render, screen, within } from '@testing-library/react';
import { TradeCard } from '@/components/organisms/TradeCard';
import type { TradeCardData } from '@/types/domain';

jest.mock('@/lib/api', () => ({
  api: {
    getStructuralStop: jest.fn(), getStockQuote: jest.fn(), getContractQuote: jest.fn(),
    getFirstPassageEstimate: jest.fn(), getExitPlan: jest.fn(),
  },
}));
jest.mock('@/components/organisms/InlineChartPanel', () => ({ InlineChartPanel: () => <div /> }));
jest.mock('@/components/molecules/SymbolHeader', () => ({ SymbolHeader: () => <div /> }));
jest.mock('@/components/molecules/ScoreCardPanel', () => ({ ScoreCardPanel: () => <div /> }));
jest.mock('@/components/molecules/LabeledStatusBadge', () => ({ LabeledStatusBadge: () => <div /> }));

const card = (o: Partial<TradeCardData> = {}): TradeCardData => ({
  symbol: 'AAPL', company: 'Apple Inc.', price: 185.2, direction: 'Bullish', status: 'PASS',
  stockScore: 82, stockConfidence: 'PASS',
  stockBreakdown: { trend: 85, pullback: 78, trigger: 72, event: 90, volatility: 65 },
  contract: 'AAPL 190C 05/15', contractScore: 70, contractConfidence: 'PASS',
  contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 60 },
  contractDetails: { strike: 190, expiry: '2026-05-15', right: 'C', mid: 5.2, delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 },
  entry: { limit: 5.2, maxFill: 5.4, orderType: 'Limit' },
  exit: {
    invalidation: 179.64, premiumStop: 3.12, timeStopDays: 10, target: 200.02,
    targets: [{ id: 'tp1', stockPrice: 200.02, targetPrice: 200.02, estimatedOptionPrice: 8.0, contractsToSell: 1, status: 'PENDING', rrContribution: 1.0 }],
  },
  rrRatio: 2.5, rrModel: 'Heston repriced', finalStatus: 'PASS',
  ...o,
});

import type { ExitPlan, ExitPlanTargetRow } from '@/types/domain';
const row = (ratio: number, overrides: Partial<ExitPlanTargetRow> = {}): ExitPlanTargetRow => ({
  rrRatio: ratio, arithmeticPrice: 195, price: 196, tpSource: 'structural_snap',
  structuralPrice: 196, contractPrice: 6.5, rrModel: 'Delta approximation',
  probability: 0.6, expectedDays: 8, qualityGood: false,
  qualityReasons: ['target_capped', 'test_quality_reason'], distanceDollar: 1, toleranceDollar: 1.5, ...overrides,
});
const plan = (): ExitPlan => ({
  stop: { price: 180, source: 'structural', contractPrice: 2.2, rrModel: 'Heston repriced',
    structuralSource: 'order_block', structuralConfidence: 80, structuralPrice: 180,
    atrFloorPrice: 175, distanceDollar: 5,
    stopCost: { premium: 4, stopPrice: 180, valueAtStop: 1.8, lossDollar: 2.2,
      fraction: 0.55, passMaxFraction: 0.6, status: 'PASS', basis: 'bs_today' } },
  targets: [row(2.5), row(3.5, { contractPrice: 4, probability: 0, expectedDays: null }), row(4.5)],
  atr: 3.5, computedAt: '2026-10-13T12:00:00Z',
});
const show = (p = plan(), overrides: Partial<TradeCardData> = {}) => {
  render(<TradeCard data={card({ exit: { ...card().exit, exitPlan: p }, ...overrides })} contracts={2} liveMid={9} />);
  return within(screen.getByText('Arithmetic Profit Target').closest('section')!);
};
beforeEach(() => { localStorage.clear(); jest.clearAllMocks(); });
it('shows every custom returned row in one table with effective stock target, model and calendar median', () => {
  const region = show();
  const table = within(region.getByRole('table', { name: 'Arithmetic target comparison' }));
  expect(table.getAllByRole('row')).toHaveLength(4);
  for (const ratio of ['2.5:1 target', '3.5:1 target', '4.5:1 target']) expect(table.getByText(ratio)).toBeVisible();
  const first = within(table.getAllByRole('row')[1]);
  for (const value of ['$195.00', '$196.00', '$6.50', '60%', '~8 calendar days', 'Delta approximation', '$500.00']) expect(first.getAllByText(value).find((element) => element.closest('td'))).toBeVisible();
  expect(region.getByText(/2 entered contracts × 100 shares.*selected-contract full exit/)).toBeVisible();
  expect(region.getByText(/Stored calculation stock entry: unavailable/)).toBeVisible();
  expect(first.getByText(/Bearish target capped/)).toBeVisible();
  expect(first.getByText(/test_quality_reason/)).toBeInTheDocument();
  expect(within(table.getAllByRole('row')[2]).getByText('$0.00')).toBeVisible();
  expect(within(table.getAllByRole('row')[2]).getByText('Unavailable — no conditional median')).toBeVisible();
});
it.each(['missing', 'zero', 'nonfinite', 'mismatched'])('does not borrow scan, edited or live premium with %s calculation provenance', (basis) => {
  const p = plan();
  if (basis === 'missing') p.stop.stopCost = undefined;
  else p.stop.stopCost = { ...p.stop.stopCost!, ...(basis === 'zero' ? { premium: 0 } : basis === 'nonfinite' ? { premium: NaN } : { stopPrice: 179 }) };
  const region = show(p);
  const first = within(within(region.getByRole('table')).getAllByRole('row')[1]);
  expect(first.getByText('Unavailable — calculation premium basis missing')).toBeVisible();
  expect(region.getByText('Calculation premium used')).toBeVisible();
  expect(region.queryByText('$4.00/share')).not.toBeInTheDocument();
});
it('names spread results as selected-contract outcomes rather than whole-spread profit', () => {
  const region = show(plan(), { spreadType: 'bear_put' });
  expect(region.getByText(/Selected-contract basis only; this is not a whole-spread outcome/)).toBeVisible();
});
it('retains absent estimates instead of inventing probability, time or profit', () => {
  const p = plan(); p.targets = [row(5, { probability: NaN, expectedDays: null, contractPrice: NaN })];
  const region = show(p);
  const result = within(within(region.getByRole('table')).getAllByRole('row')[1]);
  expect(result.getAllByText('Unavailable')).toHaveLength(3);
});
it('reports an empty target response without fixed two-row placeholders', () => {
  const p = plan(); p.targets = [];
  expect(show(p).getByText('No target estimates returned.')).toBeVisible();
  expect(screen.queryByText('2:1 target — not yet computed —')).not.toBeInTheDocument();
});
