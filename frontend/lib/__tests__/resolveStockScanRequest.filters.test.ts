import { buildStockScanRequestBody, type ResolvedStockScanContext } from '@/lib/resolveStockScanRequest';
import { resolveProfileToScanRequest } from '@/lib/scanScheduleResolve';
import { runStockScanWithContinuation } from '@/lib/stockScan';
import { useUniverseStore } from '@/lib/universeStore';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore, SCAN_PARAM_DEFAULTS } from '@/lib/scanParamsStore';
import { useSettingsStore, DEFAULT_CONFIDENCE_GATE } from '@/lib/settingsStore';
import { useRiskStore } from '@/lib/riskStore';
import { api } from '@/lib/api';
import type { SearchProfile } from '@/types/searchProfile';

jest.mock('@/lib/api', () => ({
  api: {
    postStockScan: jest.fn(),
    getLastStockScanStatus: jest.fn().mockResolvedValue({ status: 'completed' }),
  },
}));

function baseContext(): ResolvedStockScanContext {
  return {
    universe: ['SP500'],
    direction: 'Bullish',
    horizon: 'Swing',
    strategy: 'pullback_ema',
    params: { ...SCAN_PARAM_DEFAULTS },
    paramsHorizon: 'Swing',
    requireReversal: false,
    scanOverrides: {},
    confidenceGate: { ...DEFAULT_CONFIDENCE_GATE },
    accountSize: 50_000,
    riskPct: 0.01,
    holdMinDays: 5,
    holdMaxDays: 15,
  };
}

describe('buildStockScanRequestBody — universe price and market cap filters (#380 / C2)', () => {
  it('omits filter keys when filter raw inputs are undefined or empty/whitespace', () => {
    const body1 = buildStockScanRequestBody(baseContext());
    expect('min_price' in body1).toBe(false);
    expect('max_price' in body1).toBe(false);
    expect('min_cap_usd' in body1).toBe(false);
    expect('max_cap_usd' in body1).toBe(false);

    const body2 = buildStockScanRequestBody({
      ...baseContext(),
      minPriceRaw: '',
      maxPriceRaw: '   ',
      minCapRaw: '',
      maxCapRaw: ' \t\n ',
      capUnit: 'B',
    });
    expect('min_price' in body2).toBe(false);
    expect('max_price' in body2).toBe(false);
    expect('min_cap_usd' in body2).toBe(false);
    expect('max_cap_usd' in body2).toBe(false);
  });

  it('preserves explicit zero for price and market cap filters', () => {
    const body = buildStockScanRequestBody({
      ...baseContext(),
      minPriceRaw: '0',
      maxPriceRaw: '0.0',
      minCapRaw: '0',
      maxCapRaw: '0',
      capUnit: 'M',
    });
    expect('min_price' in body).toBe(true);
    expect(body.min_price).toBe(0);
    expect('max_price' in body).toBe(true);
    expect(body.max_price).toBe(0);
    expect('min_cap_usd' in body).toBe(true);
    expect(body.min_cap_usd).toBe(0);
    expect('max_cap_usd' in body).toBe(true);
    expect(body.max_cap_usd).toBe(0);
  });

  it('correctly converts capUnit M to millions (1e6) and B to billions (1e9)', () => {
    const bodyM = buildStockScanRequestBody({
      ...baseContext(),
      minPriceRaw: '10.5',
      maxPriceRaw: '250',
      minCapRaw: '25',
      maxCapRaw: '100',
      capUnit: 'M',
    });
    expect(bodyM.min_price).toBe(10.5);
    expect(bodyM.max_price).toBe(250);
    expect(bodyM.min_cap_usd).toBe(25_000_000);
    expect(bodyM.max_cap_usd).toBe(100_000_000);

    const bodyB = buildStockScanRequestBody({
      ...baseContext(),
      minCapRaw: '2.5',
      maxCapRaw: '50',
      capUnit: 'B',
    });
    expect(bodyB.min_cap_usd).toBe(2_500_000_000);
    expect(bodyB.max_cap_usd).toBe(50_000_000_000);
  });

  it('defaults cap multiplier to 1e9 when capUnit is unspecified', () => {
    const body = buildStockScanRequestBody({
      ...baseContext(),
      minCapRaw: '10',
    });
    expect(body.min_cap_usd).toBe(10_000_000_000);
  });

  it('omits filter keys when inputs are invalid or non-finite numbers', () => {
    const body = buildStockScanRequestBody({
      ...baseContext(),
      minPriceRaw: 'abc',
      maxPriceRaw: 'NaN',
      minCapRaw: 'Infinity',
      maxCapRaw: '-Infinity',
    });
    expect('min_price' in body).toBe(false);
    expect('max_price' in body).toBe(false);
    expect('min_cap_usd' in body).toBe(false);
    expect('max_cap_usd' in body).toBe(false);
  });
});

