import {
  validateExplanation,
  getComponentDisplayName,
  getComponentStatus,
  formatMetricValue,
  formatComparison,
  getBlockingSummary,
  getExplanationSummaryLine,
} from '../contractExplanation';
import type { ContractExplanation, OptionContract } from '@/types/domain';

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
      observed: 500,
      observed_unit: 'contracts',
      flags: [],
      volume: 500,
      open_interest: 2000,
      preferred_volume_min: 200,
      preferred_oi_min: 1000,
    },
    spread: {
      name: 'spread',
      wire_name: 'spread',
      raw_score: 90,
      weight: 0.25,
      contribution: 22.5,
      lost_points: 2.5,
      observed: 0.04,
      observed_unit: '%',
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
      observed_unit: 'days',
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
      observed_unit: '%',
      basis: 'absolute',
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
    {
      name: 'liquidity',
      wire_name: 'liquidity',
      raw_score: 80,
      weight: 0.25,
      contribution: 20.0,
      lost_points: 5.0,
      flags: [],
    },
    {
      name: 'spread',
      wire_name: 'spread',
      raw_score: 90,
      weight: 0.25,
      contribution: 22.5,
      lost_points: 2.5,
      flags: [],
    },
    {
      name: 'dte',
      wire_name: 'dteFit',
      raw_score: 85,
      weight: 0.15,
      contribution: 12.75,
      lost_points: 2.25,
      flags: [],
    },
  ],
  blockers: [],
  reject_reasons: [],
  soft_flags: ['iv_rank_elevated'],
  soft_fail_count: 1,
  max_soft_fail_count: 3,
};

describe('contractExplanation helpers', () => {
  test('validateExplanation returns true for valid object and false for invalid/legacy', () => {
    expect(validateExplanation(mockValidExplanation)).toBe(true);
    expect(validateExplanation(null)).toBe(false);
    expect(validateExplanation({})).toBe(false);
    expect(validateExplanation({ version: '1' })).toBe(false);
  });

  test('rejects future versions, missing weights, wrong identity and nested nonfinite numbers', () => {
    expect(validateExplanation({ ...mockValidExplanation, version: 2 })).toBe(false);
    expect(validateExplanation(mockValidExplanation, 'OTHER')).toBe(false);
    expect(validateExplanation({ ...mockValidExplanation, weights: { liquidity: .25 } })).toBe(false);
    expect(validateExplanation({ ...mockValidExplanation, components: { ...mockValidExplanation.components,
      spread: { ...mockValidExplanation.components.spread, observed: Infinity },
    } })).toBe(false);
    expect(validateExplanation({ ...mockValidExplanation, blockers: [{ code: 'spread', label: 'Spread', metric: 'spread', operator: '>', observed: NaN, threshold: .1 }] })).toBe(false);
  });

  test('getComponentDisplayName returns formatted component names', () => {
    expect(getComponentDisplayName('liquidity')).toBe('Liquidity');
    expect(getComponentDisplayName('spread')).toBe('Bid-Ask Spread');
    expect(getComponentDisplayName('delta')).toBe('Delta');
    expect(getComponentDisplayName('dte')).toBe('DTE Fit');
    expect(getComponentDisplayName('iv_rank')).toBe('IV Attractiveness');
  });

  test('getComponentStatus classifies PASS, CAUTION, REJECT bands', () => {
    expect(getComponentStatus(80)).toBe('PASS');
    expect(getComponentStatus(65)).toBe('PASS');
    expect(getComponentStatus(64)).toBe('CAUTION');
    expect(getComponentStatus(45)).toBe('CAUTION');
    expect(getComponentStatus(44)).toBe('REJECT');
  });

  test('formatMetricValue handles nulls, percentages, units and bases', () => {
    expect(formatMetricValue(null)).toBe('—');
    expect(formatMetricValue(0.045, '%')).toBe('4.5%');
    expect(formatMetricValue(2, '%')).toBe('200.0%');
    expect(formatMetricValue(1, '%')).toBe('100.0%');
    expect(formatMetricValue(0, '%')).toBe('0.0%');
    expect(formatMetricValue(45, 'days')).toBe('45d');
    expect(formatMetricValue(1500, 'contracts')).toBe('1,500');
    expect(formatMetricValue(35, '', 'rank')).toBe('35 (pctl)');
    expect(formatMetricValue(42.5, '', 'absolute')).toBe('42.5% IV');
  });

  test('formatComparison formats operators and values', () => {
    expect(formatComparison('<', 50)).toBe('< 50');
    expect(formatComparison('>=', 200)).toBe('≥ 200');
    expect(formatComparison('<=', 0.20, '%')).toBe('≤ 20.0%');
    expect(formatComparison('<=', 2, '%')).toBe('≤ 200.0%');
  });

  test('getBlockingSummary summarizes blockers for blocked outcomes', () => {
    const blocked: ContractExplanation = {
      ...mockValidExplanation,
      outcome: 'blocked',
      score: 0,
      status: 'REJECT',
      blockers: [
        { code: 'volume_too_low', label: 'Volume too low', metric: 'volume', operator: '<', threshold: 50, observed: 10 },
      ],
      reject_reasons: ['volume_too_low'],
    };

    const summary = getBlockingSummary(blocked);
    expect(summary.isBlocked).toBe(true);
    expect(summary.primaryBlocker).toContain('Volume too low');
    expect(summary.allBlockers).toHaveLength(1);

    const unblockedSummary = getBlockingSummary(mockValidExplanation);
    expect(unblockedSummary.isBlocked).toBe(false);
    expect(unblockedSummary.primaryBlocker).toBeNull();
  });

  test('getExplanationSummaryLine handles blocked, aggregate reject, top loss, and unavailable', () => {
    const mockContract: OptionContract = {
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
      ivPercentile: null,
    };

    // Legacy / unavailable
    expect(getExplanationSummaryLine(mockContract)).toBe('Explanation unavailable for this result');

    // With explanation
    const withExp: OptionContract = {
      ...mockContract,
      explanation: mockValidExplanation,
    };
    expect(getExplanationSummaryLine(withExp)).toContain('Largest loss: IV Attractiveness (−9.9 pts)');

    // Blocked
    const blocked: OptionContract = {
      ...mockContract,
      score: 0,
      contractConfidence: 'REJECT',
      explanation: {
        ...mockValidExplanation,
        outcome: 'blocked',
        score: 0,
        status: 'REJECT',
        blockers: [
          { code: 'volume_too_low', label: 'Volume too low', metric: 'volume', operator: '<', threshold: 50, observed: 10 },
        ],
      },
    };
    expect(getExplanationSummaryLine(blocked)).toContain('Blocked: Volume too low');

    // Aggregate-only REJECT
    const aggregateReject: OptionContract = {
      ...mockContract,
      score: 40,
      contractConfidence: 'REJECT',
      explanation: {
        ...mockValidExplanation,
        outcome: 'aggregate',
        score: 40,
        status: 'REJECT',
        blockers: [],
      },
    };
    expect(getExplanationSummaryLine(aggregateReject)).toContain('below caution threshold');
  });
});
