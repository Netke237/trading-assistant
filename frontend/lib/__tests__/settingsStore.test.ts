import { useSettingsStore, migrateSettings } from '@/lib/settingsStore';

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
});
