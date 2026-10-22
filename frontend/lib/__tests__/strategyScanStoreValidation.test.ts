import { useScanParamsStore, SCAN_PARAM_DEFAULTS } from '@/lib/scanParamsStore';
import { useSearchProfilesStore } from '@/lib/searchProfilesStore';
import { applySearchProfile, captureCurrentSnapshot } from '@/lib/searchProfileSnapshot';
import { buildStockScanRequestBody } from '@/lib/resolveStockScanRequest';
import { StrategyScanValidationError } from '@/lib/strategyScanValidation';
import { useUniverseStore } from '@/lib/universeStore';
import { useScanStore } from '@/lib/scanStore';
import { DEFAULT_CONFIDENCE_GATE } from '@/lib/settingsStore';
import type { SearchProfile } from '@/types/searchProfile';

describe('scanParamsStore — validation on setParam and loadParams', () => {
  beforeEach(() => {
    useScanParamsStore.getState().resetToDefaults();
  });

  it('accepts valid overrides and null', () => {
    const store = useScanParamsStore.getState();
    store.setParam('pullbackTolerancePct', 0.08);
    expect(useScanParamsStore.getState().pullbackTolerancePct).toBe(0.08);

    store.setParam('maCrossoverLookback', 20);
    expect(useScanParamsStore.getState().maCrossoverLookback).toBe(20);

    store.setParam('breakoutVolumeMult', 2.5);
    expect(useScanParamsStore.getState().breakoutVolumeMult).toBe(2.5);

    store.setParam('pullbackTolerancePct', null);
    expect(useScanParamsStore.getState().pullbackTolerancePct).toBeNull();
  });

  it('rejects invalid pullbackTolerancePct (0.0, -0.01) and preserves existing store state', () => {
    const store = useScanParamsStore.getState();
    store.setParam('pullbackTolerancePct', 0.08);

    expect(() => store.setParam('pullbackTolerancePct', 0)).toThrow(StrategyScanValidationError);
    expect(useScanParamsStore.getState().pullbackTolerancePct).toBe(0.08);

    expect(() => store.setParam('pullbackTolerancePct', -0.02)).toThrow(StrategyScanValidationError);
    expect(useScanParamsStore.getState().pullbackTolerancePct).toBe(0.08);
  });

  it('rejects invalid maCrossoverLookback (0, 1.5) and preserves existing store state', () => {
    const store = useScanParamsStore.getState();
    store.setParam('maCrossoverLookback', 15);

    expect(() => store.setParam('maCrossoverLookback', 0)).toThrow(StrategyScanValidationError);
    expect(useScanParamsStore.getState().maCrossoverLookback).toBe(15);

    expect(() => store.setParam('maCrossoverLookback', 1.5)).toThrow(StrategyScanValidationError);
    expect(useScanParamsStore.getState().maCrossoverLookback).toBe(15);
  });

  it('rejects breakoutVolumeMult <= 1.0 (1.0, 0.9) and preserves existing store state', () => {
    const store = useScanParamsStore.getState();
    store.setParam('breakoutVolumeMult', 2.0);

    expect(() => store.setParam('breakoutVolumeMult', 1.0)).toThrow(StrategyScanValidationError);
    expect(useScanParamsStore.getState().breakoutVolumeMult).toBe(2.0);

    expect(() => store.setParam('breakoutVolumeMult', 0.8)).toThrow(StrategyScanValidationError);
    expect(useScanParamsStore.getState().breakoutVolumeMult).toBe(2.0);
  });

  it('preserves unrelated zero fields without throwing (e.g. btMinWinRate: 0, minStockScore: 0)', () => {
    const store = useScanParamsStore.getState();
    expect(() => store.setParam('btMinWinRate', 0)).not.toThrow();
    expect(useScanParamsStore.getState().btMinWinRate).toBe(0);
  });

  it('loadParams rejects invalid overrides atomically without modifying the store', () => {
    const store = useScanParamsStore.getState();
    store.setParam('pullbackTolerancePct', 0.08);

    expect(() =>
      store.loadParams({
        ...SCAN_PARAM_DEFAULTS,
        pullbackTolerancePct: 0,
      }),
    ).toThrow(StrategyScanValidationError);

    expect(useScanParamsStore.getState().pullbackTolerancePct).toBe(0.08);
  });
});

