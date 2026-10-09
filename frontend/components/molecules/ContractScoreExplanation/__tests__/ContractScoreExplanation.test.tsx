import React from 'react';
import { render, screen, within } from '@testing-library/react';
import { ContractScoreExplanation } from '../index';
import type { OptionContract, ContractExplanation } from '@/types/domain';

const mockBaseContract: OptionContract = {
  id: 'AAPL|185|2026-11-20|C',
  symbol: 'AAPL',
  strike: 185,
  expiry: '2026-11-20',
  right: 'C',
  dte: 45,
  dteTotal: 45,
  price: 2.50,
  delta: 0.45,
  theta: -0.05,
  ivRank: 40,
  spread: 0.10,
  volume: 500,
  score: 72,
  contractConfidence: 'PASS',
  ivPercentile: 50,
};

const mockValidExplanation: ContractExplanation = {
  version: 1,
  contract_id: 'AAPL|185|2026-11-20|C',
  evaluated_at: '2026-10-03',
  outcome: 'aggregate',
  score: 72,
  status: 'PASS',
  unrounded_score: 72.35,
  rounded_score: 72,
  pass_threshold: 65,
  caution_threshold: 45,
  weights: { liquidity: 0.25, spread: 0.25, delta: 0.20, dte: 0.15, iv_rank: 0.15 },
  components: {
    liquidity: {
      name: 'liquidity',
      wire_name: 'liquidity',
      raw_score: 80,
      weight: 0.25,
      contribution: 20.0,
      lost_points: 5.0,
      volume: 500,
      open_interest: 2000,
      preferred_volume_min: 200,
      preferred_oi_min: 1000,
      flags: [],
    },
    spread: {
      name: 'spread',
      wire_name: 'spread',
      raw_score: 90,
      weight: 0.25,
      contribution: 22.5,
      lost_points: 2.5,
      observed: 0.04,
      preferred_max: 0.08,
      flags: [],
    },
    delta: {
      name: 'delta',
      wire_name: 'delta',
      raw_score: 60,
      weight: 0.20,
      contribution: 12.0,
      lost_points: 8.0,
      observed: 0.45,
      preferred_min: 0.30,
      preferred_max: 0.70,
      flags: [],
    },
    dte: {
      name: 'dte',
      wire_name: 'dteFit',
      raw_score: 85,
      weight: 0.15,
      contribution: 12.75,
      lost_points: 2.25,
      observed: 45,
      preferred_min: 21,
      preferred_max: 60,
      flags: [],
    },
    iv_rank: {
      name: 'iv_rank',
      wire_name: 'ivAttractiveness',
      raw_score: 34,
      weight: 0.15,
      contribution: 5.1,
      lost_points: 9.9,
      observed: 65.0,
      basis: 'absolute',
      preferred_max: 55,
      flags: ['iv_rank_elevated'],
    },
  },
  largest_losses: [
    {
      name: 'iv_rank',
      wire_name: 'ivAttractiveness',
      raw_score: 34,
      weight: 0.15,
      contribution: 5.1,
      lost_points: 9.9,
      flags: ['iv_rank_elevated'],
    },
    {
      name: 'delta',
      wire_name: 'delta',
      raw_score: 60,
      weight: 0.20,
      contribution: 12.0,
      lost_points: 8.0,
      flags: [],
    },
  ],
  blockers: [],
  reject_reasons: [],
  soft_flags: ['iv_rank_elevated'],
  soft_fail_count: 1,
  max_soft_fail_count: 3,
};

