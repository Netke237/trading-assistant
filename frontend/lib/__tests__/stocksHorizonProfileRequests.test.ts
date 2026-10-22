/*
 * STOCKS-HORIZON-T1 H5: a stock scan request carries `params_horizon` and
 * only the strategy fields the user overrode; everything else follows the
 * backend horizon profile. Covers the manual scan, the scheduled-scan body,
 * both persisted-store migrations and the search-profile round trip.
 */
import { runStockScan } from '@/lib/stockScan';
import { useScanStore } from '@/lib/scanStore';
import {
  useScanParamsStore, migrateScanParams, SCAN_PARAM_DEFAULTS, OVERRIDE_FIELDS,
} from '@/lib/scanParamsStore';
import { useSearchProfilesStore } from '@/lib/searchProfilesStore';
import { captureCurrentSnapshot, applySearchProfile } from '@/lib/searchProfileSnapshot';
import { resolveProfileToScanRequest } from '@/lib/scanScheduleResolve';
import { useSettingsStore, DEFAULT_CONFIDENCE_GATE } from '@/lib/settingsStore';
import { useRiskStore } from '@/lib/riskStore';
import { api } from '@/lib/api';
import type { SearchProfile } from '@/types/searchProfile';
import type { HorizonKey } from '@/lib/horizonPresets';

jest.mock('@/lib/api', () => ({
  api: {
    postStockScan: jest.fn(),
    getLastStockScanStatus: jest.fn(),
    getScanSchedule: jest.fn(() => Promise.resolve([])),
  },
  getLastDataRefresh: jest.fn(() => Promise.resolve({ last_refresh: null })),
  API_BASE_URL: 'http://localhost:8000',
}));

const m = (f: unknown) => f as jest.Mock;

// Every strategy field of StockScanRequest (backend horizon_profiles.STRATEGY_REQUEST_FIELDS).
const STRATEGY_WIRE_FIELDS = [
  'pullback_tolerance_pct', 'pullback_ema_period', 'pullback_trend_ema', 'pullback_ma_type',
  'ma_crossover_fast', 'ma_crossover_slow', 'ma_crossover_lookback', 'breakout_volume_mult',
  'rsi_period', 'rsi_oversold', 'rsi_overbought', 'rsi_trend_sma', 'require_choppy_regime',
  'mean_reversion_variants', 'mean_reversion_min_confirmations', 'vwap_lookback', 'vwap_deviation_pct',
];
const strategyFieldsOf = (b: Record<string, unknown>) =>
  STRATEGY_WIRE_FIELDS.filter((k) => b[k] !== undefined);

function context(horizonPreset: HorizonKey, holdMin: number, holdMax: number, horizon: string) {
  return { universe: 'SP500', direction: 'Bullish', horizon, horizonPreset, holdMin, holdMax };
}

beforeEach(() => {
  m(api.postStockScan).mockReset();
  m(api.postStockScan).mockResolvedValue({ scan_id: 'S', timestamp: '2026-10-09T10:00:00+00:00', rejected: [], candidates: [] });
  m(api.getLastStockScanStatus).mockResolvedValue({ status: 'idle', updated_at: null, strategy: null });
  useScanStore.setState({
    context: context('Quarterly', 45, 60, 'Position (45–60d)'),
    scanOverrides: {}, stockScanResult: null, stockScanRequest: null,
    activeStrategy: null, scanState: 'IDLE', stockScanError: null,
  } as never);
  useScanParamsStore.setState({ ...SCAN_PARAM_DEFAULTS });
  useSettingsStore.setState({ confidenceGate: { ...DEFAULT_CONFIDENCE_GATE } });
  useRiskStore.setState((s) => ({ limits: { ...s.limits, portfolioValue: 50_000, maxLossPerTradePct: 0.01 } }));
});

async function scanBody(strategy: string, overrides = {}) {
  m(api.postStockScan).mockClear();
  await runStockScan(strategy, overrides);
  return m(api.postStockScan).mock.calls[0][0] as Record<string, unknown>;
}

describe('manual scan request', () => {
  it('no overrides -> no strategy fields, params_horizon Quarterly for Quarterly', async () => {
    const b = await scanBody('mean_reversion_multi');
    expect(strategyFieldsOf(b)).toEqual([]);
    expect(b.params_horizon).toBe('Quarterly');
    // Untuned settings still travel.
    expect(b.bt_min_trades).toBe(SCAN_PARAM_DEFAULTS.btMinTrades);
  });

  it('Custom 60-185 -> params_horizon Annual', async () => {
    useScanStore.setState({ context: context('Custom', 60, 185, 'Position (60–185d)') } as never);
    expect((await scanBody('pullback_ema')).params_horizon).toBe('Annual');
  });

  it('Intraday -> no params_horizon', async () => {
    useScanStore.setState({ context: context('Intraday', 0, 2, 'Intraday (0–2d)') } as never);
    const b = await scanBody('pullback_ema');
    expect('params_horizon' in b && b.params_horizon !== undefined).toBe(false);
  });

  it('one override -> only that strategy field', async () => {
    useScanParamsStore.getState().setParam('rsiOverbought', 75);
    const b = await scanBody('mean_reversion_rsi');
    expect(strategyFieldsOf(b)).toEqual(['rsi_overbought']);
    expect(b.rsi_overbought).toBe(75);
  });

  it('a panel edit passed to the scan is the only strategy field', async () => {
    const b = await scanBody('pullback_ema', { pullbackEmaPeriod: 34 });
    expect(strategyFieldsOf(b)).toEqual(['pullback_ema_period']);
  });
});

