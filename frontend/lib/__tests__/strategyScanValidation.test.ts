import {
  StrategyScanValidationError,
  assertStrategyScanOverrides,
  validateStrategyScanOverrides,
  validatePullbackToleranceDraft,
  validateMaCrossoverLookbackDraft,
  validateBreakoutVolumeMultDraft,
  isSchemaValidStrategyOverride,
} from '@/lib/strategyScanValidation';

describe('strategyScanValidation — backend contract and assertStrategyScanOverrides', () => {
  it('passes when all overrides are null or undefined (follows profile)', () => {
    expect(() =>
      assertStrategyScanOverrides({
        pullbackTolerancePct: null,
        maCrossoverLookback: null,
        breakoutVolumeMult: null,
      }),
    ).not.toThrow();

    expect(() => assertStrategyScanOverrides({})).not.toThrow();
  });

  describe('pullbackTolerancePct (backend contract: 0 < fraction <= 1.0)', () => {
    it('accepts valid fractions (e.g. 0.08, 0.004, 1.0)', () => {
      expect(() => assertStrategyScanOverrides({ pullbackTolerancePct: 0.08 })).not.toThrow();
      expect(() => assertStrategyScanOverrides({ pullbackTolerancePct: 0.004 })).not.toThrow();
      expect(() => assertStrategyScanOverrides({ pullbackTolerancePct: 1.0 })).not.toThrow();
    });

    it('rejects 0.0, negative numbers, > 1.0, and non-finite values', () => {
      expect(() => assertStrategyScanOverrides({ pullbackTolerancePct: 0 })).toThrow(
        StrategyScanValidationError,
      );
      expect(() => assertStrategyScanOverrides({ pullbackTolerancePct: -0.01 })).toThrow(
        StrategyScanValidationError,
      );
      expect(() => assertStrategyScanOverrides({ pullbackTolerancePct: 1.01 })).toThrow(
        StrategyScanValidationError,
      );
      expect(() => assertStrategyScanOverrides({ pullbackTolerancePct: NaN })).toThrow(
        StrategyScanValidationError,
      );
      expect(() => assertStrategyScanOverrides({ pullbackTolerancePct: Infinity })).toThrow(
        StrategyScanValidationError,
      );
    });
  });

  describe('maCrossoverLookback (backend contract: integer >= 1)', () => {
    it('accepts positive integers (e.g. 1, 20, 30, 50)', () => {
      expect(() => assertStrategyScanOverrides({ maCrossoverLookback: 1 })).not.toThrow();
      expect(() => assertStrategyScanOverrides({ maCrossoverLookback: 20 })).not.toThrow();
      expect(() => assertStrategyScanOverrides({ maCrossoverLookback: 30 })).not.toThrow();
      expect(() => assertStrategyScanOverrides({ maCrossoverLookback: 50 })).not.toThrow();
    });

    it('rejects 0, negative integers, fractional values, and non-finite values', () => {
      expect(() => assertStrategyScanOverrides({ maCrossoverLookback: 0 })).toThrow(
        StrategyScanValidationError,
      );
      expect(() => assertStrategyScanOverrides({ maCrossoverLookback: -1 })).toThrow(
        StrategyScanValidationError,
      );
      expect(() => assertStrategyScanOverrides({ maCrossoverLookback: 1.5 })).toThrow(
        StrategyScanValidationError,
      );
      expect(() => assertStrategyScanOverrides({ maCrossoverLookback: NaN })).toThrow(
        StrategyScanValidationError,
      );
    });
  });

  describe('breakoutVolumeMult (backend contract: float > 1.0)', () => {
    it('accepts floats strictly greater than 1.0 (e.g. 1.01, 1.5, 2.0, 3.0, 4.0)', () => {
      expect(() => assertStrategyScanOverrides({ breakoutVolumeMult: 1.01 })).not.toThrow();
      expect(() => assertStrategyScanOverrides({ breakoutVolumeMult: 1.5 })).not.toThrow();
      expect(() => assertStrategyScanOverrides({ breakoutVolumeMult: 2.0 })).not.toThrow();
      expect(() => assertStrategyScanOverrides({ breakoutVolumeMult: 3.0 })).not.toThrow();
      expect(() => assertStrategyScanOverrides({ breakoutVolumeMult: 4.0 })).not.toThrow();
    });

    it('rejects exactly 1.0 (strict lower bound > 1.0), < 1.0, and non-finite values', () => {
      expect(() => assertStrategyScanOverrides({ breakoutVolumeMult: 1.0 })).toThrow(
        StrategyScanValidationError,
      );
      expect(() => assertStrategyScanOverrides({ breakoutVolumeMult: 0.9 })).toThrow(
        StrategyScanValidationError,
      );
      expect(() => assertStrategyScanOverrides({ breakoutVolumeMult: 0 })).toThrow(
        StrategyScanValidationError,
      );
      expect(() => assertStrategyScanOverrides({ breakoutVolumeMult: -1.0 })).toThrow(
        StrategyScanValidationError,
      );
      expect(() => assertStrategyScanOverrides({ breakoutVolumeMult: NaN })).toThrow(
        StrategyScanValidationError,
      );
    });
  });

  describe('validateStrategyScanOverrides', () => {
    it('returns error map without throwing', () => {
      const res = validateStrategyScanOverrides({
        pullbackTolerancePct: 0,
        maCrossoverLookback: 0,
        breakoutVolumeMult: 1.0,
      });
      expect(res.valid).toBe(false);
      expect(res.errors.pullbackTolerancePct).toBeDefined();
      expect(res.errors.maCrossoverLookback).toBeDefined();
      expect(res.errors.breakoutVolumeMult).toBeDefined();
    });

    it('returns valid true when all values are valid or null', () => {
      const res = validateStrategyScanOverrides({
        pullbackTolerancePct: 0.05,
        maCrossoverLookback: 10,
        breakoutVolumeMult: 1.5,
      });
      expect(res.valid).toBe(true);
      expect(res.errors).toEqual({});
    });
  });

  describe('isSchemaValidStrategyOverride helper', () => {
    it('identifies schema-valid values accurately', () => {
      expect(isSchemaValidStrategyOverride('pullbackTolerancePct', 0.05)).toBe(true);
      expect(isSchemaValidStrategyOverride('pullbackTolerancePct', 0)).toBe(false);
      expect(isSchemaValidStrategyOverride('pullbackTolerancePct', null)).toBe(true);

      expect(isSchemaValidStrategyOverride('maCrossoverLookback', 10)).toBe(true);
      expect(isSchemaValidStrategyOverride('maCrossoverLookback', 0)).toBe(false);

      expect(isSchemaValidStrategyOverride('breakoutVolumeMult', 4.0)).toBe(true);
      expect(isSchemaValidStrategyOverride('breakoutVolumeMult', 1.0)).toBe(false);
    });
  });
});