describe('searchProfilesStore & applySearchProfile — atomic validation', () => {
  const validSnapshot = captureCurrentSnapshot('stocks');

  beforeEach(() => {
    useSearchProfilesStore.setState({ profiles: [], staleScheduleEntryIds: [] });
    useUniverseStore.getState().setPick('SP500');
    useScanStore.getState().setContext({
      universe: 'SP500',
      direction: 'Bullish',
      horizon: 'Swing',
      horizonPreset: 'Swing',
      holdMin: 5,
      holdMax: 15,
    });
  });

  it('saveProfile and updateProfile reject snapshots with invalid strategy overrides', () => {
    const invalidSnapshot = {
      ...validSnapshot,
      strategyParams: {
        ...SCAN_PARAM_DEFAULTS,
        breakoutVolumeMult: 1.0, // invalid: must be > 1.0
      },
    };

    expect(() =>
      useSearchProfilesStore.getState().saveProfile('Bad Profile', invalidSnapshot),
    ).toThrow(StrategyScanValidationError);
    expect(useSearchProfilesStore.getState().profiles).toHaveLength(0);

    const validId = useSearchProfilesStore.getState().saveProfile('Good Profile', validSnapshot);
    expect(useSearchProfilesStore.getState().profiles).toHaveLength(1);

    expect(() =>
      useSearchProfilesStore.getState().updateProfile(validId, invalidSnapshot),
    ).toThrow(StrategyScanValidationError);
    // Profile untouched
    expect(useSearchProfilesStore.getState().profiles[0].strategyParams).toEqual(
      validSnapshot.strategyParams,
    );
  });

  it('applySearchProfile rejects invalid profile before any store mutation occurs', () => {
    useUniverseStore.getState().setPick('SP500');
    const badProfile: SearchProfile = {
      id: 'bad-1',
      name: 'Bad Profile',
      mode: 'stocks',
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
      universe: {
        pick: 'NDX100', // differs from SP500
        customRaw: '',
        minPriceRaw: '',
        maxPriceRaw: '',
        minCapRaw: '',
        maxCapRaw: '',
        capUnit: 'B',
      },
      direction: 'Bearish',
      horizonPreset: 'Quarterly',
      holdMin: 20,
      holdMax: 60,
      scanOverrides: {},
      strategy: 'pullback_ema',
      strategyParams: {
        ...SCAN_PARAM_DEFAULTS,
        pullbackTolerancePct: 0, // invalid!
      },
      scanSettings: { confidenceGate: { ...DEFAULT_CONFIDENCE_GATE } },
    };

    expect(() => applySearchProfile(badProfile)).toThrow(StrategyScanValidationError);

    // Universe was NOT updated to NDX100
    expect(useUniverseStore.getState().pick).toBe('SP500');
    // Context direction was NOT updated to Bearish
    expect(useScanStore.getState().context?.direction).toBe('Bullish');
  });
});

describe('buildStockScanRequestBody — fails closed on invalid strategy overrides', () => {
  it('throws StrategyScanValidationError when an invalid override is passed', () => {
    expect(() =>
      buildStockScanRequestBody({
        universe: ['SP500'],
        direction: 'Bullish',
        horizon: 'Swing',
        strategy: 'pullback_ema',
        params: {
          ...SCAN_PARAM_DEFAULTS,
          pullbackTolerancePct: 0,
        },
        requireReversal: false,
        scanOverrides: {},
        confidenceGate: { ...DEFAULT_CONFIDENCE_GATE },
        accountSize: 50_000,
        riskPct: 0.01,
        paramsHorizon: null,
        holdMinDays: 5,
        holdMaxDays: 15,
      }),
    ).toThrow(StrategyScanValidationError);
  });

  it('builds request successfully when overrides are valid or null', () => {
    const req = buildStockScanRequestBody({
      universe: ['SP500'],
      direction: 'Bullish',
      horizon: 'Swing',
      strategy: 'pullback_ema',
      params: {
        ...SCAN_PARAM_DEFAULTS,
        pullbackTolerancePct: 0.06,
        maCrossoverLookback: 15,
        breakoutVolumeMult: 1.8,
      },
      requireReversal: false,
      scanOverrides: {},
      confidenceGate: { ...DEFAULT_CONFIDENCE_GATE },
      accountSize: 50_000,
      riskPct: 0.01,
      paramsHorizon: null,
      holdMinDays: 5,
      holdMaxDays: 15,
    });
    expect(req.pullback_tolerance_pct).toBe(0.06);
    expect(req.ma_crossover_lookback).toBe(15);
    expect(req.breakout_volume_mult).toBe(1.8);
  });
});
