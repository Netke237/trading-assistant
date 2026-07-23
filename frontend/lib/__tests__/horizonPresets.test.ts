import {
  HORIZON_PRESETS,
  presetByKey,
  previewDteWindow,
  scoringHorizonForHold,
  resolveParamsHorizon,
  migrateLegacyHorizon,
  sanitizeHoldDays,
} from '../horizonPresets';

describe('HORIZON_PRESETS', () => {
  it('has seven presets', () => {
    expect(HORIZON_PRESETS).toHaveLength(7);
  });

  it('maps every long-dated preset to Position scoring', () => {
    for (const key of ['Position', 'Quarterly', 'SemiAnnual', 'Annual'] as const) {
      expect(presetByKey(key).scoringHorizon).toBe('Position');
    }
  });

  it('keeps the short presets on their own scoring horizons', () => {
    expect(presetByKey('Intraday').scoringHorizon).toBe('Intraday');
    expect(presetByKey('Swing').scoringHorizon).toBe('Swing');
  });
});

describe('previewDteWindow', () => {
  it.each([
    ['Intraday',   0,   2,   1,   4],
    ['Swing',      5,   15,  10,  30],
    ['Position',   15,  45,  30,  90],
    ['Quarterly',  45,  60,  90,  120],
    ['SemiAnnual', 90,  105, 180, 210],
    ['Annual',     165, 200, 330, 400],
  ])('%s: hold %i-%i -> dte %i-%i', (_label, hMin, hMax, dMin, dMax) => {
    expect(previewDteWindow(hMin as number, hMax as number)).toEqual([dMin, dMax]);
  });

  it('doubles a custom range', () => {
    expect(previewDteWindow(60, 185)).toEqual([120, 370]);
  });

  it('clamps a zero minimum up to 1', () => {
    expect(previewDteWindow(0, 0)).toEqual([1, 1]);
  });
});

describe('scoringHorizonForHold', () => {
  it('derives the custom scoring horizon from hold_max', () => {
    expect(scoringHorizonForHold(2)).toBe('Intraday');
    expect(scoringHorizonForHold(4)).toBe('Intraday');
    expect(scoringHorizonForHold(15)).toBe('Swing');
    expect(scoringHorizonForHold(20)).toBe('Swing');
    expect(scoringHorizonForHold(21)).toBe('Position');
    expect(scoringHorizonForHold(185)).toBe('Position');
  });
});

describe('resolveParamsHorizon', () => {
  it('resolves Custom to the scoring horizon derived from holdMax, at the same boundaries as scoringHorizonForHold', () => {
    expect(resolveParamsHorizon('Custom', 2)).toBe('Intraday');
    expect(resolveParamsHorizon('Custom', 4)).toBe('Intraday');
    expect(resolveParamsHorizon('Custom', 5)).toBe('Swing');
    expect(resolveParamsHorizon('Custom', 20)).toBe('Swing');
    expect(resolveParamsHorizon('Custom', 21)).toBe('Position');
    expect(resolveParamsHorizon('Custom', 200)).toBe('Position');
  });

  it('passes every non-Custom key through unchanged, preserving its own defaults-table row', () => {
    for (const key of ['Intraday', 'Swing', 'Position', 'Quarterly', 'SemiAnnual', 'Annual'] as const) {
      expect(resolveParamsHorizon(key, 999)).toBe(key);
    }
  });
});

describe('migrateLegacyHorizon', () => {
  it('parses a legacy custom string, preserving the typed days', () => {
    expect(migrateLegacyHorizon('Custom (60–185d)')).toEqual({
      horizonPreset: 'Custom', holdMin: 60, holdMax: 185,
    });
  });

  it('parses a legacy preset string', () => {
    expect(migrateLegacyHorizon('Swing (5–15d)')).toEqual({
      horizonPreset: 'Swing', holdMin: 5, holdMax: 15,
    });
  });

  it('falls back to Swing on an unknown or missing string', () => {
    expect(migrateLegacyHorizon(undefined)).toEqual({
      horizonPreset: 'Swing', holdMin: 5, holdMax: 15,
    });
  });
});

describe('sanitizeHoldDays', () => {
  it('passes whole-day values through unchanged', () => {
    expect(sanitizeHoldDays(60, 185)).toEqual({ hold_min_days: 60, hold_max_days: 185 });
  });

  it('rounds a decimal value that bypassed the input-level rounding (e.g. a stale persisted store)', () => {
    expect(sanitizeHoldDays(15.5, 45.4)).toEqual({ hold_min_days: 16, hold_max_days: 45 });
  });

  it('clamps a negative value up to 0', () => {
    expect(sanitizeHoldDays(-5, 15)).toEqual({ hold_min_days: 0, hold_max_days: 15 });
  });

  it('clamps an inverted range so max never falls below min', () => {
    expect(sanitizeHoldDays(100, 15)).toEqual({ hold_min_days: 100, hold_max_days: 100 });
  });
});