describe('scanParamsStore migration (v11 -> v12)', () => {
  it('sets every override field to null and keeps the other settings', () => {
    const migrated = migrateScanParams({
      pullbackTolerancePct: 0.08, rsiOversold: 25, meanReversionVariants: ['mean_reversion_rsi'],
      vwapLookback: 20, btMinTrades: 12, eventFilter: 'avoid', stockShortlistMax: 7,
    }, 11);
    for (const f of OVERRIDE_FIELDS) expect(migrated[f]).toBeNull();
    expect(migrated.btMinTrades).toBe(12);
    expect(migrated.eventFilter).toBe('avoid');
    expect(migrated.stockShortlistMax).toBe(7);
  });

  it('a v12 store keeps its overrides', () => {
    expect(migrateScanParams({ rsiOversold: 25 }, 12).rsiOversold).toBe(25);
  });
});

describe('searchProfilesStore migration (v4 -> v5)', () => {
  const key = 'bamendjou:search-profiles';
  const baseProfile = {
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
    direction: 'Bullish' as const,
    horizonPreset: 'Swing' as const,
    holdMin: 5,
    holdMax: 15,
    universe: {
      pick: 'SP500' as const,
      customRaw: '',
      minPriceRaw: '',
      maxPriceRaw: '',
      minCapRaw: '',
      maxCapRaw: '',
      capUnit: 'B' as const,
    },
    scanSettings: {
      confidenceGate: {
        enabled: true,
        cautionBelow: 50,
        rejectBelow: 35,
        atrMult: {
          intraday: { target: 2.0, stop: 1.5 },
          swing: { target: 3.0, stop: 1.5 },
          position: { target: 2.5, stop: 1.5 },
        },
      },
    },
  };

  beforeEach(() => {
    localStorage.clear();
    useSearchProfilesStore.setState({ profiles: [], legacyTargetPctDropped: false });
  });

  it('resets each saved profile\'s override fields to follow the profile, other fields kept', async () => {
    localStorage.setItem(key, JSON.stringify({ version: 4, state: { profiles: [{
      ...baseProfile,
      id: 'saved', name: 'Saved', mode: 'stocks', strategy: 'pullback_ema', scanOverrides: { fast_ema: 11 },
      strategyParams: {
        ...SCAN_PARAM_DEFAULTS, pullbackTolerancePct: 0.08, rsiOversold: 25, maCrossoverFast: 20,
        meanReversionVariants: ['mean_reversion_rsi'], btMinTrades: 12, btMinWinRate: 0.5,
      },
    }, { ...baseProfile, id: 'opt', name: 'Options', mode: 'options', scanOverrides: {} }] } }));
    await useSearchProfilesStore.persist.rehydrate();
    const [stocks, options] = useSearchProfilesStore.getState().profiles;
    const sp = stocks.strategyParams as unknown as Record<string, unknown>;
    for (const f of OVERRIDE_FIELDS) expect(sp[f] ?? null).toBeNull();
    expect(sp.btMinTrades).toBe(12);
    expect(sp.btMinWinRate).toBe(0.5);
    expect(stocks.scanOverrides).toEqual({ fast_ema: 11 });
    expect(options.strategyParams).toBeUndefined();
    expect(JSON.parse(localStorage.getItem(key)!).version).toBe(5);
  });
});

describe('saved search profile round trip', () => {
  it('keeps an override and nothing else', () => {
    useScanStore.setState({ activeStrategy: 'pullback_ema' } as never);
    useScanParamsStore.getState().setParam('pullbackTolerancePct', 0.06);
    const snap = captureCurrentSnapshot('stocks');
    const saved = snap.strategyParams as unknown as Record<string, unknown>;
    expect(OVERRIDE_FIELDS.filter((f) => saved[f] !== undefined && saved[f] !== null)).toEqual(['pullbackTolerancePct']);

    // Another override set after saving must be cleared by loading the profile.
    useScanParamsStore.getState().setParam('rsiOversold', 22);
    applySearchProfile({ ...snap, id: 'p', name: 'p', createdAt: '', updatedAt: '' });
    const p = useScanParamsStore.getState();
    expect(p.pullbackTolerancePct).toBe(0.06);
    for (const f of OVERRIDE_FIELDS.filter((x) => x !== 'pullbackTolerancePct')) expect(p[f]).toBeNull();
  });
});

describe('scheduled scan body', () => {
  function stockProfile(strategyParams: SearchProfile['strategyParams']): SearchProfile {
    return {
      id: 'p1', name: 'P', mode: 'stocks', createdAt: '', updatedAt: '',
      universe: { pick: 'SP500', customRaw: '', minPriceRaw: '', maxPriceRaw: '', minCapRaw: '', maxCapRaw: '', capUnit: 'B' },
      direction: 'Bullish', horizonPreset: 'Custom', holdMin: 60, holdMax: 185,
      scanOverrides: {}, scanSettings: { confidenceGate: { ...DEFAULT_CONFIDENCE_GATE } },
      strategy: 'ma_crossover', strategyParams,
    };
  }

  it('carries params_horizon and only the overrides', () => {
    const { btMinTrades, btMinWinRate, eventFilter, stockShortlistMax } = SCAN_PARAM_DEFAULTS;
    const body = resolveProfileToScanRequest(stockProfile({
      btMinTrades, btMinWinRate, eventFilter, stockShortlistMax, maCrossoverSlow: 100,
    })) as unknown as Record<string, unknown>;
    expect(body.params_horizon).toBe('Annual');
    expect(strategyFieldsOf(body)).toEqual(['ma_crossover_slow']);
    expect(body.ma_crossover_slow).toBe(100);
  });
});
