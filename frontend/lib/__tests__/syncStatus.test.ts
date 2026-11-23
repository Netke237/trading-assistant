import { syncStatusView, positionsLoadState } from '../syncStatus';
import { hhmmss } from '../configHealth';

const T1 = new Date(2026, 10, 21, 17, 42, 10).getTime();
const T2 = new Date(2026, 10, 21, 17, 42, 40).getTime();

describe('syncStatusView', () => {
  it('syncing before any attempt finished', () => {
    expect(syncStatusView({ lastSyncAt: null, lastSyncFailedAt: null, firstSyncAt: null }))
      .toEqual({ kind: 'syncing', text: 'Syncing…' });
  });
  it('ok after a success', () => {
    const v = syncStatusView({ lastSyncAt: T1, lastSyncFailedAt: null, firstSyncAt: T1 });
    expect(v.kind).toBe('ok');
    expect(v.text).toBe(`Synced ${hhmmss(T1)} · refreshes every 30 s, paused while this tab is hidden`);
    expect(v.text).toContain('17:42:10');
  });
  it('failed with a prior success names the last success, not the failure', () => {
    const v = syncStatusView({ lastSyncAt: T1, lastSyncFailedAt: T2, firstSyncAt: T1 });
    expect(v.kind).toBe('failed-with-prior');
    expect(v.text).toBe('Last sync failed 17:42:40, showing 17:42:10');
  });
  it('failed with no prior success', () => {
    const v = syncStatusView({ lastSyncAt: null, lastSyncFailedAt: T2, firstSyncAt: null });
    expect(v.kind).toBe('failed-no-prior');
    expect(v.text).toBe('Last sync failed 17:42:40, showing positions saved in this browser');
  });
  it('a later success clears the failure', () => {
    const v = syncStatusView({ lastSyncAt: T2, lastSyncFailedAt: T1, firstSyncAt: T1 });
    expect(v.kind).toBe('ok');
    expect(v.text).not.toContain('failed');
  });
  it('failure at the same instant as the success is not a failure', () => {
    expect(syncStatusView({ lastSyncAt: T1, lastSyncFailedAt: T1, firstSyncAt: T1 }).kind).toBe('ok');
  });
});

describe('positionsLoadState', () => {
  it('rows present is always ready', () => {
    expect(positionsLoadState(3, null, null)).toBe('ready');
    expect(positionsLoadState(1, null, T2)).toBe('ready');
  });
  it('empty before any attempt is loading', () => {
    expect(positionsLoadState(0, null, null)).toBe('loading');
  });
  it('empty with only a failed attempt is failed', () => {
    expect(positionsLoadState(0, null, T2)).toBe('failed');
  });
  it('empty after a real success is empty', () => {
    expect(positionsLoadState(0, T1, null)).toBe('empty');
    expect(positionsLoadState(0, T1, T2)).toBe('empty');
  });
});
