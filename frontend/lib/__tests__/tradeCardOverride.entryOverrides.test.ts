import {
  entryOverridesFrom,
  entryOverridesForPlan,
  ENTRY_OVERRIDE_KEYS,
} from '@/lib/tradeCardOverride';

describe('tradeCardOverride: Entry Quality overrides', () => {
  it('defines the three expected entry override keys', () => {
    expect(ENTRY_OVERRIDE_KEYS).toEqual([
      'entry_spread_tolerance_pct',
      'entry_max_slippage_pct',
      'entry_min_premium',
    ]);
  });

  describe('entryOverridesFrom', () => {
    it('returns empty object when no entry keys are present', () => {
      expect(entryOverridesFrom({})).toEqual({});
      expect(entryOverridesFrom({ other_key: 123, str_key: 'abc' })).toEqual({});
    });

    it('extracts finite numbers for the defined keys', () => {
      const overrides = {
        entry_spread_tolerance_pct: 0.15,
        entry_max_slippage_pct: 0.05,
        entry_min_premium: 2.5,
        unrelated: 42,
      };
      expect(entryOverridesFrom(overrides)).toEqual({
        entry_spread_tolerance_pct: 0.15,
        entry_max_slippage_pct: 0.05,
        entry_min_premium: 2.5,
      });
    });

    it('preserves zero (0 and 0.0) without dropping them', () => {
      const overrides = {
        entry_spread_tolerance_pct: 0,
        entry_max_slippage_pct: 0.0,
        entry_min_premium: 0,
      };
      expect(entryOverridesFrom(overrides)).toEqual({
        entry_spread_tolerance_pct: 0,
        entry_max_slippage_pct: 0,
        entry_min_premium: 0,
      });
    });

    it('ignores non-finite numbers and non-numeric types', () => {
      const overrides = {
        entry_spread_tolerance_pct: NaN,
        entry_max_slippage_pct: Infinity,
        entry_min_premium: '5.0' as unknown as number,
      };
      expect(entryOverridesFrom(overrides)).toEqual({});
    });
  });

  describe('entryOverridesForPlan', () => {
    it('prefers scanResult.entry_overrides when present', () => {
      const scanResult = {
        entry_overrides: {
          entry_spread_tolerance_pct: 0.08,
          entry_max_slippage_pct: 0.02,
          entry_min_premium: 1.5,
        },
      };
      const scanOverrides = {
        entry_spread_tolerance_pct: 0.20,
        entry_max_slippage_pct: 0.10,
        entry_min_premium: 5.0,
      };
      expect(entryOverridesForPlan(scanResult, scanOverrides)).toEqual({
        entry_spread_tolerance_pct: 0.08,
        entry_max_slippage_pct: 0.02,
        entry_min_premium: 1.5,
      });
    });

    it('preserves zero recorded in scanResult.entry_overrides', () => {
      const scanResult = {
        entry_overrides: {
          entry_max_slippage_pct: 0,
        },
      };
      const scanOverrides = {
        entry_max_slippage_pct: 0.05,
      };
      expect(entryOverridesForPlan(scanResult, scanOverrides)).toEqual({
        entry_max_slippage_pct: 0,
      });
    });

    it('falls back to scanOverrides when scanResult has no entry_overrides (null or undefined)', () => {
      const scanOverrides = {
        entry_spread_tolerance_pct: 0.12,
        entry_max_slippage_pct: 0.04,
      };
      expect(entryOverridesForPlan(null, scanOverrides)).toEqual({
        entry_spread_tolerance_pct: 0.12,
        entry_max_slippage_pct: 0.04,
      });
      expect(entryOverridesForPlan(undefined, scanOverrides)).toEqual({
        entry_spread_tolerance_pct: 0.12,
        entry_max_slippage_pct: 0.04,
      });
      expect(entryOverridesForPlan({ entry_overrides: null }, scanOverrides)).toEqual({
        entry_spread_tolerance_pct: 0.12,
        entry_max_slippage_pct: 0.04,
      });
    });

    it('returns empty when scanResult.entry_overrides is empty object and does not fall back to scanOverrides', () => {
      // {} means the scan specifically ran with 0 overrides (effective_entry_overrides returned {})
      const scanResult = { entry_overrides: {} };
      const scanOverrides = { entry_max_slippage_pct: 0.05 };
      expect(entryOverridesForPlan(scanResult, scanOverrides)).toEqual({});
    });
  });
});
