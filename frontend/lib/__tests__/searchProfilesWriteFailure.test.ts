import { useSearchProfilesStore, CURRENT_SEARCH_PROFILES_SCHEMA_VERSION } from '../searchProfilesStore';
import type { SearchProfile, SearchProfileSnapshot } from '@/types/searchProfile';
import { DEFAULT_CONFIDENCE_GATE } from '@/lib/settingsStore';
import { SCAN_PARAM_DEFAULTS } from '@/lib/scanParamsStore';

const STORAGE_KEY = 'bamendjou:search-profiles';

const baselineProfile: SearchProfile = {
  id: 'baseline-profile-1',
  name: 'Baseline Profile',
  mode: 'stocks',
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
  scanOverrides: {},
  strategy: 'pullback_ema',
  strategyParams: {
    ...SCAN_PARAM_DEFAULTS,
    pullbackTolerancePct: 0.08,
  },
  scanSettings: {
    confidenceGate: { ...DEFAULT_CONFIDENCE_GATE },
  },
};

const newSnapshot: SearchProfileSnapshot = {
  mode: 'stocks',
  universe: {
    pick: 'NDX100',
    customRaw: '',
    minPriceRaw: '20',
    maxPriceRaw: '200',
    minCapRaw: '',
    maxCapRaw: '',
    capUnit: 'B',
  },
  direction: 'Bearish',
  horizonPreset: 'Intraday',
  holdMin: 1,
  holdMax: 5,
  scanOverrides: {},
  strategy: 'breakout_base',
  strategyParams: {
    ...SCAN_PARAM_DEFAULTS,
    breakoutVolumeMult: 2.0,
  },
  scanSettings: {
    confidenceGate: { ...DEFAULT_CONFIDENCE_GATE },
  },
};