describe('strategyScanValidation — Settings UI draft validation', () => {
  describe('validatePullbackToleranceDraft (editing bounds: 0.5% – 15%)', () => {
    it('converts empty string to null (follow profile) without error', () => {
      expect(validatePullbackToleranceDraft('')).toEqual({ valid: true, value: null, error: null });
      expect(validatePullbackToleranceDraft('   ')).toEqual({ valid: true, value: null, error: null });
    });

    it('parses valid inputs within 0.5% to 15% and returns exact fraction', () => {
      expect(validatePullbackToleranceDraft('0.5')).toEqual({ valid: true, value: 0.005, error: null });
      expect(validatePullbackToleranceDraft('8')).toEqual({ valid: true, value: 0.08, error: null });
      expect(validatePullbackToleranceDraft('15')).toEqual({ valid: true, value: 0.15, error: null });
      expect(validatePullbackToleranceDraft('8.25')).toEqual({ valid: true, value: 0.0825, error: null });
    });

    it('rejects values below 0.5% or above 15%', () => {
      const resZero = validatePullbackToleranceDraft('0');
      expect(resZero.valid).toBe(false);
      expect(resZero.error).toContain('between 0.5% and 15%');

      const resHigh = validatePullbackToleranceDraft('15.1');
      expect(resHigh.valid).toBe(false);
      expect(resHigh.error).toContain('between 0.5% and 15%');
    });

    it('rejects non-numeric inputs', () => {
      const res = validatePullbackToleranceDraft('abc');
      expect(res.valid).toBe(false);
      expect(res.error).toBeDefined();
    });
  });

  describe('validateMaCrossoverLookbackDraft (editing bounds: 1 – 30 integer bars)', () => {
    it('converts empty string to null', () => {
      expect(validateMaCrossoverLookbackDraft('')).toEqual({ valid: true, value: null, error: null });
    });

    it('parses integers 1 to 30', () => {
      expect(validateMaCrossoverLookbackDraft('1')).toEqual({ valid: true, value: 1, error: null });
      expect(validateMaCrossoverLookbackDraft('30')).toEqual({ valid: true, value: 30, error: null });
    });

    it('rejects values < 1 or > 30 or fractional numbers', () => {
      expect(validateMaCrossoverLookbackDraft('0').valid).toBe(false);
      expect(validateMaCrossoverLookbackDraft('31').valid).toBe(false);
      expect(validateMaCrossoverLookbackDraft('5.5').valid).toBe(false);
    });
  });

  describe('validateBreakoutVolumeMultDraft (editing bounds: > 1.0 through 3.0)', () => {
    it('converts empty string to null', () => {
      expect(validateBreakoutVolumeMultDraft('')).toEqual({ valid: true, value: null, error: null });
    });

    it('parses valid floats strictly greater than 1.0 up to 3.0', () => {
      expect(validateBreakoutVolumeMultDraft('1.05')).toEqual({ valid: true, value: 1.05, error: null });
      expect(validateBreakoutVolumeMultDraft('2')).toEqual({ valid: true, value: 2, error: null });
      expect(validateBreakoutVolumeMultDraft('3.0')).toEqual({ valid: true, value: 3.0, error: null });
    });

    it('rejects <= 1.0 or > 3.0', () => {
      expect(validateBreakoutVolumeMultDraft('1.0').valid).toBe(false);
      expect(validateBreakoutVolumeMultDraft('1').valid).toBe(false);
      expect(validateBreakoutVolumeMultDraft('0.9').valid).toBe(false);
      expect(validateBreakoutVolumeMultDraft('3.1').valid).toBe(false);
    });
  });
});
