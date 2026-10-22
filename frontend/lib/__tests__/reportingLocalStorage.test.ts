import { reportingLocalStorage } from '../reportingLocalStorage';
import { outstanding, retryLocalWrites, useSettingsSaveStatus } from '../settingsSaveStatus';
import { useSettingsStore } from '../settingsStore';
import { useThemeStore } from '../theme';
import { useRiskStore } from '../riskStore';
import { useScanParamsStore } from '../scanParamsStore';

const stores = [
  { name: 'settings', key: 'bamendjou-settings', label: 'Settings (this browser)', version: 24,
    write: (value: number) => useSettingsStore.getState().setMaxContractsPerChain(value),
    read: () => useSettingsStore.getState().maxContractsPerChain, old: 13, next: 27, later: 39 },
  { name: 'theme', key: 'bamendjou:theme', label: 'Appearance (this browser)', version: 1,
    write: (value: string) => useThemeStore.getState().setTheme(value as 'dark' | 'light'),
    read: () => useThemeStore.getState().theme, old: 'dark', next: 'light', later: 'dark' },
  { name: 'risk', key: 'bamendjou-risk-v1', label: 'Risk limits (this browser)', version: 4,
    write: (value: number) => useRiskStore.getState().setLimits({ ...useRiskStore.getState().limits, portfolioValue: value }, { isUserEdit: false }),
    read: () => useRiskStore.getState().limits.portfolioValue, old: 123456, next: 234567, later: 345678 },
  { name: 'scan', key: 'bamendjou:scan-params', label: 'Strategy scan parameters (this browser)', version: 12,
    write: (value: number) => useScanParamsStore.getState().setParam('btMinTrades', value),
    read: () => useScanParamsStore.getState().btMinTrades, old: 11, next: 23, later: 37 },
];
beforeEach(() => { jest.restoreAllMocks(); localStorage.clear(); useSettingsSaveStatus.setState({ channels: {}, localFailures: {} }); });
afterEach(() => jest.restoreAllMocks());

// Each test's union member retains its correctly paired value and callback.
for (const fixture of stores) {
  const write = fixture.write as (value: number | string) => void;
  describe(fixture.name, () => {
    test.each(['QuotaExceededError', 'SecurityError'])('%s keeps old bytes, throws same error, reports new bytes and recovers on later write', (errorName) => {
      write(fixture.old);
      const oldBytes = localStorage.getItem(fixture.key);
      const error = new DOMException('Synthetic blocked storage', errorName);
      const spy = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw error; });
      let thrown: unknown; try { write(fixture.next); } catch (reason) { thrown = reason; }
      expect(thrown).toBe(error);
      expect(fixture.read()).toBe(fixture.next);
      expect(localStorage.getItem(fixture.key)).toBe(oldBytes);
      expect(outstanding()).toEqual([expect.objectContaining({ channel: fixture.key, label: fixture.label, kind: 'local' })]);
      const [key, pendingBytes] = spy.mock.calls[0];
      expect(key).toBe(fixture.key);
      expect(JSON.parse(pendingBytes).version).toBe(fixture.version);
      spy.mockRestore(); write(fixture.later);
      expect(outstanding()).toEqual([]);
      expect(JSON.parse(localStorage.getItem(fixture.key)!).version).toBe(fixture.version);
      expect(Object.keys(JSON.parse(localStorage.getItem(fixture.key)!).state).sort())
        .toEqual(Object.keys(JSON.parse(oldBytes!).state).sort());
      expect(fixture.read()).toBe(fixture.later);
    });
    test.each(['QuotaExceededError', 'SecurityError'])('%s retry writes exactly the latest failed serialized bytes and restores readback', async (errorName) => {
      write(fixture.old);
      const oldBytes = localStorage.getItem(fixture.key);
      const error = new DOMException('Synthetic blocked storage', errorName);
      const spy = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw error; });
      expect(() => write(fixture.next)).toThrow(error);
      expect(() => write(fixture.later)).toThrow(error);
      const latestBytes = spy.mock.calls[1][1];
      retryLocalWrites(); // still blocked, must retain failure and old bytes
      expect(outstanding()).toHaveLength(1);
      expect(localStorage.getItem(fixture.key)).toBe(oldBytes);
      spy.mockRestore(); retryLocalWrites();
      expect(localStorage.getItem(fixture.key)).toBe(latestBytes);
      expect(JSON.parse(latestBytes).version).toBe(fixture.version);
      expect(Object.keys(JSON.parse(latestBytes)).sort()).toEqual(['state', 'version']);
      expect(outstanding()).toEqual([]);
      write(fixture.old);
      localStorage.setItem(fixture.key, latestBytes);
      const store = [useSettingsStore, useThemeStore, useRiskStore, useScanParamsStore][stores.indexOf(fixture)];
      await store.persist.rehydrate();
      expect(fixture.read()).toBe(fixture.later);
    });
  });
}

test('Storage interface passes through reads, enumeration and removals; errors preserve identity', () => {
  const storage = reportingLocalStorage('Synthetic browser settings');
  storage.setItem('synthetic', '{"independent":73}');
  expect(storage.getItem('synthetic')).toBe('{"independent":73}');
  expect(storage.length).toBe(1); expect(storage.key(0)).toBe('synthetic');
  storage.removeItem('synthetic'); expect(storage.getItem('synthetic')).toBeNull();
  storage.setItem('synthetic', '79'); storage.clear(); expect(storage.length).toBe(0);
  const error = new DOMException('blocked', 'SecurityError');
  jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw error; });
  expect(() => storage.getItem('synthetic')).toThrow(error);
});

const persistedKeys: Record<string, string[]> = {
  settings: ['broker', 'alertDeduplicationHours', 'markov', 'shortlistMaxCandidates', 'maxContractsPerChain', 'maxContractPrice', 'premiumStopPct', 'targetProfitPct', 'confidenceGate', 'fundamentalsGate', 'ibkrPaper', 'tradierPaper', 'tradierLive', 'alpacaPaper', 'tastytradePaper', 'spreads', 'scheduleConfig'],
  theme: ['theme', 'density'],
  risk: ['limits', 'dailyRecommendations', 'lastResetDate', 'symbols', 'portfolioValueUpdatedAt'],
  scan: ['pullbackTolerancePct', 'pullbackEmaPeriod', 'pullbackTrendEma', 'pullbackMaType', 'maCrossoverFast', 'maCrossoverSlow', 'maCrossoverLookback', 'breakoutVolumeMult', 'rsiPeriod', 'rsiOversold', 'rsiOverbought', 'rsiTrendSma', 'requireChoppyRegime', 'meanReversionVariants', 'meanReversionMinConfirm', 'vwapLookback', 'vwapDeviationPct', 'btMinTrades', 'btMinWinRate', 'eventFilter', 'stockShortlistMax'],
};
test.each(stores)('$name retains the original key, version and persisted field set', (fixture) => {
  (fixture.write as (value: number | string) => void)(fixture.next);
  expect(localStorage.length).toBe(1);
  expect(localStorage.key(0)).toBe(fixture.key);
  const parsed = JSON.parse(localStorage.getItem(fixture.key)!);
  expect(Object.keys(parsed)).toEqual(['state', 'version']);
  expect(parsed.version).toBe(fixture.version);
  expect(Object.keys(parsed.state)).toEqual(persistedKeys[fixture.name]);
});
