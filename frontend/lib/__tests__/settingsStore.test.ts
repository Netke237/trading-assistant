import { act } from '@testing-library/react';
import { useSettingsStore, migrateSettings, clampGateThresholds, atrMultForHorizon, SETTINGS_STORAGE_KEY, DEFAULT_CONFIDENCE_GATE, DEFAULT_ATR_MULT_BY_HORIZON, DEFAULT_IBKR_PAPER, DEFAULT_TRADIER_PAPER, DEFAULT_TASTYTRADE_PAPER, DEFAULT_TASTYTRADE_LIVE, DEFAULT_TARGET_PROFIT_PCT } from '@/lib/settingsStore';

// Reset store state before each test
beforeEach(() => {
  const initial = useSettingsStore.getInitialState?.() ?? {};
  useSettingsStore.setState(initial, true);
});

describe('settingsStore', () => {
  it('has correct defaults', () => {
    const state = useSettingsStore.getState();
    expect(state.maxContractsPerChain).toBe(10);
    expect(state.maxContractPrice).toBe(50);
  });

  it('setMaxContractsPerChain updates state', () => {
    useSettingsStore.getState().setMaxContractsPerChain(25);
    expect(useSettingsStore.getState().maxContractsPerChain).toBe(25);
  });

  it('setMaxContractPrice updates state', () => {
    useSettingsStore.getState().setMaxContractPrice(20);
    expect(useSettingsStore.getState().maxContractPrice).toBe(20);
  });
});

describe('settingsStore — premiumStopPct', () => {
  it('defaults to 0.60', () => {
    const state = useSettingsStore.getState();
    expect(state.premiumStopPct).toBe(0.60);
  });

  it('setPremiumStopPct updates the value', () => {
    useSettingsStore.getState().setPremiumStopPct(0.50);
    expect(useSettingsStore.getState().premiumStopPct).toBe(0.50);
  });
});

describe('settingsStore — migrate is cumulative', () => {
  it('migrating from v8 includes every field added after v8', () => {
    const result = migrateSettings({}, 8) as unknown as Record<string, unknown>;
    // Fields added in v9 and v10 must all be present, not just the v9 ones.
    expect(result.maxContractsPerChain).toBe(10);
    expect(result.maxContractPrice).toBe(50);
    expect(result.premiumStopPct).toBe(0.60);
  });

  it('migrating from v6 resets markov and adds all later fields', () => {
    const result = migrateSettings({}, 6) as unknown as Record<string, unknown>;
    expect(result.shortlistMaxCandidates).toBe(10);
    expect(result.maxContractsPerChain).toBe(10);
    expect(result.premiumStopPct).toBe(0.60);
  });

  it('migrating from v10 injects the confidenceGate default', () => {
    const result = migrateSettings({}, 10) as unknown as Record<string, unknown>;
    expect(result.confidenceGate).toEqual(DEFAULT_CONFIDENCE_GATE);
  });

  it('migrating from v22 restructures a legacy numeric atrMult into per-horizon pairs', () => {
    const result = migrateSettings(
      { confidenceGate: { enabled: true, cautionBelow: 60, rejectBelow: 40, atrMult: 2.0 } },
      21,
    ) as unknown as Record<string, unknown>;
    const gate = result.confidenceGate as Record<string, unknown>;
    expect(gate.atrMult).toEqual(DEFAULT_ATR_MULT_BY_HORIZON);
    expect(gate.cautionBelow).toBe(60); // existing value preserved
    expect(gate.rejectBelow).toBe(40);
  });

  it('migrating from v22 leaves an already-nested atrMult untouched', () => {
    const nested = { intraday: { target: 1.0, stop: 1.0 }, swing: { target: 1.0, stop: 1.0 }, position: { target: 1.0, stop: 1.0 } };
    const result = migrateSettings(
      { confidenceGate: { enabled: true, cautionBelow: 60, rejectBelow: 40, atrMult: nested } },
      21,
    ) as unknown as Record<string, unknown>;
    const gate = result.confidenceGate as Record<string, unknown>;
    expect(gate.atrMult).toEqual(nested);
  });
});

describe('settingsStore — confidenceGate', () => {
  it('defaults to enabled 50/35 with per-horizon ATR pairs', () => {
    expect(useSettingsStore.getState().confidenceGate).toEqual({
      enabled: true, cautionBelow: 50, rejectBelow: 35, atrMult: DEFAULT_ATR_MULT_BY_HORIZON,
    });
  });

  it('setConfidenceGate updates the value', () => {
    useSettingsStore.getState().setConfidenceGate({
      enabled: true, cautionBelow: 60, rejectBelow: 40, atrMult: DEFAULT_ATR_MULT_BY_HORIZON,
    });
    expect(useSettingsStore.getState().confidenceGate.cautionBelow).toBe(60);
    expect(useSettingsStore.getState().confidenceGate.rejectBelow).toBe(40);
  });
});

