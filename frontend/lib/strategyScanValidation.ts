/**
 * Shared validation for the three Strategy Scan override fields
 * (pullbackTolerancePct, maCrossoverLookback, breakoutVolumeMult).
 *
 * Contract:
 * - Backend/persisted overrides (StockScanRequest):
 *     pullbackTolerancePct: null | finite fraction > 0 and <= 1.0 (e.g. 0.08 = 8%).
 *     maCrossoverLookback:  null | integer bars >= 1.
 *     breakoutVolumeMult:   null | finite float > 1.0 (strict lower bound > 1.0; 1.0 is invalid).
 *     null | undefined means follow the horizon profile.
 * - Settings UI editing bounds:
 *     pullbackTolerancePct: 0.5% – 15%
 *     maCrossoverLookback:  1 – 30 integer bars
 *     breakoutVolumeMult:   > 1.0 through 3.0
 */

export class StrategyScanValidationError extends Error {
  constructor(
    message: string,
    public readonly field?: 'pullbackTolerancePct' | 'maCrossoverLookback' | 'breakoutVolumeMult',
    public readonly value?: unknown,
  ) {
    super(message);
    this.name = 'StrategyScanValidationError';
  }
}

export interface StrategyScanOverrides {
  pullbackTolerancePct?: number | null;
  maCrossoverLookback?: number | null;
  breakoutVolumeMult?: number | null;
}

export function validatePullbackToleranceOverride(val: number | null | undefined): string | null {
  if (val === null || val === undefined) return null;
  if (!Number.isFinite(val)) {
    return 'Pullback tolerance must be a finite number.';
  }
  if (val <= 0 || val > 1.0) {
    return 'Pullback tolerance must be greater than 0% and at most 100% (fraction > 0 and <= 1.0).';
  }
  return null;
}

export function validateMaCrossoverLookbackOverride(val: number | null | undefined): string | null {
  if (val === null || val === undefined) return null;
  if (!Number.isFinite(val) || !Number.isInteger(val)) {
    return 'MA crossover lookback must be an integer.';
  }
  if (val < 1) {
    return 'MA crossover lookback must be at least 1 bar.';
  }
  return null;
}

export function validateBreakoutVolumeMultOverride(val: number | null | undefined): string | null {
  if (val === null || val === undefined) return null;
  if (!Number.isFinite(val)) {
    return 'Breakout volume multiplier must be a finite number.';
  }
  if (val <= 1.0) {
    return 'Breakout volume multiplier must be greater than 1.0×.';
  }
  return null;
}

export function isSchemaValidStrategyOverride(
  field: 'pullbackTolerancePct' | 'maCrossoverLookback' | 'breakoutVolumeMult',
  value: number | null | undefined,
): boolean {
  switch (field) {
    case 'pullbackTolerancePct':
      return validatePullbackToleranceOverride(value) === null;
    case 'maCrossoverLookback':
      return validateMaCrossoverLookbackOverride(value) === null;
    case 'breakoutVolumeMult':
      return validateBreakoutVolumeMultOverride(value) === null;
  }
}

export function validateStrategyScanOverrides(overrides: StrategyScanOverrides): {
  valid: boolean;
  errors: Partial<Record<keyof StrategyScanOverrides, string>>;
} {
  const errors: Partial<Record<keyof StrategyScanOverrides, string>> = {};

  if ('pullbackTolerancePct' in overrides) {
    const err = validatePullbackToleranceOverride(overrides.pullbackTolerancePct);
    if (err) errors.pullbackTolerancePct = err;
  }
  if ('maCrossoverLookback' in overrides) {
    const err = validateMaCrossoverLookbackOverride(overrides.maCrossoverLookback);
    if (err) errors.maCrossoverLookback = err;
  }
  if ('breakoutVolumeMult' in overrides) {
    const err = validateBreakoutVolumeMultOverride(overrides.breakoutVolumeMult);
    if (err) errors.breakoutVolumeMult = err;
  }

  return {
    valid: Object.keys(errors).length === 0,
    errors,
  };
}

export function assertStrategyScanOverrides(overrides: StrategyScanOverrides): void {
  if ('pullbackTolerancePct' in overrides) {
    const err = validatePullbackToleranceOverride(overrides.pullbackTolerancePct);
    if (err) throw new StrategyScanValidationError(err, 'pullbackTolerancePct', overrides.pullbackTolerancePct);
  }
  if ('maCrossoverLookback' in overrides) {
    const err = validateMaCrossoverLookbackOverride(overrides.maCrossoverLookback);
    if (err) throw new StrategyScanValidationError(err, 'maCrossoverLookback', overrides.maCrossoverLookback);
  }
  if ('breakoutVolumeMult' in overrides) {
    const err = validateBreakoutVolumeMultOverride(overrides.breakoutVolumeMult);
    if (err) throw new StrategyScanValidationError(err, 'breakoutVolumeMult', overrides.breakoutVolumeMult);
  }
}

/* ---------------- Settings UI Draft Validation Helpers ---------------- */

export interface DraftValidationResult {
  valid: boolean;
  value: number | null;
  error: string | null;
}

export function validatePullbackToleranceDraft(raw: string): DraftValidationResult {
  const trimmed = raw.trim();
  if (trimmed === '') return { valid: true, value: null, error: null };
  const num = Number(trimmed);
  if (!Number.isFinite(num)) {
    return { valid: false, value: null, error: 'Pullback tolerance must be a valid number.' };
  }
  if (num < 0.5 || num > 15) {
    return { valid: false, value: null, error: 'Pullback tolerance must be between 0.5% and 15%.' };
  }
  return { valid: true, value: num / 100, error: null };
}

export function validateMaCrossoverLookbackDraft(raw: string): DraftValidationResult {
  const trimmed = raw.trim();
  if (trimmed === '') return { valid: true, value: null, error: null };
  const num = Number(trimmed);
  if (!Number.isFinite(num) || !Number.isInteger(num)) {
    return { valid: false, value: null, error: 'MA crossover lookback must be an integer.' };
  }
  if (num < 1 || num > 30) {
    return { valid: false, value: null, error: 'MA crossover lookback must be an integer between 1 and 30 bars.' };
  }
  return { valid: true, value: num, error: null };
}

export function validateBreakoutVolumeMultDraft(raw: string): DraftValidationResult {
  const trimmed = raw.trim();
  if (trimmed === '') return { valid: true, value: null, error: null };
  const num = Number(trimmed);
  if (!Number.isFinite(num)) {
    return { valid: false, value: null, error: 'Breakout volume multiplier must be a valid number.' };
  }
  if (num <= 1.0 || num > 3.0) {
    return { valid: false, value: null, error: 'Breakout volume multiplier must be greater than 1.0× and at most 3.0×.' };
  }
  return { valid: true, value: num, error: null };
}
