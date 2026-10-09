import React from 'react';
import { render, screen } from '@testing-library/react';
import { TradeCardQualification } from '..';
import type { TradeCardData, StockExplanation, ContractExplanation } from '@/types/domain';

const card = { symbol: 'TEST', direction: 'Bullish', stockScore: 54, stockConfidence: 'CAUTION', contract: 'TEST|100|2027-01-15|C', contractScore: 0, contractConfidence: 'REJECT' } as TradeCardData;
const stock: StockExplanation = {
  version: 1, symbol: card.symbol, direction: card.direction, horizon: 'Swing', scoring_mode: 'options', iv_basis: 'rank', evaluated_at: '2026-10-04T00:00:00Z', score: 54, status: 'CAUTION', raw_status: 'PASS', unrounded_score: 54.5, rounding: 'python_round_ties_to_even', pass_threshold: 54, caution_threshold: 31, weights: { trend: 0.123 },
  components: { trend: { name: 'trend', wire_name: 'trend', raw_score: 100, status: 'PASS', measured: false, weight: 0.123, contribution: 12.3, detail: { observation: 'Missing benchmark' }, config: { custom_threshold: 17 } } },
  caps: [{ name: 'confidence', status: 'CAUTION', before: 'PASS', after: 'CAUTION', detail: { confidence: null, sample_size: 0, interpretation: 'No historical entry signals' }, config: { pass_min: 60 } }], gate_config: { confidence: { pass_min: 60 } },
};
const contract: ContractExplanation = { version: 1, contract_id: card.contract, evaluated_at: stock.evaluated_at, outcome: 'blocked', score: 0, status: 'REJECT', unrounded_score: null, rounded_score: null, pass_threshold: 67, caution_threshold: 43, weights: {}, components: { iv_rank: { name: 'iv_rank', wire_name: 'ivAttractiveness', raw_score: 50, weight: 0.2, contribution: 10, lost_points: 10, basis: 'absolute', observed: 62, observed_unit: '% IV', preferred_max: 55, flags: [] } }, largest_losses: [], blockers: [{ code: 'dte', label: 'DTE too short', metric: 'dte', observed: 2, threshold: 21, operator: '<' }], reject_reasons: ['DTE too short'], soft_flags: ['Wide spread'], soft_fail_count: 1, max_soft_fail_count: 3, raw_inputs: { iv_rank: null }, hard_bounds: { min_dte: 21 } };

it('uses actual captured thresholds, precision, observations and gate reasons without mutating the card', () => {
  const input = { ...card, stockExplanation: stock };
  const before = JSON.stringify(input);
  render(<TradeCardQualification card={input} kind="stock" />);
  expect(screen.getByText('Composite thresholds: PASS ≥ 54 · CAUTION ≥ 31')).toBeInTheDocument();
  expect(screen.getByText('Authoritative score: 54 · Unrounded: 54.5')).toBeInTheDocument();
  expect(screen.getByText('Score: 100 · Weight (fraction): 0.123 · Contribution (points): 12.3')).toBeInTheDocument();
  expect(screen.getByText('Missing benchmark')).toBeInTheDocument();
  expect(screen.getByText('confidence: PASS → CAUTION · Gate status: CAUTION')).toBeInTheDocument();
  expect(screen.getByText('No historical entry signals')).toBeInTheDocument();
  expect(screen.getByText('sample size')).toBeInTheDocument();
  expect(JSON.stringify(input)).toBe(before);
});
it('keeps blocked contributions diagnostic and shows IV basis, raw missing inputs and reasons', () => {
  render(<TradeCardQualification card={{ ...card, contractExplanation: contract }} kind="contract" />);
  expect(screen.getByText(/Score forced to 0/)).toBeInTheDocument();
  expect(screen.getAllByText('DTE too short')).toHaveLength(2);
  expect(screen.getByText('absolute')).toBeInTheDocument();
  expect(screen.getByText('% IV')).toBeInTheDocument();
  expect(screen.getAllByText('Not supplied').length).toBeGreaterThan(0);
});
it.each(['stock', 'contract'] as const)('marks absent or mismatched %s evidence explicitly', kind => {
  const { rerender } = render(<TradeCardQualification card={card} kind={kind} />);
  expect(screen.getByText('Not captured — re-run scan')).toBeInTheDocument();
  rerender(<TradeCardQualification card={{ ...card, stockExplanation: { ...stock, score: 99 }, contractExplanation: { ...contract, contract_id: 'OTHER' } }} kind={kind} />);
  expect(screen.getByText('Not captured — re-run scan')).toBeInTheDocument();
  expect(screen.queryByText(/Composite thresholds/)).not.toBeInTheDocument();
});