describe('scheduled scans — resolveProfileToScanRequest price/cap propagation (#380)', () => {
  const baseProfile: SearchProfile = {
    id: 'test-profile',
    name: 'Test Stocks Profile',
    mode: 'stocks',
    strategy: 'pullback_ema',
    strategyParams: { ...SCAN_PARAM_DEFAULTS },
    universe: {
      pick: 'Custom',
      customRaw: 'AAPL, MSFT',
      minPriceRaw: '0',
      maxPriceRaw: '150',
      minCapRaw: '25',
      maxCapRaw: '50',
      capUnit: 'M',
    },
    direction: 'Bullish',
    horizonPreset: 'Swing',
    holdMin: 5,
    holdMax: 15,
    scanOverrides: {},
    scanSettings: {
      confidenceGate: { ...DEFAULT_CONFIDENCE_GATE },
    },
    createdAt: '2026-10-20T00:00:00Z',
    updatedAt: '2026-10-20T00:00:00Z',
  };

  it('forwards configured universe price and cap filters', () => {
    const req = resolveProfileToScanRequest(baseProfile);
    expect(req.min_price).toBe(0);
    expect(req.max_price).toBe(150);
    expect(req.min_cap_usd).toBe(25_000_000);
    expect(req.max_cap_usd).toBe(50_000_000);
  });

  it('omits filter keys when profile universe filters are blank', () => {
    const blankProfile: SearchProfile = {
      ...baseProfile,
      universe: {
        pick: 'SP500',
        customRaw: '',
        minPriceRaw: '',
        maxPriceRaw: '',
        minCapRaw: '',
        maxCapRaw: '',
        capUnit: 'B',
      },
    };
    const req = resolveProfileToScanRequest(blankProfile);
    expect('min_price' in req).toBe(false);
    expect('max_price' in req).toBe(false);
    expect('min_cap_usd' in req).toBe(false);
    expect('max_cap_usd' in req).toBe(false);
  });
});

describe('manual scans — runStockScanWithContinuation price/cap propagation (#380)', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (api.postStockScan as jest.Mock).mockResolvedValue({
      candidates: [],
      rejected: [],
    });
    useScanStore.getState().setContext({
      universe: 'SP500',
      direction: 'Bullish',
      horizon: 'Swing (5–15d)',
      horizonPreset: 'Swing',
      holdMin: 5,
      holdMax: 15,
    });
    useScanParamsStore.getState().loadParams({ ...SCAN_PARAM_DEFAULTS });
    useSettingsStore.getState().setConfidenceGate({ ...DEFAULT_CONFIDENCE_GATE });
    useRiskStore.getState().setLimits({ ...useRiskStore.getState().limits, portfolioValue: 100_000, maxLossPerTradePct: 0.01 });
  });

  it('reads price and cap filters from useUniverseStore and sends them to API', async () => {
    useUniverseStore.setState({
      minPriceRaw: '0',
      maxPriceRaw: '200',
      minCapRaw: '25',
      maxCapRaw: '75',
      capUnit: 'M',
    });

    await runStockScanWithContinuation('pullback_ema');

    expect(api.postStockScan).toHaveBeenCalledTimes(1);
    const sentBody = (api.postStockScan as jest.Mock).mock.calls[0][0];
    expect(sentBody.min_price).toBe(0);
    expect(sentBody.max_price).toBe(200);
    expect(sentBody.min_cap_usd).toBe(25_000_000);
    expect(sentBody.max_cap_usd).toBe(75_000_000);
  });

  it('omits filter keys when useUniverseStore filters are blank', async () => {
    useUniverseStore.setState({
      minPriceRaw: '',
      maxPriceRaw: '',
      minCapRaw: '',
      maxCapRaw: '',
      capUnit: 'B',
    });

    await runStockScanWithContinuation('pullback_ema');

    expect(api.postStockScan).toHaveBeenCalledTimes(1);
    const sentBody = (api.postStockScan as jest.Mock).mock.calls[0][0];
    expect('min_price' in sentBody).toBe(false);
    expect('max_price' in sentBody).toBe(false);
    expect('min_cap_usd' in sentBody).toBe(false);
    expect('max_cap_usd' in sentBody).toBe(false);
  });
});
