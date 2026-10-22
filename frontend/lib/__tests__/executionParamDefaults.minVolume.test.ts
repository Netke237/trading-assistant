import { PARAM_DEFAULTS_PER_HORIZON } from '@/lib/executionParamDefaults';

// CONTRACT-LIQUIDITY-DTE (fix 1): the hard `min_volume` floor is optional and
// off (0) by default, matching backend/config/contract_rules.yaml's
// hard_reject.min_volume. Volume is scored softly under Preferred Liquidity
// instead. The other two liquidity hard gates (open interest 200, spread 0.20)
// are unchanged. Step 3 presets reach the scan only when edited, so this pins
// that what Step 3 shows (and what an edit starts from) matches the backend.
const EXPECTED_HORIZON_KEYS = ['Intraday', 'Swing', 'Position', 'Quarterly', 'SemiAnnual', 'Annual', 'Custom'];

const EXPECTED_HARD_LIQUIDITY_DEFAULTS = {
  min_volume: 0,
  min_open_interest: 200,
  max_bid_ask_spread_pct: 0.20,
};

describe('PARAM_DEFAULTS_PER_HORIZON hard liquidity defaults match contract_rules.yaml', () => {
  it('covers exactly the expected horizon keys (a new key cannot be silently skipped)', () => {
    expect(Object.keys(PARAM_DEFAULTS_PER_HORIZON).sort()).toEqual([...EXPECTED_HORIZON_KEYS].sort());
  });

  for (const horizon of Object.keys(PARAM_DEFAULTS_PER_HORIZON) as (keyof typeof PARAM_DEFAULTS_PER_HORIZON)[]) {
    it(`${horizon} row: min_volume is 0 (off); min_open_interest and spread ceiling unchanged`, () => {
      const row = PARAM_DEFAULTS_PER_HORIZON[horizon];
      expect(row.min_volume).toBe(EXPECTED_HARD_LIQUIDITY_DEFAULTS.min_volume);
      expect(row.min_open_interest).toBe(EXPECTED_HARD_LIQUIDITY_DEFAULTS.min_open_interest);
      expect(row.max_bid_ask_spread_pct).toBe(EXPECTED_HARD_LIQUIDITY_DEFAULTS.max_bid_ask_spread_pct);
    });
  }
});
