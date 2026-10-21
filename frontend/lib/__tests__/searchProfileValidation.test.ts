import {
  isValidSearchProfile,
  sanitizeSearchProfiles,
  safeCompareTimestamps,
} from '../searchProfileValidation';
import type { SearchProfile } from '@/types/searchProfile';
import { DEFAULT_ATR_MULT_BY_HORIZON } from '../settingsStore';
import * as fs from 'fs';
import * as path from 'path';

function makeValidProfile(mode: 'options' | 'stocks' = 'options'): SearchProfile {
  const base: SearchProfile = {
    id: 'prof-test-1',
    name: 'Test Profile',
    mode,
    createdAt: '2026-10-21T10:00:00.000Z',
    updatedAt: '2026-10-21T10:30:00.000Z',
    universe: {
      pick: 'SP500',
      customRaw: '',
      minPriceRaw: '10',
      maxPriceRaw: '500',
      minCapRaw: '1000',
      maxCapRaw: '',
      capUnit: 'M',
    },
    direction: 'Bullish',
    horizonPreset: 'Swing',
    holdMin: 5,
    holdMax: 15,
    scanOverrides: {
      min_score: 70,
    },
    scanSettings: {
      confidenceGate: {
        enabled: true,
        cautionBelow: 50,
        rejectBelow: 35,
        atrMult: { ...DEFAULT_ATR_MULT_BY_HORIZON },
      },
    },
  };
  return base;
}

