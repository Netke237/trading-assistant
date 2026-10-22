import { act } from '@testing-library/react';
import {
  useSettingsStore,
  SETTINGS_STORAGE_KEY,
  isSettingsEqual,
  mergeLeafProperties,
  getDefaultPersistedSettings,
  getLastCommittedSettings,
  setLastCommittedSettings,
  syncSettingsFromStorage,
  createSettingsStateStorage,
  DEFAULT_MARKOV,
  DEFAULT_CONFIDENCE_GATE,
  DEFAULT_FUNDAMENTALS_GATE,
  DEFAULT_ATR_MULT_BY_HORIZON,
} from '@/lib/settingsStore';
import { useSettingsSaveStatus } from '@/lib/settingsSaveStatus';

describe('isSettingsEqual', () => {
  it('compares primitives correctly', () => {
    expect(isSettingsEqual(42, 42)).toBe(true);
    expect(isSettingsEqual(42, 43)).toBe(false);
    expect(isSettingsEqual('abc', 'abc')).toBe(true);
    expect(isSettingsEqual('abc', 'def')).toBe(false);
    expect(isSettingsEqual(true, true)).toBe(true);
    expect(isSettingsEqual(true, false)).toBe(false);
    expect(isSettingsEqual(null, null)).toBe(true);
    expect(isSettingsEqual(undefined, undefined)).toBe(true);
    expect(isSettingsEqual(null, undefined)).toBe(false);
    expect(isSettingsEqual(NaN, NaN)).toBe(true);
  });

  it('compares arrays correctly', () => {
    expect(isSettingsEqual([1, 2, 3], [1, 2, 3])).toBe(true);
    expect(isSettingsEqual([1, 2, 3], [1, 2, 4])).toBe(false);
    expect(isSettingsEqual([1, 2], [1, 2, 3])).toBe(false);
    expect(isSettingsEqual([1, [2, 3]], [1, [2, 3]])).toBe(true);
  });

  it('compares nested plain objects independent of key order', () => {
    expect(isSettingsEqual({ a: 1, b: 2 }, { b: 2, a: 1 })).toBe(true);
    expect(isSettingsEqual({ a: 1, b: { c: 3 } }, { a: 1, b: { c: 3 } })).toBe(true);
    expect(isSettingsEqual({ a: 1, b: { c: 3 } }, { a: 1, b: { c: 4 } })).toBe(false);
    expect(isSettingsEqual({ a: 1 }, { a: 1, b: 2 })).toBe(false);
  });
});

describe('mergeLeafProperties', () => {
  it('preserves disk update when incoming matches baseline', () => {
    const incoming = { a: 1, b: 2 };
    const disk = { a: 1, b: 3 };
    const baseline = { a: 1, b: 2 };
    expect(mergeLeafProperties(incoming, disk, baseline)).toEqual({ a: 1, b: 3 });
  });

  it('preserves incoming update when disk matches baseline', () => {
    const incoming = { a: 1, b: 4 };
    const disk = { a: 1, b: 2 };
    const baseline = { a: 1, b: 2 };
    expect(mergeLeafProperties(incoming, disk, baseline)).toEqual({ a: 1, b: 4 });
  });

  it('merges non-conflicting leaf updates across different branches', () => {
    const incoming = { markov: { lookback: 20 }, confidenceGate: { cautionBelow: 64 } };
    const disk = { markov: { lookback: 55 }, confidenceGate: { cautionBelow: 50 } };
    const baseline = { markov: { lookback: 20 }, confidenceGate: { cautionBelow: 50 } };
    expect(mergeLeafProperties(incoming, disk, baseline)).toEqual({
      markov: { lookback: 55 },
      confidenceGate: { cautionBelow: 64 },
    });
  });

  it('resolves same-leaf conflict in favor of active incoming edit', () => {
    const incoming = { markov: { lookback: 45 } };
    const disk = { markov: { lookback: 55 } };
    const baseline = { markov: { lookback: 20 } };
    expect(mergeLeafProperties(incoming, disk, baseline)).toEqual({
      markov: { lookback: 45 },
    });
  });

  it('recursively merges nested properties at arbitrary depth (F-08)', () => {
    const incoming = {
      confidenceGate: {
        atrMult: {
          swing: { target: 3.0, stop: 1.5 },
          intraday: { target: 1.8, stop: 1.5 },
        },
      },
    };
    const disk = {
      confidenceGate: {
        atrMult: {
          swing: { target: 3.5, stop: 1.5 },
          intraday: { target: 2.0, stop: 1.5 },
        },
      },
    };
    const baseline = {
      confidenceGate: {
        atrMult: {
          swing: { target: 3.0, stop: 1.5 },
          intraday: { target: 2.0, stop: 1.5 },
        },
      },
    };
    expect(mergeLeafProperties(incoming, disk, baseline)).toEqual({
      confidenceGate: {
        atrMult: {
          swing: { target: 3.5, stop: 1.5 },
          intraday: { target: 1.8, stop: 1.5 },
        },
      },
    });
  });
});

