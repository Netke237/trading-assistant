import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { SearchProfileBar } from '../index';
import { useSearchProfilesStore } from '@/lib/searchProfilesStore';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore, SCAN_PARAM_DEFAULTS } from '@/lib/scanParamsStore';
import { DEFAULT_CONFIDENCE_GATE } from '@/lib/settingsStore';
import type { SearchProfile } from '@/types/searchProfile';

const validProfileA: SearchProfile = {
  id: 'profile-a',
  name: 'Profile A (Valid)',
  mode: 'stocks',
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-01-01T00:00:00Z',
  universe: { pick: 'SP500', customRaw: '', minPriceRaw: '', maxPriceRaw: '', minCapRaw: '', maxCapRaw: '', capUnit: 'B' },
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
  scanSettings: { confidenceGate: { ...DEFAULT_CONFIDENCE_GATE } },
};

const invalidProfileB: SearchProfile = {
  id: 'profile-b',
  name: 'Profile B (Invalid)',
  mode: 'stocks',
  createdAt: '2026-01-02T00:00:00Z',
  updatedAt: '2026-01-02T00:00:00Z',
  universe: { pick: 'NDX100', customRaw: '', minPriceRaw: '', maxPriceRaw: '', minCapRaw: '', maxCapRaw: '', capUnit: 'B' },
  direction: 'Bullish',
  horizonPreset: 'Swing',
  holdMin: 5,
  holdMax: 15,
  scanOverrides: {},
  strategy: 'pullback_ema',
  strategyParams: {
    ...SCAN_PARAM_DEFAULTS,
    pullbackTolerancePct: 0, // Invalid: <= 0!
  },
  scanSettings: { confidenceGate: { ...DEFAULT_CONFIDENCE_GATE } },
};

describe('SearchProfileBar — atomic selection and validation error handling (Plan F1 fix)', () => {
  beforeEach(() => {
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
    });
    useScanParamsStore.getState().resetToDefaults();
    useSearchProfilesStore.setState({
      profiles: [validProfileA, invalidProfileB],
      staleScheduleEntryIds: [],
    });
  });

  it('selecting invalid profile retains previous selection, displays actionable error, and does NOT expose Update for rejected profile', () => {
    render(<SearchProfileBar />);

    const select = screen.getByLabelText('Search profile') as HTMLSelectElement;

    // 1. Select valid profile A
    fireEvent.change(select, { target: { value: 'profile-a' } });
    expect(select.value).toBe('profile-a');
    expect(screen.queryByRole('alert')).toBeNull();

    // 2. Select invalid profile B
    fireEvent.change(select, { target: { value: 'profile-b' } });

    // Selection must NOT commit to B; it remains A (or empty if none was selected)
    expect(select.value).toBe('profile-a');

    // Actionable error is visible
    const alert = screen.getByRole('alert');
    expect(alert).toBeInTheDocument();
    expect(alert.textContent).toContain('Pullback tolerance must be greater than 0%');

    // Update button for Profile B must NOT exist
    expect(screen.queryByText(/Update "Profile B/)).toBeNull();

    // Stored profile B configuration is untouched
    const storedB = useSearchProfilesStore.getState().profiles.find((p) => p.id === 'profile-b');
    expect(storedB?.strategyParams?.pullbackTolerancePct).toBe(0);

    // Active scan params still follow Profile A
    expect(useScanParamsStore.getState().pullbackTolerancePct).toBe(0.08);
  });
});
