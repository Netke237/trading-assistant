import { useUniverseStore } from '@/lib/universeStore';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore, SCAN_PARAM_DEFAULTS } from '@/lib/scanParamsStore';
import { useSettingsStore, DEFAULT_CONFIDENCE_GATE, DEFAULT_ATR_MULT_BY_HORIZON, DEFAULT_FUNDAMENTALS_GATE, DEFAULT_SPREADS } from '@/lib/settingsStore';
import { captureCurrentSnapshot, applySearchProfile, stableStringify } from '@/lib/searchProfileSnapshot';

function resetStores() {
  useUniverseStore.setState({
    pick: 'SP500', customRaw: '', minPriceRaw: '', maxPriceRaw: '', minCapRaw: '', maxCapRaw: '', capUnit: 'B',
  });
  useScanStore.setState({
    context: {
      universe: 'SP500', direction: 'Bullish', horizon: 'Swing (5–15d)',
      horizonPreset: 'Swing', holdMin: 5, holdMax: 15,
    },
    scanOverrides: {},
    activeStrategy: null,
    previousRun: { scan_id: 'prev-1', timestamp: '2026-01-01T00:00:00', candidates: [], rejected: [] },
    previousStockScanResult: null,
  });
  useScanParamsStore.setState({ ...SCAN_PARAM_DEFAULTS });
  useSettingsStore.setState({
    confidenceGate:   { ...DEFAULT_CONFIDENCE_GATE },
    fundamentalsGate: { ...DEFAULT_FUNDAMENTALS_GATE },
    shortlistMaxCandidates: 10,
    spreads: { ...DEFAULT_SPREADS },
  });
}

beforeEach(resetStores);

describe('captureCurrentSnapshot / applySearchProfile — stocks mode', () => {
  it('round-trips universe, direction/horizon, scanOverrides, and strategy tuning', () => {
    useUniverseStore.setState({
      pick: 'NDX100', customRaw: 'AAPL,MSFT', minPriceRaw: '10', maxPriceRaw: '500',
      minCapRaw: '1', maxCapRaw: '100', capUnit: 'B',
    });
    useScanStore.setState({
      context: {
        universe: 'NDX100', direction: 'Bearish', horizon: 'Position (60–185d)',
        horizonPreset: 'Position', holdMin: 60, holdMax: 185,
      },
      scanOverrides: { weight_trend: 40, ema_required: false },
      activeStrategy: 'pullback_ema',
    });
    useScanParamsStore.getState().setParam('pullbackTolerancePct', 0.12);
    useScanParamsStore.getState().setParam('rsiOversold', 25);

    const captured = captureCurrentSnapshot('stocks');
    expect(captured.strategy).toBe('pullback_ema');
    expect(captured.strategyParams?.pullbackTolerancePct).toBe(0.12);
    expect(captured.strategyParams?.rsiOversold).toBe(25);

    // Mutate everything again, including a DIFFERENT strategy/params, to
    // prove apply genuinely restores the captured snapshot rather than
    // coincidentally matching current state.
    useUniverseStore.setState({ pick: 'DOW30', customRaw: '', minPriceRaw: '', maxPriceRaw: '', minCapRaw: '', maxCapRaw: '', capUnit: 'M' });
    useScanStore.setState({
      context: {
        universe: 'DOW30', direction: 'Bullish', horizon: 'Swing (5–15d)',
        horizonPreset: 'Swing', holdMin: 5, holdMax: 15,
      },
      scanOverrides: {},
      activeStrategy: 'breakout_base',
    });
    useScanParamsStore.getState().setParam('pullbackTolerancePct', 0.5);
    useScanParamsStore.getState().setParam('rsiOversold', 70);

    applySearchProfile({ ...captured, id: 'p1', name: 'test', createdAt: '', updatedAt: '' });

    const u = useUniverseStore.getState();
    expect(u.pick).toBe('NDX100');
    expect(u.customRaw).toBe('AAPL,MSFT');
    expect(u.minPriceRaw).toBe('10');
    expect(u.maxPriceRaw).toBe('500');

    const s = useScanStore.getState();
    // context.universe is what stockScan.ts / step-5-strategy actually read
    // for the Stocks scan request (not useUniverseStore) — must match the
    // profile's captured pick (NDX100), not the DOW30 it was mutated to
    // right before apply.
    expect(s.context?.universe).toBe('NDX100');
    expect(s.context?.direction).toBe('Bearish');
    expect(s.context?.horizonPreset).toBe('Position');
    expect(s.context?.holdMin).toBe(60);
    expect(s.context?.holdMax).toBe(185);
    expect(s.scanOverrides).toEqual({ weight_trend: 40, ema_required: false });
    expect(s.activeStrategy).toBe('pullback_ema');

    const p = useScanParamsStore.getState();
    expect(p.pullbackTolerancePct).toBe(0.12);
    expect(p.rsiOversold).toBe(25);

    // Applying any profile is a fresh setup — the prior scan's delta baseline
    // must not survive across a profile switch.
    expect(s.previousRun).toBeNull();
  });

  it('omits strategy/strategyParams entirely when no strategy has been picked this session', () => {
    useScanStore.setState({ activeStrategy: null });
    const captured = captureCurrentSnapshot('stocks');
    expect(captured.strategy).toBeUndefined();
    expect(captured.strategyParams).toBeUndefined();
  });

  it('clears a leftover activeStrategy when applying a strategy-less profile', () => {
    // Profile saved from Step 3 before ever visiting Step 5 — no strategy.
    useScanStore.setState({ activeStrategy: null });
    const captured = captureCurrentSnapshot('stocks');
    expect(captured.strategyParams).toBeUndefined();

    // A DIFFERENT session/candidate left a real strategy active.
    useScanStore.setState({ activeStrategy: 'breakout_base' });

    applySearchProfile({ ...captured, id: 'p4', name: 'no-strategy', createdAt: '', updatedAt: '' });

    // Must be reset to null, not left at the stale 'breakout_base' — a
    // leftover strategy here would silently run via RunScanButton's Stocks
    // path and could get baked into this profile on a later "Update".
    expect(useScanStore.getState().activeStrategy).toBeNull();
  });
});

