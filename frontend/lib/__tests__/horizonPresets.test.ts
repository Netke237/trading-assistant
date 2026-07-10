import {
  HORIZON_PRESETS,
  presetByKey,
  previewDteWindow,
  scoringHorizonForHold,
  migrateLegacyHorizon,
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
