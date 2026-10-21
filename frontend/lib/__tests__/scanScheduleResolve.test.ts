import { SCAN_PARAM_DEFAULTS } from '@/lib/scanParamsStore';
import { DEFAULT_CONFIDENCE_GATE, DEFAULT_FUNDAMENTALS_GATE, DEFAULT_SPREADS } from '@/lib/settingsStore';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { useRiskStore } from '@/lib/riskStore';
import { resolveProfileToScanRequest, scheduleRiskIgnored } from '@/lib/scanScheduleResolve';
import type { SearchProfile } from '@/types/searchProfile';
import type { StockScanRequestBody } from '@/lib/resolveStockScanRequest';

const BASE_RISK_LIMITS = {
  portfolioValue: 100_000, maxLossPerTradePct: 0.0375, maxSingleStockPositionPct: 0.2, maxTotalStockExposurePct: 1,
  maxSingleTradeExposurePct: 0.05, maxTotalExposurePct: 0.25,
  maxConcurrentPositions: 10, maxDailyRecommendations: 5,
};

// Regression coverage for a gap caught by post-implementation adversarial
// review: resolveProfileToScanRequest's stocks-mode branch used to wrap
// `profile.universe.pick` in an array directly, so a stocks-mode profile
// saved with universe pick 'Custom' or 'Watchlist' would resolve to a
// schedule entry whose universe was literally ["Custom"]/["Watchlist"] — a
// single nonexistent ticker, scanned "successfully" forever. The
// options-mode branch already resolved these correctly; the fix reuses the
// same logic for both modes.

function baseProfile(overrides: Partial<SearchProfile> = {}): SearchProfile {
  return {
    id: 'p1',
    name: 'Test profile',
    mode: 'options',
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
    universe: {
      pick: 'SP500', customRaw: '', minPriceRaw: '', maxPriceRaw: '',
      minCapRaw: '', maxCapRaw: '', capUnit: 'B',
    },
    direction: 'Bullish',
    horizonPreset: 'Swing',
    holdMin: 5,
    holdMax: 15,
    scanOverrides: {},
    scanSettings: {
      confidenceGate: { ...DEFAULT_CONFIDENCE_GATE },
      fundamentalsGate: { ...DEFAULT_FUNDAMENTALS_GATE },
      shortlistMaxCandidates: 10,
      spreads: { ...DEFAULT_SPREADS },
    },
    ...overrides,
  };
}

function stockProfile(overrides: Partial<SearchProfile> = {}): SearchProfile {
  return baseProfile({
    mode: 'stocks',
    strategy: 'pullback_ema',
    strategyParams: { ...SCAN_PARAM_DEFAULTS },
    scanSettings: { confidenceGate: { ...DEFAULT_CONFIDENCE_GATE } },
    ...overrides,
  });
}

beforeEach(() => {
  useWatchlistStore.setState({ added: ['AAPL', 'MSFT'] });
  useRiskStore.setState({ limits: { ...BASE_RISK_LIMITS } });
});

describe('resolveProfileToScanRequest — universe resolution, options mode', () => {
  it('resolves a preset pick to itself', () => {
    const req = resolveProfileToScanRequest(baseProfile({ universe: { ...baseProfile().universe, pick: 'NDX100' } }));
    expect(req.universe).toEqual(['NDX100']);
  });

  it('resolves Custom to the parsed symbol list', () => {
    const req = resolveProfileToScanRequest(baseProfile({
      universe: { ...baseProfile().universe, pick: 'Custom', customRaw: 'AAPL, msft ; TSLA' },
    }));
    expect(req.universe.sort()).toEqual(['AAPL', 'MSFT', 'TSLA']);
  });

  it('resolves Watchlist to the current watchlist contents', () => {
    const req = resolveProfileToScanRequest(baseProfile({
      universe: { ...baseProfile().universe, pick: 'Watchlist' },
    }));
    expect(req.universe).toEqual(['AAPL', 'MSFT']);
  });
});

describe('resolveProfileToScanRequest — universe resolution, stocks mode', () => {
  it('resolves a preset pick to itself', () => {
    const req = resolveProfileToScanRequest(stockProfile({ universe: { ...stockProfile().universe, pick: 'DOW30' } }));
    expect(req.universe).toEqual(['DOW30']);
  });

  it('resolves Custom to the parsed symbol list, not the literal string "Custom"', () => {
    const req = resolveProfileToScanRequest(stockProfile({
      universe: { ...stockProfile().universe, pick: 'Custom', customRaw: 'AAPL,MSFT' },
    }));
    expect(req.universe.sort()).toEqual(['AAPL', 'MSFT']);
    expect(req.universe).not.toContain('Custom');
  });

  it('resolves Watchlist to the current watchlist contents, not the literal string "Watchlist"', () => {
    const req = resolveProfileToScanRequest(stockProfile({
      universe: { ...stockProfile().universe, pick: 'Watchlist' },
    }));
    expect(req.universe).toEqual(['AAPL', 'MSFT']);
    expect(req.universe).not.toContain('Watchlist');
  });
});

