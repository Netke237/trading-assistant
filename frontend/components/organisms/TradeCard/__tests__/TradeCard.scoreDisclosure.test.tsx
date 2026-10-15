import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { TradeCard } from '..';
import type { TradeCardData, StockExplanation, ContractExplanation } from '@/types/domain';

jest.mock('@/lib/api', () => ({ api: {
  getStructuralStop: jest.fn(), getStockQuote: jest.fn(), getContractQuote: jest.fn(),
  getFirstPassageEstimate: jest.fn(), getExitPlan: jest.fn(),
} }));
jest.mock('@/components/organisms/InlineChartPanel', () => ({ InlineChartPanel: () => null }));

const card: TradeCardData = {
  symbol: 'TEST', company: 'Test Company', price: 185.2, direction: 'Bullish', status: 'CAUTION',
  stockScore: 54, stockConfidence: 'CAUTION', confidence: null,
  confidenceText: 'No historical entry signals for TEST',
  stockBreakdown: { trend: 85, pullback: 78, trigger: 72, event: 90, volatility: 65,
    trendDetail: { method: 'Captured trend observation' },
    pullbackDetail: { retracement_pct: null, fvg_hit: false, fvg_gap: null, reason: 'Captured pullback observation' },
    eventDetail: { event: 'earnings', days_to_event: 21 },
  },
  contract: 'TEST|190|2027-01-15|C', contractScore: 0, contractConfidence: 'REJECT',
  contractBreakdown: { dteFit: 80, delta: 66, ivAttractiveness: 55, liquidity: 75, spread: 60 },
  contractDetails: { strike: 190, expiry: '2027-01-15', right: 'C', mid: 2.5,
    delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 },
  entry: { limit: 2.5, maxFill: 2.63, orderType: 'Limit' },
  exit: { invalidation: 179.64, premiumStop: 1.5, timeStopDays: 10, target: 200.02, targets: [] },
  rrRatio: 2.5, rrModel: 'Heston repriced', finalStatus: 'CAUTION',
  fundamentals: { score: 64, growth_score: 65, quality_score: 40, risk_score: 39,
    quality_label: 'Strong', risk_label: 'High', safety_flags: ['negative_equity'], detail: {} },
};
const stock: StockExplanation = {
  version: 1, symbol: 'TEST', direction: 'Bullish', horizon: 'Swing', scoring_mode: 'options',
  iv_basis: 'rank', evaluated_at: '2026-10-04T00:00:00Z', score: 54, status: 'CAUTION',
  raw_status: 'PASS', unrounded_score: 54.5, rounding: 'python_round_ties_to_even',
  pass_threshold: 54, caution_threshold: 31, weights: { trend: 0.123 },
  components: { trend: { name: 'trend', wire_name: 'trend', raw_score: 100, status: 'PASS',
    measured: false, weight: 0.123, contribution: 12.3,
    detail: { observation: 'Missing benchmark' }, config: { custom_threshold: 17 } } },
  caps: [], gate_config: { confidence: { pass_min: 60 } },
};
const contract: ContractExplanation = {
  version: 1, contract_id: card.contract, evaluated_at: stock.evaluated_at, outcome: 'blocked',
  score: 0, status: 'REJECT', unrounded_score: null, rounded_score: null,
  pass_threshold: 67, caution_threshold: 43, weights: {}, components: {}, largest_losses: [],
  blockers: [{ code: 'dte', label: 'DTE too short', metric: 'dte', observed: 2, threshold: 21, operator: '<' }],
  reject_reasons: ['DTE too short'], soft_flags: ['Wide spread'], soft_fail_count: 1,
  max_soft_fail_count: 3, raw_inputs: { iv_rank: null }, hard_bounds: { min_dte: 21 },
};
const data = { ...card, stockExplanation: stock, contractExplanation: contract };
const scoresKey = 'bamendjou:tradecard-scores-collapsed';
const stockKey = 'bamendjou:tradecard:stock:scoring-evidence:collapsed';
const contractKey = 'bamendjou:tradecard:contract:scoring-evidence:collapsed';

beforeEach(() => localStorage.clear());

