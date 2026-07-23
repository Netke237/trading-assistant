import { PARAM_DEFAULTS_PER_HORIZON } from '@/lib/executionParamDefaults';

// Regression guard for the Step 5 event-gate fix: PARAM_DEFAULTS_PER_HORIZON is a
// plain hardcoded copy of backend/config/scoring_rules.yaml's per-horizon event
// window (it feeds the user-editable Execution Parameters panel, which forwards
// event_reject_days/event_caution_days as real scan overrides — see
// frontend/lib/stockScan.ts's STOCKS_SCORER_KEYS and RunScanButton's forwarding
// into the options /api/scan call). Nothing fetches this table from the backend,
// so it can silently drift the way it already had for Swing (7/21 instead of the
// real 21/45) — this test is the only thing that would now catch that recurring.
//
// Expected values below are literal copies of scoring_rules.yaml's
// horizons.<horizon>.event.{reject_days,caution_days} block, deliberately NOT
// imported from eventThresholdsStore's FALLBACK — comparing two frontend
// hardcoded copies against each other would pass even if both had drifted to
// the same wrong number together (exactly how the original Swing bug slipped
// through). Keep these three pairs in sync with the YAML by hand if it changes.
const EXPECTED_FROM_YAML: Record<'Intraday' | 'Swing' | 'Position', { reject_days: number; caution_days: number }> = {
  Intraday: { reject_days: 1,  caution_days: 3  },
  Swing:    { reject_days: 21, caution_days: 45 },
  Position: { reject_days: 30, caution_days: 60 },
};

describe('Step 3 Execution Parameters defaults — event days match the backend', () => {
  it.each(['Intraday', 'Swing', 'Position'] as const)(
    '%s: event_reject_days/event_caution_days match scoring_rules.yaml',
    (horizon) => {
      const defaults = PARAM_DEFAULTS_PER_HORIZON[horizon];
      const expected = EXPECTED_FROM_YAML[horizon];
      expect(defaults.event_reject_days).toBe(expected.reject_days);
      expect(defaults.event_caution_days).toBe(expected.caution_days);
    },
  );

  it('Custom mirrors the Swing window (Custom defaults to a 5-15d hold, same as Swing)', () => {
    const custom = PARAM_DEFAULTS_PER_HORIZON.Custom;
    expect(custom.event_reject_days).toBe(EXPECTED_FROM_YAML.Swing.reject_days);
    expect(custom.event_caution_days).toBe(EXPECTED_FROM_YAML.Swing.caution_days);
  });
});
