import React from 'react';
import { render, screen } from '@testing-library/react';
import { SearchProfileBar } from '../index';
import { useSearchProfilesStore } from '@/lib/searchProfilesStore';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore, SCAN_PARAM_DEFAULTS } from '@/lib/scanParamsStore';
import { useUniverseStore } from '@/lib/universeStore';
import { useSettingsStore, DEFAULT_CONFIDENCE_GATE } from '@/lib/settingsStore';
import { captureCurrentSnapshot } from '@/lib/searchProfileSnapshot';
import type { SearchProfile } from '@/types/searchProfile';

const validProfile: SearchProfile = {
  id: 'valid-profile-1',
  name: 'Valid Profile',
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

const STORAGE_KEY = 'bamendjou:search-profiles';

describe('SearchProfileBar — Malformed profile handling & future-version write barrier (#381)', () => {
  beforeEach(() => {
    localStorage.clear();
    useScanStore.setState({
      screenerMode: 'stocks',
      scanState: 'IDLE',
      context: {
        universe: 'SP500',
        direction: 'Bullish',
        horizon: 'Swing',
        horizonPreset: 'Swing',
        holdMin: 5,
        holdMax: 15,
      },
      scanOverrides: {},
      activeStrategy: 'pullback_ema',
    });
    useScanParamsStore.setState({
      ...SCAN_PARAM_DEFAULTS,
    });
    useUniverseStore.setState({
      pick: 'SP500',
      customRaw: '',
      minPriceRaw: '10',
      maxPriceRaw: '500',
      minCapRaw: '1000',
      maxCapRaw: '',
      capUnit: 'M',
    });
    useSettingsStore.setState({
      confidenceGate: { ...DEFAULT_CONFIDENCE_GATE },
    });
    useSearchProfilesStore.setState({
      profiles: [],
      legacyTargetPctDropped: false,
    });
  });

  describe('Defect C3 — Malformed current-version profile', () => {
    it('rejects malformed profile with null updatedAt on rehydration and preserves valid profile', async () => {
      const malformed = {
        ...validProfile,
        id: 'bad-profile',
        name: 'Bad Profile',
        updatedAt: null,
      };

      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
          version: 5,
          state: {
            profiles: [malformed, validProfile],
          },
        }),
      );

      await useSearchProfilesStore.persist.rehydrate();

      const profiles = useSearchProfilesStore.getState().profiles;
      expect(profiles).toHaveLength(1);
      expect(profiles[0].id).toBe('valid-profile-1');
      expect(profiles[0].name).toBe('Valid Profile');
    });

    it('rejects a store with only a malformed profile leaving zero profiles', async () => {
      const malformed = {
        ...validProfile,
        id: 'bad-profile-only',
        updatedAt: null,
      };

      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
          version: 5,
          state: {
            profiles: [malformed],
          },
        }),
      );

      await useSearchProfilesStore.persist.rehydrate();

      const profiles = useSearchProfilesStore.getState().profiles;
      expect(profiles).toHaveLength(0);
    });

    it('renders SearchProfileBar safely without crash even if an invalid profile exists in memory', () => {
      // Force an invalid profile with null updatedAt into state
      useSearchProfilesStore.setState({
        profiles: [
          { ...validProfile, id: 'bad-null-timestamp', updatedAt: null as unknown as string },
          validProfile,
        ],
      });

      render(<SearchProfileBar />);

      // The bar renders without throwing a TypeError
      expect(screen.getByRole('combobox')).toBeInTheDocument();
      // Dropdown option includes Valid Profile
      expect(screen.getByRole('option', { name: /Valid Profile/i })).toBeInTheDocument();
      // Malformed profile is omitted from options
      expect(screen.queryByRole('option', { name: /bad-null-timestamp/i })).not.toBeInTheDocument();
    });
  });

  describe('Finding S3 — Unknown future-version write barrier', () => {
    it('preserves exact future envelope disk bytes upon rehydration (beforeRaw === afterRaw)', async () => {
      const futurePayload = {
        version: 9999,
        state: {
          profiles: [validProfile],
          futureAuditSentinel: 'must-survive-older-client',
        },
      };

      const beforeRaw = JSON.stringify(futurePayload);
      localStorage.setItem(STORAGE_KEY, beforeRaw);

      // Rehydrate store (simulating Step 3 mount / StoreHydration)
      await useSearchProfilesStore.persist.rehydrate();

      // Check disk bytes: MUST remain 100% byte-for-byte identical!
      const afterRaw = localStorage.getItem(STORAGE_KEY);
      expect(afterRaw).toBe(beforeRaw);

      // Check in-memory state: valid profile is safely loaded for display
      const profiles = useSearchProfilesStore.getState().profiles;
      expect(profiles).toHaveLength(1);
      expect(profiles[0].id).toBe('valid-profile-1');

      // Check UI render: profile displays in the dropdown
      render(<SearchProfileBar />);
      expect(screen.getByRole('option', { name: /Valid Profile/i })).toBeInTheDocument();
    });

    it('refuses subsequent writes when a future-version envelope exists on disk', async () => {
      const futurePayload = {
        version: 9999,
        state: {
          profiles: [validProfile],
          futureAuditSentinel: 'must-survive-older-client',
        },
      };

      const beforeRaw = JSON.stringify(futurePayload);
      localStorage.setItem(STORAGE_KEY, beforeRaw);

      await useSearchProfilesStore.persist.rehydrate();

      // Attempt to save a new profile
      const snapshot = captureCurrentSnapshot('stocks');
      expect(() => {
        useSearchProfilesStore.getState().saveProfile('Brand New Profile', snapshot);
      }).toThrow(/Write barrier: refusing write to newer schema version 9999/);

      // In-memory profiles must not have mutated
      expect(useSearchProfilesStore.getState().profiles).toHaveLength(1);

      // Disk bytes must NOT be downgraded to version 5, and futureAuditSentinel must survive
      const afterRaw = localStorage.getItem(STORAGE_KEY);
      expect(afterRaw).toBe(beforeRaw);
      const parsedDisk = JSON.parse(afterRaw!);
      expect(parsedDisk.version).toBe(9999);
      expect(parsedDisk.state.futureAuditSentinel).toBe('must-survive-older-client');
    });
  });
});