describe('captureCurrentSnapshot — options mode', () => {
  it('never attaches strategy/strategyParams, even if activeStrategy happens to be set', () => {
    useScanStore.setState({ activeStrategy: 'pullback_ema' });
    const captured = captureCurrentSnapshot('options');
    expect(captured.strategy).toBeUndefined();
    expect(captured.strategyParams).toBeUndefined();
  });
});

describe('scanSettings mode-asymmetry', () => {
  it('captures and restores all four fields for an options profile', () => {
    useSettingsStore.setState({
      confidenceGate: { enabled: false, cautionBelow: 55, rejectBelow: 40, atrMult: DEFAULT_ATR_MULT_BY_HORIZON },
      fundamentalsGate: { enabled: false, cautionBelow: 60, rejectBelow: 50, deReject: 4.0 },
      shortlistMaxCandidates: 25,
      spreads: { shortLegDelta: 0.25, widthPoints: 10, ivRankThreshold: 60, minCredit: 1.0, maxDebitPctOfWidth: 50 },
    });
    const captured = captureCurrentSnapshot('options');
    expect(captured.scanSettings.fundamentalsGate?.cautionBelow).toBe(60);
    expect(captured.scanSettings.shortlistMaxCandidates).toBe(25);
    expect(captured.scanSettings.spreads?.widthPoints).toBe(10);

    resetStores();
    applySearchProfile({ ...captured, mode: 'options', id: 'p2', name: 'opt', createdAt: '', updatedAt: '' });

    const settings = useSettingsStore.getState();
    expect(settings.confidenceGate.cautionBelow).toBe(55);
    expect(settings.fundamentalsGate.cautionBelow).toBe(60);
    expect(settings.shortlistMaxCandidates).toBe(25);
    expect(settings.spreads.widthPoints).toBe(10);
  });

  it('captures only confidenceGate for a stocks profile, and applying it leaves the other three untouched', () => {
    useSettingsStore.setState({
      confidenceGate: { enabled: false, cautionBelow: 55, rejectBelow: 40, atrMult: DEFAULT_ATR_MULT_BY_HORIZON },
      fundamentalsGate: { enabled: false, cautionBelow: 60, rejectBelow: 50, deReject: 4.0 },
      shortlistMaxCandidates: 25,
      spreads: { shortLegDelta: 0.25, widthPoints: 10, ivRankThreshold: 60, minCredit: 1.0, maxDebitPctOfWidth: 50 },
    });
    const captured = captureCurrentSnapshot('stocks');
    expect(captured.scanSettings.confidenceGate.cautionBelow).toBe(55);
    expect(captured.scanSettings.fundamentalsGate).toBeUndefined();
    expect(captured.scanSettings.shortlistMaxCandidates).toBeUndefined();
    expect(captured.scanSettings.spreads).toBeUndefined();

    // Reset settingsStore to defaults, then apply — confidenceGate should be
    // restored to the captured (non-default) value, everything else must
    // stay at whatever it was left at (defaults here), untouched by a
    // Stocks-mode profile that has no bearing on them.
    useSettingsStore.setState({
      confidenceGate: { ...DEFAULT_CONFIDENCE_GATE },
      fundamentalsGate: { ...DEFAULT_FUNDAMENTALS_GATE },
      shortlistMaxCandidates: 10,
      spreads: { ...DEFAULT_SPREADS },
    });

    applySearchProfile({ ...captured, mode: 'stocks', id: 'p3', name: 'stk', createdAt: '', updatedAt: '' });

    const settings = useSettingsStore.getState();
    expect(settings.confidenceGate.cautionBelow).toBe(55);
    expect(settings.fundamentalsGate).toEqual(DEFAULT_FUNDAMENTALS_GATE);
    expect(settings.shortlistMaxCandidates).toBe(10);
    expect(settings.spreads).toEqual(DEFAULT_SPREADS);
  });
});

describe('stableStringify', () => {
  it('produces identical output for objects differing only in key order', () => {
    const a = { foo: 1, bar: { x: 1, y: 2 } };
    const b = { bar: { y: 2, x: 1 }, foo: 1 };
    expect(stableStringify(a)).toBe(stableStringify(b));
  });

  it('still distinguishes objects with genuinely different values', () => {
    const a = { foo: 1 };
    const b = { foo: 2 };
    expect(stableStringify(a)).not.toBe(stableStringify(b));
  });
});