it('starts fresh scores folded and reveals both complete panels without replacing captured evidence', () => {
  const before = JSON.stringify(data);
  render(<TradeCard data={data} />);
  const toggle = screen.getByRole('button', { name: /Stock & contract scores/ });
  expect(toggle).toHaveAttribute('aria-expanded', 'false');
  expect(screen.getByText('Stock Scorecard')).not.toBeVisible();
  expect(screen.getByText('Fundamental Health')).toBeVisible();
  expect(screen.getByText('negative equity')).toBeVisible();
  fireEvent.click(toggle);
  const section = within(toggle.closest('section')!);
  const values = [85, 78, 72, 90, 65, 80, 66, 55, 75, 60];
  const labels = ['Trend', 'Pullback', 'Trigger', 'Event', 'Volatility', 'DTE fit', 'Delta', 'IV', 'Liquidity', 'Spread'];
  labels.forEach((label, index) => {
    expect(section.getByRole('progressbar', { name: `${label} score ${values[index]}/100` }))
      .toHaveAttribute('aria-valuenow', String(values[index]));
    expect(section.getByText(`${values[index]}/100`)).toBeVisible();
  });
  for (const text of ['Captured trend observation', 'Captured pullback observation', 'earnings in 21d',
    '54/100', '0/100', 'Backtested setup confidence', 'Unvalidated']) {
    expect(section.getByText(text)).toBeVisible();
  }
  expect(section.getByText(/Based on historical entry signals/)).toBeVisible();
  expect(section.getAllByText('No historical entry signals for TEST').some(node => node.tagName === 'SPAN')).toBe(true);
  const stockToggle = section.getByRole('button', { name: /Captured stock scoring evidence/ });
  const contractToggle = section.getByRole('button', { name: /Captured contract scoring evidence/ });
  expect(stockToggle).toHaveAttribute('aria-expanded', 'false');
  expect(contractToggle).toHaveAttribute('aria-expanded', 'false');
  fireEvent.click(stockToggle);
  fireEvent.click(contractToggle);
  expect(section.getByText('Authoritative score: 54 · Unrounded: 54.5')).toBeVisible();
  expect(section.getByText('Missing benchmark')).toBeVisible();
  expect(section.getByText(/Score forced to 0 by blocking rules/)).toBeVisible();
  expect(section.getAllByText('DTE too short')).toHaveLength(2);
  const details = section.getByText('Effective gate configuration and weights').closest('details')!;
  fireEvent.click(within(details).getByText('Effective gate configuration and weights'));
  expect(details.open).toBe(true);
  fireEvent.click(toggle);
  expect(details).not.toBeVisible();
  fireEvent.click(toggle);
  expect(section.getByText('Effective gate configuration and weights').closest('details')).toBe(details);
  expect(details.open).toBe(true);
  expect(stockToggle).toHaveAttribute('aria-expanded', 'true');
  expect(contractToggle).toHaveAttribute('aria-expanded', 'true');
  expect(JSON.stringify(data)).toBe(before);
});

it.each(['0', '1'])('restores existing outer score preference %s and independent evidence preferences', saved => {
  localStorage.setItem(scoresKey, saved);
  localStorage.setItem(stockKey, '0');
  localStorage.setItem(contractKey, '1');
  const { unmount } = render(<TradeCard data={data} />);
  const toggle = screen.getByRole('button', { name: /Stock & contract scores/ });
  expect(toggle).toHaveAttribute('aria-expanded', saved === '0' ? 'true' : 'false');
  expect(localStorage.getItem(scoresKey)).toBe(saved);
  if (saved === '1') fireEvent.click(toggle);
  expect(screen.getByRole('button', { name: /Captured stock scoring evidence/ })).toHaveAttribute('aria-expanded', 'true');
  expect(screen.getByRole('button', { name: /Captured contract scoring evidence/ })).toHaveAttribute('aria-expanded', 'false');
  fireEvent.click(toggle);
  expect(localStorage.getItem(scoresKey)).toBe('1');
  unmount();
  render(<TradeCard data={data} />);
  expect(screen.getByRole('button', { name: /Stock & contract scores/ })).toHaveAttribute('aria-expanded', 'false');
  expect(localStorage.getItem(stockKey)).toBe('0');
  expect(localStorage.getItem(contractKey)).toBe('1');
});
