import { PARAM_DEFAULTS_PER_HORIZON } from '@/lib/executionParamDefaults';

// CONTRACT-LIQUIDITY-DTE fix 1: min_volume is an OPTIONAL hard floor, 0 = off
// (PRD FR-25 makes volume a soft rule, scored by preferred_volume_min). Every
// horizon row must carry the same 0 that backend/config/contract_rules.yaml's
// hard_reject.min_volume ships, or "Reset to defaults" would send a hidden
// floor of 50 back to the scan. The two liquidity hard gates that stay
// (min_open_interest, max_bid_ask_spread_pct) are pinned unchanged.
describe('PARAM_DEFAULTS_PER_HORIZON min_volume default is 0 (off)', () => {
  for (const horizon of ['Intraday', 'Swing', 'Position', 'Quarterly', 'SemiAnnual', 'Annual', 'Custom'] as const) {
    it(`${horizon} row: min_volume 0, OI and spread hard gates unchanged`, () => {
      const row = PARAM_DEFAULTS_PER_HORIZON[horizon];
      expect(row.min_volume).toBe(0);
      expect(row.min_open_interest).toBe(200);
      expect(row.max_bid_ask_spread_pct).toBe(0.20);
    });
  }
});
