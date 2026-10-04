import { useSearchProfilesStore } from '../searchProfilesStore';
const key = 'bamendjou:search-profiles';
describe('AREA3 target migration through actual hydration', () => {
  beforeEach(() => {
    localStorage.clear();
    useSearchProfilesStore.setState({ profiles: [], legacyTargetPctDropped: false });
  });
  it.each([1, 2, 3])('migrates v%i preserving other values and persisting dismissal', async (version) => {
    localStorage.setItem(key, JSON.stringify({ version, state: { profiles: [{
      id: 'saved', name: 'Saved', scanOverrides: {
        rr_bullish_target_pct: 0.12, rr_bearish_target_pct: 0.08,
        rr_bullish_invalidation_pct: 0.04, rr_target_r_multiple: 3, fast_ema: 11,
      },
    }] } }));
    await useSearchProfilesStore.persist.rehydrate();
    expect(useSearchProfilesStore.getState().profiles[0]).toMatchObject({
      id: 'saved', name: 'Saved', scanOverrides: { rr_bullish_invalidation_pct: 0.04, rr_target_r_multiple: 3, fast_ema: 11 },
    });
    const overrides = useSearchProfilesStore.getState().profiles[0].scanOverrides;
    expect(overrides).not.toHaveProperty('rr_bullish_target_pct');
    expect(overrides).not.toHaveProperty('rr_bearish_target_pct');
    expect(useSearchProfilesStore.getState().legacyTargetPctDropped).toBe(true);
    await useSearchProfilesStore.persist.rehydrate();
    expect(useSearchProfilesStore.getState().legacyTargetPctDropped).toBe(true);
    useSearchProfilesStore.getState().dismissLegacyTargetPctNotice();
    await useSearchProfilesStore.persist.rehydrate();
    expect(useSearchProfilesStore.getState().legacyTargetPctDropped).toBe(false);
    expect(JSON.parse(localStorage.getItem(key)!).version).toBe(4);
  });
  it('default percentages need no notice', async () => {
    localStorage.setItem(key, JSON.stringify({ version: 3, state: { profiles: [{ scanOverrides: { rr_bullish_target_pct: 0.08, rr_bearish_target_pct: 0.08 } }] } }));
    await useSearchProfilesStore.persist.rehydrate();
    expect(useSearchProfilesStore.getState().legacyTargetPctDropped).toBe(false);
  });
});
