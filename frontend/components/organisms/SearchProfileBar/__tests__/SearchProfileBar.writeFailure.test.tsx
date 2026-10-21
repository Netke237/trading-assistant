import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { SearchProfileBar } from '../index';
import { useSearchProfilesStore } from '@/lib/searchProfilesStore';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore, SCAN_PARAM_DEFAULTS } from '@/lib/scanParamsStore';
import { useUniverseStore } from '@/lib/universeStore';
import { useSettingsStore, DEFAULT_CONFIDENCE_GATE } from '@/lib/settingsStore';
import type { SearchProfile } from '@/types/searchProfile';

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

describe('SearchProfileBar — Write Failure UI Alerts & Memory Rollback (Finding S1 / Issue #398)', () => {
  const origSetItem = Storage.prototype.setItem;

  beforeEach(() => {
    Storage.prototype.setItem = origSetItem;
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
      profiles: [baselineProfile],
      legacyTargetPctDropped: false,
      staleScheduleEntryIds: [],
    });
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        version: 5,
        state: {
          profiles: [baselineProfile],
          legacyTargetPctDropped: false,
        },
      }),
    );
  });

  afterEach(() => {
    Storage.prototype.setItem = origSetItem;
  });

  it('renders role="alert" and rolls back memory when Save as new fails with QuotaExceededError', async () => {
    Storage.prototype.setItem = function (k: string, v: string) {
      if (k === STORAGE_KEY) {
        throw new DOMException('QuotaExceededError: localStorage quota exceeded', 'QuotaExceededError');
      }
      return origSetItem.call(this, k, v);
    };

    render(<SearchProfileBar />);

    // Click Save as new...
    fireEvent.click(screen.getByRole('button', { name: 'Save as new…' }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    // Type new name
    fireEvent.change(screen.getByPlaceholderText('Profile name'), {
      target: { value: 'Exceeded Profile' },
    });

    // Click Save
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    // Rejection alert is displayed
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/QuotaExceededError/);

    // Dialog is closed
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    // Dropdown still contains only Baseline Profile
    const options = screen.getAllByRole('option');
    expect(options.map((o) => o.textContent)).toEqual(['— none —', 'Baseline Profile']);

    // In-memory profiles untouched
    expect(useSearchProfilesStore.getState().profiles).toHaveLength(1);
    expect(useSearchProfilesStore.getState().profiles[0].name).toBe('Baseline Profile');
  });

  it('renders role="alert" and preserves previous direction when Update fails with SecurityError', async () => {
    render(<SearchProfileBar />);

    // Select baseline profile
    const select = screen.getByRole('combobox', { name: 'Search profile' });
    fireEvent.change(select, { target: { value: baselineProfile.id } });

    // Mutate scanStore direction to Bearish so profile is dirty
    useScanStore.setState({
      context: {
        ...useScanStore.getState().context!,
        direction: 'Bearish',
      },
    });

    // Wait for Update button
    const updateBtn = await screen.findByRole('button', {
      name: `Update “${baselineProfile.name}”`,
    });
    expect(updateBtn).not.toBeDisabled();

    // Inject SecurityError
    Storage.prototype.setItem = function (k: string, v: string) {
      if (k === STORAGE_KEY) {
        throw new DOMException('SecurityError: storage access denied', 'SecurityError');
      }
      return origSetItem.call(this, k, v);
    };

    fireEvent.click(updateBtn);

    // Rejection alert is displayed
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/SecurityError/);

    // In-memory profile must STILL have direction: 'Bullish'
    const profileInStore = useSearchProfilesStore.getState().profiles.find((p) => p.id === baselineProfile.id);
    expect(profileInStore?.direction).toBe('Bullish');
  });

  it('renders role="alert" and preserves profile name when Rename fails with QuotaExceededError', async () => {
    render(<SearchProfileBar />);

    // Select baseline profile
    const select = screen.getByRole('combobox', { name: 'Search profile' });
    fireEvent.change(select, { target: { value: baselineProfile.id } });

    // Click Rename
    fireEvent.click(screen.getByRole('button', { name: 'Rename' }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    // Enter new name
    fireEvent.change(screen.getByPlaceholderText('Profile name'), {
      target: { value: 'Renamed Fails' },
    });

    // Inject storage failure
    Storage.prototype.setItem = function (k: string, v: string) {
      if (k === STORAGE_KEY) {
        throw new DOMException('QuotaExceededError: disk full', 'QuotaExceededError');
      }
      return origSetItem.call(this, k, v);
    };

    // Click Save inside RenameProfileDialog
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    // Rejection alert is rendered
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/QuotaExceededError/);

    // In-memory name not changed
    expect(useSearchProfilesStore.getState().profiles[0].name).toBe('Baseline Profile');
  });

  it('renders role="alert" and preserves profile when Delete fails with SecurityError', async () => {
    render(<SearchProfileBar />);

    // Select baseline profile
    const select = screen.getByRole('combobox', { name: 'Search profile' });
    fireEvent.change(select, { target: { value: baselineProfile.id } });

    // Click Delete
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    // Inject storage failure
    Storage.prototype.setItem = function (k: string, v: string) {
      if (k === STORAGE_KEY) {
        throw new DOMException('SecurityError: access restricted', 'SecurityError');
      }
      return origSetItem.call(this, k, v);
    };

    // Click Confirm
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));

    // Rejection alert is rendered
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/SecurityError/);

    // Profile was not deleted from memory
    expect(useSearchProfilesStore.getState().profiles).toHaveLength(1);
    expect(useSearchProfilesStore.getState().profiles[0].id).toBe(baselineProfile.id);

    // Selected ID is still preserved
    expect((select as HTMLSelectElement).value).toBe(baselineProfile.id);
  });
});
