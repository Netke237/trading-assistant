import React from 'react';
import { render, screen } from '@testing-library/react';
import { ScoreCardPanel } from '..';
import type { TradeCardData } from '@/types/domain';

const card = { symbol: 'TEST', stockScore: 54, stockConfidence: 'CAUTION', contractScore: 0, contractConfidence: 'REJECT' } as TradeCardData;
const props = { title: 'Stock Scorecard', bars: [{ label: 'Trend', value: 71, detailText: 'Original observation', displayValue: '71 points' }], total: 54, confidence: 'CAUTION' as const, confidenceScore: 39, confidenceText: 'TEST: 39% from 17 signals', statusTooltip: 'Original verdict tooltip' };

it('keeps shared defaults and all original bars, observations, numeric confidence and tooltips', () => {
  const { container } = render(<ScoreCardPanel {...props} />);
  expect(screen.getByText('Stock Scorecard')).toBeInTheDocument();
  expect(screen.getByText('Original observation')).toBeInTheDocument();
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '71');
  expect(screen.getByText('71 points')).toBeInTheDocument();
  expect(screen.getByText('54/100')).toBeInTheDocument();
  expect(screen.getByText('39%')).toBeInTheDocument();
  expect(container.textContent).toContain('Original verdict tooltip');
  expect(container.textContent).toContain(props.confidenceText);
  expect(screen.queryByText('Backtested setup confidence')).not.toBeInTheDocument();
  expect(screen.queryByText('Not captured — re-run scan')).not.toBeInTheDocument();
});
it('adds visible interpretation and per-symbol text without changing the original display', () => {
  const { container } = render(<ScoreCardPanel {...props} qualification={{ card, kind: 'stock' }} />);
  expect(screen.getByText('Backtested setup confidence')).toBeVisible();
  expect(screen.getByText(/Based on historical entry signals/)).toBeVisible();
  expect(screen.getAllByText(props.confidenceText).some(node => node.tagName === 'SPAN')).toBe(true);
  expect(screen.getByText('39%')).toBeInTheDocument();
  expect(screen.getByText('54/100')).toBeInTheDocument();
  expect(screen.getByText('Not captured — re-run scan')).toBeInTheDocument();
  expect(container.querySelector('[data-tier="moderate"]')).toBeInTheDocument();
});
it('preserves null-confidence no-history tooltip and visible explanation', () => {
  render(<ScoreCardPanel {...props} confidenceScore={null} confidenceText="No backtest history for TEST" qualification={{ card, kind: 'stock' }} />);
  expect(screen.getByText('—')).toBeInTheDocument();
  expect(screen.getAllByText('No backtest history for TEST').length).toBeGreaterThan(0);
});
it('does not fabricate absent confidence or relabel contract verdict as historical confidence', () => {
  const { rerender } = render(<ScoreCardPanel {...props} confidenceScore={undefined} confidenceText={undefined} qualification={{ card, kind: 'stock' }} />);
  expect(screen.getByText('Backtest confidence not supplied')).toBeInTheDocument();
  rerender(<ScoreCardPanel {...props} total={0} confidence="REJECT" confidenceScore={undefined} qualification={{ card, kind: 'contract' }} />);
  expect(screen.queryByText('Backtested setup confidence')).not.toBeInTheDocument();
  expect(screen.getByText('0/100')).toBeInTheDocument();
});
it('refuses evidence paired with a different panel result while retaining supplied score/status', () => {
  render(<ScoreCardPanel {...props} total={55} qualification={{ card, kind: 'stock' }} />);
  expect(screen.getByText('55/100')).toBeInTheDocument();
  expect(screen.getByText('Evidence does not match displayed score')).toBeInTheDocument();
});