describe('searchProfileValidation', () => {
  describe('isValidSearchProfile', () => {
    it('accepts a valid options profile', () => {
      const p = makeValidProfile('options');
      expect(isValidSearchProfile(p)).toBe(true);
    });

    it('accepts a valid stocks profile without strategy', () => {
      const p = makeValidProfile('stocks');
      expect(isValidSearchProfile(p)).toBe(true);
    });

    it('accepts a valid stocks profile with both strategy and strategyParams', () => {
      const p: SearchProfile = {
        ...makeValidProfile('stocks'),
        strategy: 'pullback_ema',
        strategyParams: {
          btMinTrades: 5,
          btMinWinRate: 0.45,
          eventFilter: 'include',
          stockShortlistMax: 10,
          pullbackTolerancePct: 1.5,
        },
      };
      expect(isValidSearchProfile(p)).toBe(true);
    });

    it('rejects non-object or null inputs', () => {
      expect(isValidSearchProfile(null)).toBe(false);
      expect(isValidSearchProfile(undefined)).toBe(false);
      expect(isValidSearchProfile('profile')).toBe(false);
      expect(isValidSearchProfile(123)).toBe(false);
      expect(isValidSearchProfile([])).toBe(false);
    });

    it('rejects profile with missing or empty id or name', () => {
      const p = makeValidProfile();
      expect(isValidSearchProfile({ ...p, id: '' })).toBe(false);
      expect(isValidSearchProfile({ ...p, id: '   ' })).toBe(false);
      expect(isValidSearchProfile({ ...p, name: '' })).toBe(false);
      expect(isValidSearchProfile({ ...p, name: '   ' })).toBe(false);
      expect(isValidSearchProfile({ ...p, id: null })).toBe(false);
    });

    it('rejects invalid mode', () => {
      const p = makeValidProfile();
      expect(isValidSearchProfile({ ...p, mode: 'crypto' })).toBe(false);
      expect(isValidSearchProfile({ ...p, mode: '' })).toBe(false);
    });

    it('rejects null, invalid, or missing timestamps (Defect C3)', () => {
      const p = makeValidProfile();
      expect(isValidSearchProfile({ ...p, updatedAt: null })).toBe(false);
      expect(isValidSearchProfile({ ...p, updatedAt: '' })).toBe(false);
      expect(isValidSearchProfile({ ...p, updatedAt: 'not-a-date' })).toBe(false);
      expect(isValidSearchProfile({ ...p, createdAt: null })).toBe(false);
      expect(isValidSearchProfile({ ...p, createdAt: '' })).toBe(false);
      expect(isValidSearchProfile({ ...p, createdAt: 'invalid' })).toBe(false);
    });

    it('rejects invalid direction or horizon', () => {
      const p = makeValidProfile();
      expect(isValidSearchProfile({ ...p, direction: 'Neutral' })).toBe(false);
      expect(isValidSearchProfile({ ...p, horizonPreset: '' })).toBe(false);
      expect(isValidSearchProfile({ ...p, holdMin: NaN })).toBe(false);
      expect(isValidSearchProfile({ ...p, holdMax: Infinity })).toBe(false);
    });

    it('rejects universe with non-string price or cap fields (Finding F-5)', () => {
      const p = makeValidProfile();
      expect(isValidSearchProfile({ ...p, universe: { ...p.universe, minPriceRaw: null } })).toBe(false);
      expect(isValidSearchProfile({ ...p, universe: { ...p.universe, maxPriceRaw: 100 } })).toBe(false);
      expect(isValidSearchProfile({ ...p, universe: { ...p.universe, minCapRaw: undefined } })).toBe(false);
      expect(isValidSearchProfile({ ...p, universe: { ...p.universe, maxCapRaw: null } })).toBe(false);
      expect(isValidSearchProfile({ ...p, universe: { ...p.universe, capUnit: 'K' } })).toBe(false);
    });

    it('rejects corrupt confidenceGate or missing atrMult (Finding F-6)', () => {
      const p = makeValidProfile();
      const corruptGate1 = { ...p.scanSettings.confidenceGate, atrMult: undefined };
      expect(isValidSearchProfile({ ...p, scanSettings: { confidenceGate: corruptGate1 } })).toBe(false);

      const corruptGate2 = {
        ...p.scanSettings.confidenceGate,
        atrMult: { intraday: { target: 2.0, stop: 1.5 } }, // missing swing, position
      };
      expect(isValidSearchProfile({ ...p, scanSettings: { confidenceGate: corruptGate2 } })).toBe(false);

      const corruptGate3 = {
        ...p.scanSettings.confidenceGate,
        cautionBelow: 'fifty', // not number
      };
      expect(isValidSearchProfile({ ...p, scanSettings: { confidenceGate: corruptGate3 } })).toBe(false);
    });

    it('rejects stocks profile when strategy and strategyParams are not co-present (Finding F-7)', () => {
      const p = makeValidProfile('stocks');
      // Has strategy but no strategyParams
      expect(isValidSearchProfile({ ...p, strategy: 'pullback_ema' })).toBe(false);
      // Has strategyParams but no strategy
      expect(isValidSearchProfile({ ...p, strategyParams: { pullbackTolerancePct: 1.5 } })).toBe(false);
    });

    it('rejects options profile with stocks strategy fields (Finding F-7)', () => {
      const p = makeValidProfile('options');
      expect(isValidSearchProfile({ ...p, strategy: 'pullback_ema' })).toBe(false);
      expect(isValidSearchProfile({ ...p, strategyParams: {} })).toBe(false);
    });
  });

  describe('sanitizeSearchProfiles', () => {
    it('returns empty array when input is not an array', () => {
      expect(sanitizeSearchProfiles(null)).toEqual([]);
      expect(sanitizeSearchProfiles(undefined)).toEqual([]);
      expect(sanitizeSearchProfiles('test')).toEqual([]);
    });

    it('filters out malformed entries and preserves valid entries', () => {
      const valid1 = makeValidProfile('options');
      const valid2 = { ...makeValidProfile('stocks'), id: 'prof-test-2' };
      const malformed1 = { ...makeValidProfile(), id: 'bad-1', updatedAt: null };
      const malformed2 = { ...makeValidProfile(), id: 'bad-2', mode: 'crypto' };
      const malformed3 = { ...makeValidProfile(), id: 'bad-3', universe: null };

      const result = sanitizeSearchProfiles([malformed1, valid1, malformed2, valid2, malformed3]);
      expect(result).toHaveLength(2);
      expect(result.map((p) => p.id)).toEqual(['prof-test-1', 'prof-test-2']);
    });
  });

  describe('safeCompareTimestamps', () => {
    it('sorts descending by timestamp', () => {
      const t1 = '2026-10-21T10:00:00.000Z';
      const t2 = '2026-10-21T11:00:00.000Z';
      expect(safeCompareTimestamps(t1, t2)).toBeGreaterThan(0);
      expect(safeCompareTimestamps(t2, t1)).toBeLessThan(0);
      expect(safeCompareTimestamps(t1, t1)).toBe(0);
    });

    it('handles null and undefined without throwing', () => {
      const t = '2026-10-21T10:00:00.000Z';
      expect(() => safeCompareTimestamps(null, t)).not.toThrow();
      expect(() => safeCompareTimestamps(t, null)).not.toThrow();
      expect(() => safeCompareTimestamps(undefined, undefined)).not.toThrow();
      expect(safeCompareTimestamps(null, t)).toBeGreaterThan(0);
      expect(safeCompareTimestamps(t, null)).toBeLessThan(0);
    });
  });

  describe('Production Search Profiles compatibility', () => {
    it('validates all production profiles from search-profiles-export.json', () => {
      const exportPath = path.resolve(__dirname, '../../../../docs/search-profiles/search-profiles-export.json');
      if (fs.existsSync(exportPath)) {
        const raw = fs.readFileSync(exportPath, 'utf8');
        const profiles = JSON.parse(raw);
        expect(Array.isArray(profiles)).toBe(true);
        expect(profiles.length).toBeGreaterThan(0);
        for (const p of profiles) {
          expect(isValidSearchProfile(p)).toBe(true);
        }
      }
    });
  });
});