describe('ContractScoreExplanation component', () => {
  test('renders explanation unavailable for missing or invalid data', () => {
    render(<ContractScoreExplanation id="test-exp" contract={mockBaseContract} />);
    expect(screen.getByText('Explanation unavailable for this result')).toBeInTheDocument();
  });

  test('renders aggregate outcome with 5 components and thresholds', () => {
    const contractWithExp = { ...mockBaseContract, explanation: mockValidExplanation };
    render(<ContractScoreExplanation id="test-exp" contract={contractWithExp} />);

    expect(screen.getByText(/Pass ≥ 65 · Caution ≥ 45/)).toBeInTheDocument();
    expect(screen.getByText('Liquidity')).toBeInTheDocument();
    expect(screen.getByText('Bid-Ask Spread')).toBeInTheDocument();
    expect(screen.getByText('Delta')).toBeInTheDocument();
    expect(screen.getByText('DTE Fit')).toBeInTheDocument();
    expect(screen.getByText('IV Attractiveness')).toBeInTheDocument();

    // Nested OI in liquidity
    expect(screen.getByText(/Open Int \(nested\):/)).toBeInTheDocument();

    // Contextual metrics
    expect(screen.getByText(/Contextual Metrics/)).toBeInTheDocument();
    expect(screen.getByText(/2\.50/)).toBeInTheDocument();
  });

  test('low IV component score preserves the overall PASS and distinct rank/percentile', () => {
    render(<ContractScoreExplanation id="rank-exp" contract={{ ...mockBaseContract, ivPercentile: 53,
      explanation: { ...mockValidExplanation, components: { ...mockValidExplanation.components,
        iv_rank: { ...mockValidExplanation.components.iv_rank, raw_score: 36, observed: 35.2,
          basis: 'rank', contribution: 5.4, lost_points: 9.6, flags: [] },
      } },
    }} />);
    expect(screen.getAllByText('PASS')).toHaveLength(1);
    expect(screen.queryByText('REJECT')).not.toBeInTheDocument();
    expect(screen.queryByText('CAUTION')).not.toBeInTheDocument();
    expect(screen.getByText('36/100')).toBeInTheDocument();
    expect(screen.getByText('35.2 (rank)')).toBeInTheDocument();
    expect(screen.getByText('≤ 55 rank')).toBeInTheDocument();
    expect(screen.getByText('53')).toBeInTheDocument();
    const card = screen.getByText('IV Attractiveness').closest('div')!.parentElement!;
    expect(within(card).getByText('+5.4')).toBeInTheDocument();
    expect(within(card).getByText('(−9.6 lost)')).toBeInTheDocument();
  });

  test('absolute IV keeps its own unit and a rule warning', () => {
    render(<ContractScoreExplanation id="absolute-exp" contract={{ ...mockBaseContract,
      explanation: mockValidExplanation,
    }} />);
    expect(screen.getByText('65.0% IV')).toBeInTheDocument();
    expect(screen.getByText('≤ 55% IV')).toBeInTheDocument();
    expect(screen.getByText('Rule notes: IV above preferred maximum')).toBeInTheDocument();
  });

  test('missing IV shows a neutral score without inventing a rank threshold', () => {
    render(<ContractScoreExplanation id="missing-exp" contract={{ ...mockBaseContract, ivPercentile: null,
      explanation: { ...mockValidExplanation, components: { ...mockValidExplanation.components,
        iv_rank: { ...mockValidExplanation.components.iv_rank, raw_score: 50, observed: null,
          basis: 'none', flags: ['no_iv_rank_data'] },
      } },
    }} />);
    expect(screen.getByText('50/100')).toBeInTheDocument();
    expect(screen.getByText('Neutral 50 applied (no IV data)')).toBeInTheDocument();
    expect(screen.queryByText('Preferred maximum:')).not.toBeInTheDocument();
    expect(screen.queryByText(/pctl/)).not.toBeInTheDocument();
  });

  test('renders blocked banner when contract is hard-rejected', () => {
    const blockedExp: ContractExplanation = {
      ...mockValidExplanation,
      outcome: 'blocked',
      score: 0,
      status: 'REJECT',
      blockers: [
        { code: 'volume_too_low', label: 'Volume too low', metric: 'volume', operator: '<', threshold: 50, observed: 10 },
      ],
      reject_reasons: ['volume_too_low'],
    };
    const contractBlocked = { ...mockBaseContract, score: 0, contractConfidence: 'REJECT' as const, explanation: blockedExp };
    render(<ContractScoreExplanation id="test-exp" contract={contractBlocked} />);

    expect(screen.getByText('Score forced to 0 by blocking rule(s)')).toBeInTheDocument();
    expect(screen.getByText('Volume too low')).toBeInTheDocument();
    expect(screen.getByText('volume:')).toBeInTheDocument();
  });

  test('shows the exact blocker operands rather than a false rounded inequality', () => {
    const observed = (2.15 - 2.05) / ((2.15 + 2.05) / 2);
    render(<ContractScoreExplanation id="blocker-exp" contract={{ ...mockBaseContract,
      explanation: { ...mockValidExplanation, outcome: 'blocked', score: 0, status: 'REJECT',
        unrounded_score: null, rounded_score: null,
        blockers: [{ code: 'spread_too_wide', label: 'Spread too wide', metric: 'spread_pct', observed, threshold: .04761, operator: '>' }],
      },
    }} />);
    expect(screen.getByText('0.04761904761904767 > 0.04761')).toBeInTheDocument();
  });

  test('preserves fractional spread and delta boundaries', () => {
    render(<ContractScoreExplanation id="boundary-exp" contract={{ ...mockBaseContract,
      explanation: { ...mockValidExplanation, components: { ...mockValidExplanation.components,
        spread: { ...mockValidExplanation.components.spread, observed: .056, preferred_max: .0555 },
        delta: { ...mockValidExplanation.components.delta, observed: .45001, preferred_min: .45002, preferred_max: .55003 },
      } },
    }} />);
    expect(screen.getByText('5.6% (≤5.55%)')).toBeInTheDocument();
    expect(screen.getByText('0.45001 (0.45002–0.55003)')).toBeInTheDocument();
  });

  test('rejects another contract identity or unsupported snapshot version', () => {
    render(<ContractScoreExplanation id="foreign" contract={{ ...mockBaseContract,
      explanation: { ...mockValidExplanation, contract_id: 'OTHER|1|2026-11-20|C' },
    }} />);
    expect(screen.getByText('Explanation unavailable for this result')).toBeInTheDocument();
  });

  test('preserves the effective fractional component weight', () => {
    render(<ContractScoreExplanation id="fractional-exp" contract={{
      ...mockBaseContract,
      explanation: { ...mockValidExplanation, weights: {
        ...mockValidExplanation.weights, iv_rank: 0.1525,
      }, components: {
        ...mockValidExplanation.components,
        iv_rank: { ...mockValidExplanation.components.iv_rank, weight: 0.1525 },
      } },
    }} />);
    const ivCard = screen.getByText('IV Attractiveness').closest('div')?.parentElement;
    expect(ivCard).toHaveTextContent('Weight:15.25%');
  });

  test('shows a 200 percent spread without changing its ratio unit', () => {
    render(<ContractScoreExplanation id="spread-exp" contract={{
      ...mockBaseContract,
      explanation: { ...mockValidExplanation, components: {
        ...mockValidExplanation.components,
        spread: { ...mockValidExplanation.components.spread, observed: 2 },
      } },
    }} />);
    expect(screen.getByText(/200\.0%/)).toBeInTheDocument();
  });
});
