import { useSettingsStore } from '@/lib/settingsStore';

// Reset store state before each test
beforeEach(() => {
  const initial = useSettingsStore.getInitialState?.() ?? {};
  useSettingsStore.setState(initial, true);
});

describe('settingsStore v9', () => {
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
