import { useSettingsStore, migrateSettings, DEFAULT_CONFIDENCE_GATE, DEFAULT_IBKR_PAPER, DEFAULT_TRADIER_PAPER } from '@/lib/settingsStore';

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
    const result = migrateSettings({ ivPassThreshold: 30 }, 8) as unknown as Record<string, unknown>;
    // Fields added in v9 and v10 must all be present, not just the v9 ones.
    expect(result.maxContractsPerChain).toBe(10);
    expect(result.maxContractPrice).toBe(50);
    expect(result.premiumStopPct).toBe(0.60);
    // Existing persisted values are preserved.
    expect(result.ivPassThreshold).toBe(30);
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

  it('migrating from v11 adds atrMult to an existing gate', () => {
    const result = migrateSettings(
      { confidenceGate: { enabled: true, cautionBelow: 60, rejectBelow: 40 } },
      11,
    ) as unknown as Record<string, unknown>;
    const gate = result.confidenceGate as Record<string, unknown>;
    expect(gate.atrMult).toBe(1.5);
    expect(gate.cautionBelow).toBe(60); // existing value preserved
  });
});

describe('settingsStore — confidenceGate', () => {
  it('defaults to enabled 50/35 with ATR 1.5', () => {
    expect(useSettingsStore.getState().confidenceGate).toEqual({
      enabled: true, cautionBelow: 50, rejectBelow: 35, atrMult: 1.5,
    });
  });

  it('setConfidenceGate updates the value', () => {
    useSettingsStore.getState().setConfidenceGate({ enabled: true, cautionBelow: 60, rejectBelow: 40, atrMult: 2.0 });
    expect(useSettingsStore.getState().confidenceGate.cautionBelow).toBe(60);
    expect(useSettingsStore.getState().confidenceGate.atrMult).toBe(2.0);
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