describe('searchProfilesStore — Atomic CRUD & Write Failure Rollback (Finding S1 / Issue #398)', () => {
  const origSetItem = Storage.prototype.setItem;

  beforeEach(() => {
    Storage.prototype.setItem = origSetItem;
    localStorage.clear();
    const envelope = {
      version: CURRENT_SEARCH_PROFILES_SCHEMA_VERSION,
      state: {
        profiles: [baselineProfile],
        legacyTargetPctDropped: false,
      },
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(envelope));
    useSearchProfilesStore.setState({
      profiles: [baselineProfile],
      legacyTargetPctDropped: false,
      staleScheduleEntryIds: [],
    });
  });

  afterEach(() => {
    Storage.prototype.setItem = origSetItem;
  });

  describe('QuotaExceededError & SecurityError during saveProfile', () => {
    it.each(['QuotaExceededError', 'SecurityError'])(
      'prevents in-memory addition and preserves exact disk bytes on %s',
      (errName) => {
        const diskBefore = localStorage.getItem(STORAGE_KEY);
        expect(diskBefore).not.toBeNull();
        const storeBefore = useSearchProfilesStore.getState().profiles;
        expect(storeBefore).toHaveLength(1);

        Storage.prototype.setItem = function (k: string, v: string) {
          if (k === STORAGE_KEY) {
            throw new DOMException(`Injected ${errName}`, errName);
          }
          return origSetItem.call(this, k, v);
        };

        expect(() => {
          useSearchProfilesStore.getState().saveProfile('Failed New Profile', newSnapshot);
        }).toThrow();

        // 1. In-memory profiles untouched
        const storeAfter = useSearchProfilesStore.getState().profiles;
        expect(storeAfter).toHaveLength(1);
        expect(storeAfter[0].id).toBe('baseline-profile-1');
        expect(storeAfter[0].name).toBe('Baseline Profile');

        // 2. Exact disk bytes untouched
        const diskAfter = localStorage.getItem(STORAGE_KEY);
        expect(diskAfter).toBe(diskBefore);
      },
    );
  });

  describe('QuotaExceededError & SecurityError during updateProfile', () => {
    it.each(['QuotaExceededError', 'SecurityError'])(
      'prevents in-memory mutation and preserves exact disk bytes on %s',
      (errName) => {
        const diskBefore = localStorage.getItem(STORAGE_KEY);
        const storeBefore = useSearchProfilesStore.getState().profiles;
        expect(storeBefore[0].direction).toBe('Bullish');

        Storage.prototype.setItem = function (k: string, v: string) {
          if (k === STORAGE_KEY) {
            throw new DOMException(`Injected ${errName}`, errName);
          }
          return origSetItem.call(this, k, v);
        };

        expect(() => {
          useSearchProfilesStore.getState().updateProfile(baselineProfile.id, {
            ...newSnapshot,
            direction: 'Bearish',
          });
        }).toThrow();

        // In-memory profile must NOT have mutated to Bearish
        const storeAfter = useSearchProfilesStore.getState().profiles;
        expect(storeAfter).toHaveLength(1);
        expect(storeAfter[0].direction).toBe('Bullish');

        // Disk bytes must be identical
        const diskAfter = localStorage.getItem(STORAGE_KEY);
        expect(diskAfter).toBe(diskBefore);
      },
    );
  });

  describe('QuotaExceededError & SecurityError during renameProfile', () => {
    it.each(['QuotaExceededError', 'SecurityError'])(
      'prevents in-memory rename and preserves exact disk bytes on %s',
      (errName) => {
        const diskBefore = localStorage.getItem(STORAGE_KEY);

        Storage.prototype.setItem = function (k: string, v: string) {
          if (k === STORAGE_KEY) {
            throw new DOMException(`Injected ${errName}`, errName);
          }
          return origSetItem.call(this, k, v);
        };

        expect(() => {
          useSearchProfilesStore.getState().renameProfile(baselineProfile.id, 'Renamed Name');
        }).toThrow();

        const storeAfter = useSearchProfilesStore.getState().profiles;
        expect(storeAfter).toHaveLength(1);
        expect(storeAfter[0].name).toBe('Baseline Profile');

        const diskAfter = localStorage.getItem(STORAGE_KEY);
        expect(diskAfter).toBe(diskBefore);
      },
    );
  });

  describe('QuotaExceededError & SecurityError during deleteProfile', () => {
    it.each(['QuotaExceededError', 'SecurityError'])(
      'prevents in-memory removal and preserves exact disk bytes on %s',
      (errName) => {
        const diskBefore = localStorage.getItem(STORAGE_KEY);

        Storage.prototype.setItem = function (k: string, v: string) {
          if (k === STORAGE_KEY) {
            throw new DOMException(`Injected ${errName}`, errName);
          }
          return origSetItem.call(this, k, v);
        };

        expect(() => {
          useSearchProfilesStore.getState().deleteProfile(baselineProfile.id);
        }).toThrow();

        const storeAfter = useSearchProfilesStore.getState().profiles;
        expect(storeAfter).toHaveLength(1);
        expect(storeAfter[0].id).toBe(baselineProfile.id);

        const diskAfter = localStorage.getItem(STORAGE_KEY);
        expect(diskAfter).toBe(diskBefore);
      },
    );
  });

  describe('Future-version write barrier write refusal', () => {
    it('refuses saveProfile, updateProfile, renameProfile, and deleteProfile when disk has newer version', () => {
      const futureEnvelope = {
        version: 9999,
        state: {
          profiles: [baselineProfile],
          legacyTargetPctDropped: false,
          _futureSentinel: 'preserve-me-byte-for-byte',
        },
      };
      const futureRaw = JSON.stringify(futureEnvelope);
      localStorage.setItem(STORAGE_KEY, futureRaw);

      // 1. saveProfile
      expect(() => {
        useSearchProfilesStore.getState().saveProfile('Blocked Profile', newSnapshot);
      }).toThrow(/Write barrier: refusing write to newer schema version 9999/);
      expect(localStorage.getItem(STORAGE_KEY)).toBe(futureRaw);
      expect(useSearchProfilesStore.getState().profiles).toHaveLength(1);

      // 2. updateProfile
      expect(() => {
        useSearchProfilesStore.getState().updateProfile(baselineProfile.id, newSnapshot);
      }).toThrow(/Write barrier: refusing write to newer schema version 9999/);
      expect(localStorage.getItem(STORAGE_KEY)).toBe(futureRaw);
      expect(useSearchProfilesStore.getState().profiles[0].direction).toBe('Bullish');

      // 3. renameProfile
      expect(() => {
        useSearchProfilesStore.getState().renameProfile(baselineProfile.id, 'New Name');
      }).toThrow(/Write barrier: refusing write to newer schema version 9999/);
      expect(localStorage.getItem(STORAGE_KEY)).toBe(futureRaw);
      expect(useSearchProfilesStore.getState().profiles[0].name).toBe('Baseline Profile');

      // 4. deleteProfile
      expect(() => {
        useSearchProfilesStore.getState().deleteProfile(baselineProfile.id);
      }).toThrow(/Write barrier: refusing write to newer schema version 9999/);
      expect(localStorage.getItem(STORAGE_KEY)).toBe(futureRaw);
      expect(useSearchProfilesStore.getState().profiles).toHaveLength(1);
    });
  });
});