describe('settingsLostUpdate — end to end store behavior', () => {
  beforeEach(() => {
    localStorage.clear();
    const initial = useSettingsStore.getInitialState?.() ?? {};
    useSettingsStore.setState(initial, true);
    setLastCommittedSettings(null);
  });

  afterEach(() => {
    localStorage.clear();
  });

  it('reproduces and resolves S5: stale Tab B edit does not overwrite unrelated Tab A edit', () => {
    // 1. Initial shared baseline: markov.lookback: 20, confidenceGate.cautionBelow: 50
    const baselineState = {
      ...getDefaultPersistedSettings(),
      markov: { ...DEFAULT_MARKOV, lookback: 20 },
      confidenceGate: { ...DEFAULT_CONFIDENCE_GATE, cautionBelow: 50 },
    };
    localStorage.setItem(
      SETTINGS_STORAGE_KEY,
      JSON.stringify({ state: baselineState, version: 24 }),
    );

    // Tab B initializes with baseline
    useSettingsStore.persist.rehydrate();
    expect(useSettingsStore.getState().markov.lookback).toBe(20);
    expect(useSettingsStore.getState().confidenceGate.cautionBelow).toBe(50);
    expect(getLastCommittedSettings()?.markov).toEqual(baselineState.markov);

    // 2. Tab A executes concurrently and writes markov.lookback: 55 to disk
    const tabADiskState = {
      ...baselineState,
      markov: { ...DEFAULT_MARKOV, lookback: 55 },
    };
    localStorage.setItem(
      SETTINGS_STORAGE_KEY,
      JSON.stringify({ state: tabADiskState, version: 24 }),
    );

    // 3. Tab B (which has not yet synced or blurred) now edits confidenceGate.cautionBelow to 64
    act(() => {
      useSettingsStore.getState().setConfidenceGate({
        ...DEFAULT_CONFIDENCE_GATE,
        cautionBelow: 64,
      });
    });

    // 4. Verify that localStorage has Tab A's markov.lookback: 55 AND Tab B's cautionBelow: 64
    const stored = JSON.parse(localStorage.getItem(SETTINGS_STORAGE_KEY) ?? '{}');
    expect(stored.state.markov.lookback).toBe(55);
    expect(stored.state.confidenceGate.cautionBelow).toBe(64);

    // 5. Verify that in-memory store in Tab B is also updated with disk changes
    expect(useSettingsStore.getState().markov.lookback).toBe(55);
    expect(useSettingsStore.getState().confidenceGate.cautionBelow).toBe(64);
  });

  it('resolves F-08: merges nested atrMult properties without dropping independent horizon edits', () => {
    const baselineState = {
      ...getDefaultPersistedSettings(),
      confidenceGate: {
        ...DEFAULT_CONFIDENCE_GATE,
        atrMult: {
          intraday: { target: 2.0, stop: 1.5 },
          swing:    { target: 3.0, stop: 1.5 },
          position: { target: 2.5, stop: 1.5 },
        },
      },
    };
    localStorage.setItem(
      SETTINGS_STORAGE_KEY,
      JSON.stringify({ state: baselineState, version: 24 }),
    );

    useSettingsStore.persist.rehydrate();

    // Tab A writes swing.target = 3.5
    const tabADiskState = {
      ...baselineState,
      confidenceGate: {
        ...baselineState.confidenceGate,
        atrMult: {
          ...baselineState.confidenceGate.atrMult,
          swing: { target: 3.5, stop: 1.5 },
        },
      },
    };
    localStorage.setItem(
      SETTINGS_STORAGE_KEY,
      JSON.stringify({ state: tabADiskState, version: 24 }),
    );

    // Tab B writes intraday.target = 1.8
    act(() => {
      useSettingsStore.getState().setConfidenceGate({
        ...useSettingsStore.getState().confidenceGate,
        atrMult: {
          ...useSettingsStore.getState().confidenceGate.atrMult,
          intraday: { target: 1.8, stop: 1.5 },
        },
      });
    });

    const stored = JSON.parse(localStorage.getItem(SETTINGS_STORAGE_KEY) ?? '{}');
    expect(stored.state.confidenceGate.atrMult.swing.target).toBe(3.5);
    expect(stored.state.confidenceGate.atrMult.intraday.target).toBe(1.8);
    expect(useSettingsStore.getState().confidenceGate.atrMult.swing.target).toBe(3.5);
    expect(useSettingsStore.getState().confidenceGate.atrMult.intraday.target).toBe(1.8);
  });

  it('resolves F-05: re-clamps merged thresholds to maintain rejectBelow <= cautionBelow invariant', () => {
    // Initial baseline: cautionBelow 50, rejectBelow 35
    const baselineState = {
      ...getDefaultPersistedSettings(),
      confidenceGate: { ...DEFAULT_CONFIDENCE_GATE, cautionBelow: 50, rejectBelow: 35 },
    };
    localStorage.setItem(
      SETTINGS_STORAGE_KEY,
      JSON.stringify({ state: baselineState, version: 24 }),
    );

    useSettingsStore.persist.rehydrate();

    // Tab A lowers cautionBelow to 40
    const tabADiskState = {
      ...baselineState,
      confidenceGate: { ...baselineState.confidenceGate, cautionBelow: 40, rejectBelow: 35 },
    };
    localStorage.setItem(
      SETTINGS_STORAGE_KEY,
      JSON.stringify({ state: tabADiskState, version: 24 }),
    );

    // Tab B raises rejectBelow to 45 (which would invert if merged without re-clamping)
    act(() => {
      useSettingsStore.getState().setConfidenceGate({
        ...DEFAULT_CONFIDENCE_GATE,
        cautionBelow: 50,
        rejectBelow: 45,
      });
    });

    const stored = JSON.parse(localStorage.getItem(SETTINGS_STORAGE_KEY) ?? '{}');
    // cautionBelow was 40, rejectBelow was 45 -> re-clamped so rejectBelow <= cautionBelow
    expect(stored.state.confidenceGate.cautionBelow).toBe(40);
    expect(stored.state.confidenceGate.rejectBelow).toBe(40);
    expect(stored.state.confidenceGate.rejectBelow).toBeLessThanOrEqual(stored.state.confidenceGate.cautionBelow);
  });

  it('resolves F-02: fresh session with empty storage does not crash on null dereference', () => {
    localStorage.clear();
    setLastCommittedSettings(null);

    // Writing to store should fall back to getDefaultPersistedSettings() without throwing TypeError
    expect(() => {
      act(() => {
        useSettingsStore.getState().setMarkov({ ...DEFAULT_MARKOV, lookback: 55 });
      });
    }).not.toThrow();

    const stored = JSON.parse(localStorage.getItem(SETTINGS_STORAGE_KEY) ?? '{}');
    expect(stored.state.markov.lookback).toBe(55);
    expect(getLastCommittedSettings()?.markov).toEqual({ ...DEFAULT_MARKOV, lookback: 55 });
  });

  it('resolves F-07: pre-v24 disk state migrates when establishing baseline, preventing spurious diffs', () => {
    // Legacy disk at version 21 without targetProfitPct or per-horizon atrMult
    const legacyState = {
      markov: { ...DEFAULT_MARKOV, lookback: 25 },
      confidenceGate: { enabled: true, cautionBelow: 55, rejectBelow: 35, atrMult: 2.0 },
    };
    localStorage.setItem(
      SETTINGS_STORAGE_KEY,
      JSON.stringify({ state: legacyState, version: 21 }),
    );

    const storage = createSettingsStateStorage();
    storage.getItem(SETTINGS_STORAGE_KEY);

    // Baseline should have migrated atrMult to per-horizon structure
    const baseline = getLastCommittedSettings();
    expect(baseline).toBeDefined();
    const gate = baseline?.confidenceGate as Record<string, unknown>;
    expect(gate.atrMult).toEqual(DEFAULT_ATR_MULT_BY_HORIZON);
    expect(gate.cautionBelow).toBe(55);
  });

  it('resolves F-09: StorageEvent updates in-memory store synchronously without write echo', () => {
    const storageSpy = jest.spyOn(Storage.prototype, 'setItem');

    const updatedState = {
      ...getDefaultPersistedSettings(),
      markov: { ...DEFAULT_MARKOV, lookback: 70 },
    };
    const serialized = JSON.stringify({ state: updatedState, version: 24 });

    // Clear calls from setup
    storageSpy.mockClear();

    // Dispatch cross-tab storage event
    act(() => {
      window.dispatchEvent(
        new StorageEvent('storage', {
          key: SETTINGS_STORAGE_KEY,
          newValue: serialized,
        }),
      );
    });

    // In-memory store should update synchronously
    expect(useSettingsStore.getState().markov.lookback).toBe(70);
    // Baseline should update synchronously
    expect((getLastCommittedSettings()?.markov as typeof DEFAULT_MARKOV)?.lookback).toBe(70);

    // Storage.setItem must NOT have been called as an echo of the storage event
    expect(storageSpy).not.toHaveBeenCalled();

    storageSpy.mockRestore();
  });

  it('preserves reportingLocalStorage error tracking on quota failure (Criterion 6)', () => {
    const setItemSpy = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('QuotaExceededError', 'QuotaExceededError');
    });

    expect(() => {
      act(() => {
        useSettingsStore.getState().setMarkov({ ...DEFAULT_MARKOV, lookback: 80 });
      });
    }).toThrow();

    const failure = useSettingsSaveStatus.getState().localFailures[SETTINGS_STORAGE_KEY];
    expect(failure).toBeDefined();
    expect(failure?.label).toBe('Settings (this browser)');

    setItemSpy.mockRestore();
  });
});
