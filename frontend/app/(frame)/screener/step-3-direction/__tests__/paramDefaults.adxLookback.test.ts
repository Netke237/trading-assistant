import { PARAM_DEFAULTS_PER_HORIZON } from '@/lib/executionParamDefaults';

// Regression guard for the additive_adx_pass/swing_high_lookback_bars drift fix
// (same class of bug as paramDefaults.eventDays.test.ts and
// paramDefaults.rsiVolume.test.ts). The Position block carried ADX pass 20 and
// swing-high lookback 15 while scoring_rules.yaml says 25 and 75. The two drifted
// differently: handleHzChange writes `additive_adx_pass` into scanOverrides, so a
// Position-family scan started after picking the horizon scored with ADX 20, not
// 25. `swing_high_lookback_bars` is not written there, so the 15 was mostly a
// display default. Mostly: the panel drops an override whose value equals the
// default, so a user who deliberately typed 15 had it silently replaced by the
// YAML's 75.
//
// Expected values are literal copies of scoring_rules.yaml's
// horizons.<horizon>.{trend.additive.adx_pass, pullback.swing_high_lookback_bars},
// hand-copied on purpose (see paramDefaults.rsiVolume.test.ts for why). Keep them
// in sync with the YAML by hand if it changes.
const EXPECTED_FROM_YAML: Record<'Intraday' | 'Swing' | 'Position', { additive_adx_pass: number; swing_high_lookback_bars: number }> = {
  Intraday: { additive_adx_pass: 20, swing_high_lookback_bars: 20 },
  Swing:    { additive_adx_pass: 25, swing_high_lookback_bars: 40 },
  Position: { additive_adx_pass: 25, swing_high_lookback_bars: 75 },
};

describe('Step 3 Execution Parameters defaults — additive_adx_pass/swing_high_lookback_bars match the backend', () => {
  it.each(['Intraday', 'Swing', 'Position'] as const)(
    '%s: additive_adx_pass/swing_high_lookback_bars match scoring_rules.yaml',
    (horizon) => {
      const defaults = PARAM_DEFAULTS_PER_HORIZON[horizon];
      const expected = EXPECTED_FROM_YAML[horizon];
      expect(defaults.additive_adx_pass).toBe(expected.additive_adx_pass);
      expect(defaults.swing_high_lookback_bars).toBe(expected.swing_high_lookback_bars);
    },
  );

  it.each(['Quarterly', 'SemiAnnual', 'Annual'] as const)(
    '%s scores as Position, so it carries the Position values',
    (horizon) => {
      const defaults = PARAM_DEFAULTS_PER_HORIZON[horizon];
      expect(defaults.additive_adx_pass).toBe(EXPECTED_FROM_YAML.Position.additive_adx_pass);
      expect(defaults.swing_high_lookback_bars).toBe(EXPECTED_FROM_YAML.Position.swing_high_lookback_bars);
    },
  );
});
