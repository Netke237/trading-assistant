import { PARAM_DEFAULTS_PER_HORIZON } from '@/lib/executionParamDefaults';

// backend/config/risk_rules.yaml's reward_risk block is the source of truth:
// bullish_target_pct: 0.08, bearish_target_pct: 0.08,
// bullish_invalidation_pct: 0.03, bearish_invalidation_pct: 0.03.
const EXPECTED_RR_DEFAULTS = {
  rr_bullish_target_pct: 0.08,
  rr_bearish_target_pct: 0.08,
  rr_bullish_invalidation_pct: 0.03,
  rr_bearish_invalidation_pct: 0.03,
};

describe('PARAM_DEFAULTS_PER_HORIZON reward/risk defaults match risk_rules.yaml', () => {
  for (const horizon of ['Intraday', 'Swing', 'Position', 'Custom'] as const) {
    it(`${horizon} row matches the backend default`, () => {
      const row = PARAM_DEFAULTS_PER_HORIZON[horizon];
      expect(row.rr_bullish_target_pct).toBe(EXPECTED_RR_DEFAULTS.rr_bullish_target_pct);
      expect(row.rr_bearish_target_pct).toBe(EXPECTED_RR_DEFAULTS.rr_bearish_target_pct);
      expect(row.rr_bullish_invalidation_pct).toBe(EXPECTED_RR_DEFAULTS.rr_bullish_invalidation_pct);
      expect(row.rr_bearish_invalidation_pct).toBe(EXPECTED_RR_DEFAULTS.rr_bearish_invalidation_pct);
    });
  }
});
