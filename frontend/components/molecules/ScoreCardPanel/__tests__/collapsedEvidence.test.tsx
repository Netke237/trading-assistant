import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { ScoreCardPanel } from '..';
import { CollapsibleSection } from '@/components/molecules/CollapsibleSection';
import type { StockExplanation, TradeCardData } from '@/types/domain';

const explanation: StockExplanation = {
  version: 1, symbol: 'TEST', direction: 'Bullish', horizon: 'Swing',
  scoring_mode: 'options', iv_basis: 'rank', evaluated_at: '2026-10-04T00:00:00Z',
  score: 54, status: 'CAUTION', raw_status: 'PASS', unrounded_score: 54.5,
  rounding: 'python_round_ties_to_even', pass_threshold: 54, caution_threshold: 31,
  weights: { trend: 0.123 }, caps: [], gate_config: { confidence: { pass_min: 60 } },
  components: { trend: { name: 'trend', wire_name: 'trend', raw_score: 100,
    status: 'PASS', measured: false, weight: 0.123, contribution: 12.3,
    detail: { observation: 'Missing benchmark' }, config: { custom_threshold: 17 } } },
};
const card = { symbol: 'TEST', direction: 'Bullish', stockScore: 54,
  stockConfidence: 'CAUTION', contractScore: 0, contractConfidence: 'REJECT',
  stockExplanation: explanation } as TradeCardData;
const props = { title: 'Stock Scorecard', bars: [{ label: 'Trend', value: 71 }],
  total: 54, confidence: 'CAUTION' as const };

beforeEach(() => localStorage.clear());

it('hides mounted evidence by default and expands without hiding bars or changing captured fields', () => {
  const before = JSON.stringify(card);
  render(<ScoreCardPanel {...props} qualification={{ card, kind: 'stock' }} />);
  const toggle = screen.getByRole('button', { name: /Captured stock scoring evidence/ });
  const evidence = screen.getByText(/Captured TEST evidence/);
  expect(toggle).toHaveAttribute('aria-expanded', 'false');
  expect(evidence).toBeInTheDocument();
  expect(evidence).not.toBeVisible();
  expect(screen.getByRole('progressbar')).toBeVisible();
  expect(screen.getByText('54/100')).toBeVisible();
  toggle.focus();
  expect(toggle).toHaveFocus();
  expect(toggle).toHaveAttribute('type', 'button');
  fireEvent.click(toggle);
  expect(toggle).toHaveAttribute('aria-expanded', 'true');
  expect(evidence).toBeVisible();
  expect(screen.getByText('Authoritative score: 54 · Unrounded: 54.5')).toBeVisible();
  expect(screen.getByText('Score: 100 · Weight (fraction): 0.123 · Contribution (points): 12.3')).toBeVisible();
  expect(screen.getByText('Missing benchmark')).toBeVisible();
  expect(JSON.stringify(card)).toBe(before);
});

it('preserves the real evidence disclosure state and DOM identity across collapse and outer score toggles', () => {
  render(<CollapsibleSection title="Stock & contract scores" storageKey="test:scores" keepMounted>
    <ScoreCardPanel {...props} qualification={{ card, kind: 'stock' }} />
  </CollapsibleSection>);
  const toggle = screen.getByRole('button', { name: /Captured stock scoring evidence/ });
  fireEvent.click(toggle);
  const summary = screen.getByText('Effective gate configuration and weights');
  const details = summary.closest('details')!;
  fireEvent.click(summary);
  expect(details.open).toBe(true);
  fireEvent.click(toggle);
  expect(details).not.toBeVisible();
  expect(details.open).toBe(true);
  expect(screen.getByRole('progressbar')).toBeVisible();
  fireEvent.click(toggle);
  expect(screen.getByText('Effective gate configuration and weights').closest('details')).toBe(details);
  expect(details).toBeVisible();
  const outer = screen.getByRole('button', { name: /Stock & contract scores/ });
  fireEvent.click(outer);
  expect(details).not.toBeVisible();
  fireEvent.click(outer);
  expect(toggle).toHaveAttribute('aria-expanded', 'true');
  expect(details.open).toBe(true);
  expect(details).toBeVisible();
});

it('persists stock and contract evidence independently of the outer score group', () => {
  render(<>
    <ScoreCardPanel {...props} qualification={{ card, kind: 'stock' }} />
    <ScoreCardPanel {...props} title="Contract Scorecard" total={0} confidence="REJECT" qualification={{ card, kind: 'contract' }} />
  </>);
  fireEvent.click(screen.getByRole('button', { name: /Captured stock scoring evidence/ }));
  expect(screen.getByRole('button', { name: /Captured contract scoring evidence/ })).toHaveAttribute('aria-expanded', 'false');
  expect(localStorage.getItem('bamendjou:tradecard:stock:scoring-evidence:collapsed')).toBe('0');
  expect(localStorage.getItem('bamendjou:tradecard:contract:scoring-evidence:collapsed')).toBe('1');
});

it.each([{ total: 55 }, { confidence: 'PASS' as const }])('retains the panel mismatch guard for %j', mismatch => {
  render(<ScoreCardPanel {...props} {...mismatch} qualification={{ card, kind: 'stock' }} />);
  expect(screen.getByText('Evidence does not match displayed score')).toBeVisible();
  expect(screen.queryByRole('button', { name: /scoring evidence/ })).not.toBeInTheDocument();
  expect(screen.queryByText(/Captured TEST evidence/)).not.toBeInTheDocument();
});