describe('settingsStore — real rehydration through zustand persist (not migrateSettings() called directly)', () => {
  afterEach(() => {
    localStorage.removeItem(SETTINGS_STORAGE_KEY);
  });

  it('recovers a missing atrMult on a store already persisted at the current version', async () => {
    // Regression: an earlier build shipped `version: 22` and deleted atrMult
    // entirely rather than nesting it. zustand's persist middleware only runs
    // migrate() when the persisted version differs from the current version —
    // gating this fix on `version < 22` (matching that old build's number)
    // would make persist() skip migrate() outright for a store already at 22,
    // leaving confidenceGate.atrMult permanently undefined and crashing every
    // reader. This seeds exactly that broken localStorage shape and rehydrates
    // through the real persist/migrate machinery, not a direct migrateSettings() call.
    localStorage.setItem(
      SETTINGS_STORAGE_KEY,
      JSON.stringify({
        version: 22,
        state: {
          confidenceGate: { enabled: true, cautionBelow: 55, rejectBelow: 40 },
        },
      }),
    );

    await act(async () => {
      await useSettingsStore.persist.rehydrate();
    });

    const gate = useSettingsStore.getState().confidenceGate;
    expect(gate.atrMult).toEqual(DEFAULT_ATR_MULT_BY_HORIZON);
    expect(gate.cautionBelow).toBe(55); // existing value preserved
    expect(gate.rejectBelow).toBe(40);
  });
});

describe('atrMultForHorizon', () => {
  it('resolves intraday/swing/position by first word, case-insensitively', () => {
    expect(atrMultForHorizon(DEFAULT_CONFIDENCE_GATE, 'Intraday')).toEqual({ target: 2.0, stop: 1.5 });
    expect(atrMultForHorizon(DEFAULT_CONFIDENCE_GATE, 'swing')).toEqual({ target: 3.0, stop: 1.5 });
    expect(atrMultForHorizon(DEFAULT_CONFIDENCE_GATE, 'Position (15-45d)')).toEqual({ target: 2.5, stop: 1.5 });
  });

  it('falls back to swing for an unrecognized horizon', () => {
    expect(atrMultForHorizon(DEFAULT_CONFIDENCE_GATE, 'Quarterly')).toEqual({ target: 3.0, stop: 1.5 });
  });
});

describe('clampGateThresholds', () => {
  it('normal edit: caution still above reject leaves reject untouched', () => {
    const result = clampGateThresholds('cautionBelow', 60, 35);
    expect(result).toEqual({ cautionBelow: 60, rejectBelow: 35 });
  });

  it('normal edit: reject still below caution leaves caution untouched', () => {
    const result = clampGateThresholds('rejectBelow', 40, 60);
    expect(result).toEqual({ cautionBelow: 60, rejectBelow: 40 });
  });

  it('backwards edit: caution dropped below current reject pulls reject down to match', () => {
    const result = clampGateThresholds('cautionBelow', 10, 35);
    expect(result).toEqual({ cautionBelow: 10, rejectBelow: 10 });
  });

  it('backwards edit: reject raised above current caution pulls caution up to match', () => {
    const result = clampGateThresholds('rejectBelow', 80, 50);
    expect(result).toEqual({ cautionBelow: 80, rejectBelow: 80 });
  });

  it('clamps out-of-range values to [0,100] in combination with the ordering fix', () => {
    expect(clampGateThresholds('cautionBelow', 150, 35)).toEqual({ cautionBelow: 100, rejectBelow: 35 });
    expect(clampGateThresholds('rejectBelow', -20, 50)).toEqual({ cautionBelow: 50, rejectBelow: 0 });
  });
});

describe('settingsStore — broker accounts', () => {
  it('has ibkrPaper and tradierPaper defaults', () => {
    const s = useSettingsStore.getState();
    expect(s.ibkrPaper.baseUrl).toBe('https://localhost:7499/v1/api');
    expect(s.tradierPaper.accountId).toBe('');
    expect(s.ibkrLive.enabled).toBe(false);
  });

  it('setIbkrPaper updates the config', () => {
    const s = useSettingsStore.getState();
    s.setIbkrPaper({ ...s.ibkrPaper, accountId: 'DU999' });
    expect(useSettingsStore.getState().ibkrPaper.accountId).toBe('DU999');
  });
});

describe('settingsStore — tastytrade', () => {
  it('has tastytradePaper and tastytradeLive defaults', () => {
    const s = useSettingsStore.getState();
    expect(s.tastytradePaper).toEqual(DEFAULT_TASTYTRADE_PAPER);
    expect(s.tastytradeLive).toEqual(DEFAULT_TASTYTRADE_LIVE);
    expect(s.tastytradeLive.enabled).toBe(false);
  });

  it('setTastytradePaper updates the config', () => {
    const s = useSettingsStore.getState();
    s.setTastytradePaper({ ...s.tastytradePaper, accountId: '5WX12345' });
    expect(useSettingsStore.getState().tastytradePaper.accountId).toBe('5WX12345');
  });

  it('migrating from v19 injects tastytrade defaults', () => {
    const result = migrateSettings({}, 19) as unknown as Record<string, unknown>;
    expect(result.tastytradePaper).toEqual(DEFAULT_TASTYTRADE_PAPER);
    expect(result.tastytradeLive).toEqual(DEFAULT_TASTYTRADE_LIVE);
  });
});

describe('settingsStore — targetProfitPct', () => {
  it('defaults to 20/35/50', () => {
    expect(useSettingsStore.getState().targetProfitPct).toEqual(DEFAULT_TARGET_PROFIT_PCT);
  });

  it('setTargetProfitPct updates the value', () => {
    useSettingsStore.getState().setTargetProfitPct({ t1: 0.15, t2: 0.30, t3: 0.45 });
    expect(useSettingsStore.getState().targetProfitPct).toEqual({ t1: 0.15, t2: 0.30, t3: 0.45 });
  });

  it('migrating from v20 injects targetProfitPct defaults', () => {
    const result = migrateSettings({}, 20) as unknown as Record<string, unknown>;
    expect(result.targetProfitPct).toEqual(DEFAULT_TARGET_PROFIT_PCT);
  });
});
