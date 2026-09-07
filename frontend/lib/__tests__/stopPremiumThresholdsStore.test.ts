import {
  useStopPremiumThresholdsStore,
  getStopPremiumThresholds,
  FALLBACK,
} from '@/lib/stopPremiumThresholdsStore';
import { api } from '@/lib/api';

jest.mock('@/lib/api');

// Deliberately NOT the live YAML's values (0.80 / 0.70 / 0.60 since Q7) — this
// fixture stands in for "whatever the backend served" and has to differ from
// FALLBACK for the resolution-order tests below to mean anything.
const YAML_LIKE = {
  Intraday: { pass_max_fraction: 0.85 },
  Swing:    { pass_max_fraction: 0.80 },
  Position: { pass_max_fraction: 0.70 },
};

beforeEach(() => {
  useStopPremiumThresholdsStore.setState({ thresholds: FALLBACK, override: null, loaded: false });
  jest.clearAllMocks();
});

describe('stopPremiumThresholdsStore', () => {
  it('replaces the fallback with the backend values on a successful fetch', async () => {
    (api.getStopPremiumThresholds as jest.Mock).mockResolvedValue(YAML_LIKE);
    await useStopPremiumThresholdsStore.getState().fetch();
    const s = useStopPremiumThresholdsStore.getState();
    expect(s.thresholds).toEqual(YAML_LIKE);
    expect(s.loaded).toBe(true);
  });

  it('keeps the fallback and still marks loaded when the fetch fails', async () => {
    // A dead config endpoint must not silently disable the gate.
    (api.getStopPremiumThresholds as jest.Mock).mockRejectedValue(new Error('offline'));
    await useStopPremiumThresholdsStore.getState().fetch();
    const s = useStopPremiumThresholdsStore.getState();
    expect(s.thresholds).toEqual(FALLBACK);
    expect(s.loaded).toBe(true);
  });
});

describe('getStopPremiumThresholds resolution order', () => {
  it('per-run override beats the horizon value', () => {
    const override = { pass_max_fraction: 0.5 };
    expect(getStopPremiumThresholds('Position', YAML_LIKE, override)).toBe(override);
  });

  it('horizon value beats the bundled fallback', () => {
    expect(getStopPremiumThresholds('Position', YAML_LIKE, null)).toEqual(YAML_LIKE.Position);
    expect(getStopPremiumThresholds('Intraday', YAML_LIKE, null).pass_max_fraction).toBe(0.85);
  });

  it('an unknown horizon falls toward caution (Swing), not toward the loosest band', () => {
    // Intraday is the most permissive at 0.85; defaulting there on an unknown
    // key would silently under-warn.
    expect(getStopPremiumThresholds('Weekly', YAML_LIKE, null)).toEqual(FALLBACK.Swing);
  });

  it('falls back per-horizon when the fetched map is missing that horizon', () => {
    expect(getStopPremiumThresholds('Position', { Swing: YAML_LIKE.Swing }, null))
      .toEqual(FALLBACK.Position);
  });
});
