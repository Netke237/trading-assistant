import { PARAM_DEFAULTS_PER_HORIZON } from '@/lib/executionParamDefaults';

// options-scan-liquidity-profiles work: preferred_volume_min/preferred_oi_min/
// preferred_spread_pct_max became overridable in contract_validator.py
// (backend/tests/test_overrides.py) — this pins that every horizon's default
// row carries the SAME values backend/config/contract_rules.yaml's soft_rank
// block ships, so "Reset to defaults" is unchanged for a caller that never
// sets these new fields.
const EXPECTED_PREFERRED_LIQUIDITY_DEFAULTS = {
  preferred_volume_min: 200,
  preferred_oi_min: 1000,
  preferred_spread_pct_max: 0.08,
};

describe('PARAM_DEFAULTS_PER_HORIZON preferred-liquidity defaults match contract_rules.yaml', () => {
  for (const horizon of ['Intraday', 'Swing', 'Position', 'Quarterly', 'SemiAnnual', 'Annual', 'Custom'] as const) {
    it(`${horizon} row matches the backend soft_rank default`, () => {
      const row = PARAM_DEFAULTS_PER_HORIZON[horizon];
      expect(row.preferred_volume_min).toBe(EXPECTED_PREFERRED_LIQUIDITY_DEFAULTS.preferred_volume_min);
      expect(row.preferred_oi_min).toBe(EXPECTED_PREFERRED_LIQUIDITY_DEFAULTS.preferred_oi_min);
      expect(row.preferred_spread_pct_max).toBe(EXPECTED_PREFERRED_LIQUIDITY_DEFAULTS.preferred_spread_pct_max);
    });
  }
});
