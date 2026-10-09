// STOCKS-HORIZON-T1 shared definition "Params horizon": the examples are
// pinned in both suites (backend tests/test_horizon_profiles.py).
import { tunedParamsHorizon, TUNED_HORIZONS } from '@/lib/horizonPresets';

describe('tunedParamsHorizon', () => {
  it.each(TUNED_HORIZONS.map((h) => [h]))('a tuned preset (%s) is itself', (h) => {
    expect(tunedParamsHorizon(h, 999)).toBe(h);
  });

  it('Intraday has no params horizon', () => {
    expect(tunedParamsHorizon('Intraday', 2)).toBeNull();
  });

  it.each([
    [185, 'Annual'],
    [30, 'Swing'],      // |30-15| = |30-45| = 15 -> the shorter horizon
    [3, null],          // scores as Intraday
    [4, null],
    [5, 'Swing'],
    [50, 'Position'],   // |50-45| = 5 < |50-60| = 10
    [100, 'SemiAnnual'],
    [150, 'SemiAnnual'], // |150-105| = 45 < |150-200| = 50
  ])('Custom with holdMax %i -> %s', (holdMax, expected) => {
    expect(tunedParamsHorizon('Custom', holdMax)).toBe(expected);
  });
});
