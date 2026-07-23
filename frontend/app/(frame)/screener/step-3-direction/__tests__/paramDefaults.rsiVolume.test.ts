import { PARAM_DEFAULTS_PER_HORIZON } from '@/lib/executionParamDefaults';

// Regression guard for the rsi_floor/volume_multiplier drift fix (same class of bug
// as paramDefaults.eventDays.test.ts's event_reject_days/event_caution_days fix):
// PARAM_DEFAULTS_PER_HORIZON is a plain hardcoded copy of backend/config/scoring_rules.yaml's
// per-horizon trigger block. Nothing fetches this table from the backend, so it can
// silently drift — it already had, for all three horizons' rsi_floor and for
// Swing/Position's volume_multiplier.
//
// Expected values below are literal copies of scoring_rules.yaml's
// horizons.<horizon>.trigger.{rsi_floor,volume_multiplier} block, deliberately
// hand-copied rather than derived from any other frontend constant — comparing two
// frontend hardcoded copies against each other would pass even if both had drifted
// to the same wrong number together. Keep these three pairs in sync with the YAML
// by hand if it changes.
const EXPECTED_FROM_YAML: Record<'Intraday' | 'Swing' | 'Position', { rsi_floor: number; volume_multiplier: number }> = {
  Intraday: { rsi_floor: 40, volume_multiplier: 1.20 },
  Swing:    { rsi_floor: 38, volume_multiplier: 1.50 },
  Position: { rsi_floor: 37, volume_multiplier: 1.50 },
};

describe('Step 3 Execution Parameters defaults — rsi_floor/volume_multiplier match the backend', () => {
  it.each(['Intraday', 'Swing', 'Position'] as const)(
    '%s: rsi_floor/volume_multiplier match scoring_rules.yaml',
    (horizon) => {
      const defaults = PARAM_DEFAULTS_PER_HORIZON[horizon];
      const expected = EXPECTED_FROM_YAML[horizon];
      expect(defaults.rsi_floor).toBe(expected.rsi_floor);
      expect(defaults.volume_multiplier).toBe(expected.volume_multiplier);
    },
  );

  it('Custom mirrors the Swing trigger tuning (Custom defaults to a 5-15d hold, same as Swing)', () => {
    const custom = PARAM_DEFAULTS_PER_HORIZON.Custom;
    expect(custom.rsi_floor).toBe(EXPECTED_FROM_YAML.Swing.rsi_floor);
    expect(custom.volume_multiplier).toBe(EXPECTED_FROM_YAML.Swing.volume_multiplier);
  });

  it.each(['Quarterly', 'SemiAnnual', 'Annual'] as const)(
    '%s mirrors the Position trigger tuning (all three spread PARAM_DEFAULTS_POSITION)',
    (horizon) => {
      const defaults = PARAM_DEFAULTS_PER_HORIZON[horizon];
      expect(defaults.rsi_floor).toBe(EXPECTED_FROM_YAML.Position.rsi_floor);
      expect(defaults.volume_multiplier).toBe(EXPECTED_FROM_YAML.Position.volume_multiplier);
    },
  );
});