describe('resolveProfileToScanRequest — risk fields (stocks mode)', () => {
  it('pulls account_size/risk_pct from the live riskStore, not hardcoded defaults', () => {
    useRiskStore.setState({ limits: { ...BASE_RISK_LIMITS, portfolioValue: 250_000, maxLossPerTradePct: 0.02 } });
    const req = resolveProfileToScanRequest(stockProfile()) as StockScanRequestBody;
    expect(req.account_size).toBe(250_000);
    expect(req.risk_pct).toBe(0.02);
  });
});

describe('resolveProfileToScanRequest — error cases', () => {
  it('throws for a stocks-mode profile with no strategy selected', () => {
    expect(() => resolveProfileToScanRequest(stockProfile({ strategy: undefined, strategyParams: undefined })))
      .toThrow(/no strategy selected/);
  });

  it('throws for an options-mode profile missing fundamentalsGate/spreads', () => {
    expect(() => resolveProfileToScanRequest(baseProfile({
      scanSettings: { confidenceGate: { ...DEFAULT_CONFIDENCE_GATE } },
    }))).toThrow(/fundamentalsGate\/spreads/);
  });
});

// P3c item 3 — decision P3C-SCHEDULE-ZERO-RISK-WARNS-2026-09-25.
describe('scheduleRiskIgnored', () => {
  it('is true for a stocks entry saved with risk_pct 0', () => {
    expect(scheduleRiskIgnored({ mode: 'stocks', resolved_request: { risk_pct: 0 } })).toBe(true);
  });
  it('is false for a stocks entry with a non-zero risk_pct', () => {
    expect(scheduleRiskIgnored({ mode: 'stocks', resolved_request: { risk_pct: 0.02 } })).toBe(false);
  });
  it('is false for a stocks entry with no risk_pct', () => {
    expect(scheduleRiskIgnored({ mode: 'stocks', resolved_request: { risk_pct: undefined } })).toBe(false);
    expect(scheduleRiskIgnored({ mode: 'stocks', resolved_request: {} })).toBe(false);
    expect(scheduleRiskIgnored({ mode: 'stocks', resolved_request: null })).toBe(false);
  });
  it('is false for an options entry', () => {
    expect(scheduleRiskIgnored({ mode: 'options', resolved_request: { risk_pct: 0 } })).toBe(false);
    expect(scheduleRiskIgnored({ mode: 'options', resolved_request: { universe: ['SP500'] } })).toBe(false);
  });
});

describe('resolveProfileToScanRequest — hold (stocks mode, STOCKS-HORIZON-P0B B6)', () => {
  it('sends the profile hold as hold_max_days', () => {
    const req = resolveProfileToScanRequest(stockProfile()) as StockScanRequestBody;
    expect(req.hold_max_days).toBe(15);
  });

  it('a Custom 60-185 profile sends 185, not the Custom preset row', () => {
    const req = resolveProfileToScanRequest(stockProfile({
      horizonPreset: 'Custom', holdMin: 60, holdMax: 185,
    })) as StockScanRequestBody;
    expect(req.horizon).toBe('Position');
    expect(req.hold_max_days).toBe(185);
  });
});

// #368: literal USD expectations, independent of the conversion implementation.
describe('Options cap units in saved profiles', () => {
  it.each([
    ['M', '25', 25_000_000], ['B', '2', 2_000_000_000],
    ['M', '0.5', 500_000], ['B', '0.25', 250_000_000],
    ['M', '0', 0], ['B', '0', 0],
    ['M', '', undefined], ['B', '', undefined],
    ['M', 'NaN', undefined], ['B', 'Infinity', undefined],
  ] as const)('%s %s resolves both bounds to %s USD', (capUnit, raw, usd) => {
    const profile = baseProfile();
    profile.universe = { ...profile.universe, capUnit, minCapRaw: raw, maxCapRaw: raw };
    const req = resolveProfileToScanRequest(profile);
    expect((req as import('@/lib/resolveOptionsScanRequest').OptionsScanRequestBody).min_cap_usd).toBe(usd);
    expect((req as import('@/lib/resolveOptionsScanRequest').OptionsScanRequestBody).max_cap_usd).toBe(usd);
    expect(req).toMatchObject({ cap_filter_units_version: 1 });
    if (usd === undefined) {
      expect(req).not.toHaveProperty('min_cap_usd');
      expect(req).not.toHaveProperty('max_cap_usd');
    }
  });
});
