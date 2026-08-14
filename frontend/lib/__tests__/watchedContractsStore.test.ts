import { migrateWatchedContracts } from '@/lib/watchedContractsStore';

describe('watchedContractsStore — migrate (T4)', () => {
  it('v1 -> v2 is currently an identity passthrough (documented: no shape change)', () => {
    const state = { ids: ['AAPL|190|2026-05-15|C'] };
    expect(migrateWatchedContracts(state, 1)).toEqual(state);
  });

  it('v2 -> v2 is a passthrough', () => {
    const state = { ids: [] };
    expect(migrateWatchedContracts(state, 2)).toEqual(state);
  });
});
