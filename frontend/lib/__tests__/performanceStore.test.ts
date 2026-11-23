import { usePerformanceStore } from '../performanceStore';

const jsonRes = (body: unknown, ok = true) =>
  ({ ok, status: ok ? 200 : 500, json: async () => body }) as unknown as Response;

const PERF = {
  realizedToday: 1, realizedWeek: 2, realizedMonth: 3, realizedYear: 4,
  realizedCurve: [], equityCurve: [{ date: '2026-10-23', value: 5 }], openPnlCurve: [{ date: '2026-10-23', value: 1530 }],
};

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

describe('performanceStore sync-state fields', () => {
  const originalFetch = global.fetch;
  beforeEach(() => {
    usePerformanceStore.setState({
      performance: {
        realizedToday: 0, realizedWeek: 0, realizedMonth: 0, realizedYear: 0,
        realizedCurve: [], equityCurve: [], openPnlCurve: [],
        lastSnapshotDate: null, snapshotSkippedOn: null, snapshotSkippedContracts: [],
      },
      fetchedAt: null,
    });
  });
  afterEach(() => { global.fetch = originalFetch; jest.restoreAllMocks(); });

  it('initial state has the new fields defaulted', () => {
    const s = usePerformanceStore.getState();
    expect(s.fetchedAt).toBeNull();
    expect(s.performance.lastSnapshotDate).toBeNull();
    expect(s.performance.snapshotSkippedOn).toBeNull();
    expect(s.performance.snapshotSkippedContracts).toEqual([]);
  });

  it('stores the three backend fields', async () => {
    global.fetch = jest.fn().mockResolvedValue(jsonRes({
      ...PERF, lastSnapshotDate: '2026-10-23', snapshotSkippedOn: '2026-11-17',
      snapshotSkippedContracts: ['BMY|67|2027-03-19|C'],
    })) as unknown as typeof fetch;
    await usePerformanceStore.getState().fetchPerformance();
    const p = usePerformanceStore.getState().performance;
    expect(p.lastSnapshotDate).toBe('2026-10-23');
    expect(p.snapshotSkippedOn).toBe('2026-11-17');
    expect(p.snapshotSkippedContracts).toEqual(['BMY|67|2027-03-19|C']);
  });

  it('absent fields default', async () => {
    global.fetch = jest.fn().mockResolvedValue(jsonRes(PERF)) as unknown as typeof fetch;
    await usePerformanceStore.getState().fetchPerformance();
    const p = usePerformanceStore.getState().performance;
    expect(p.lastSnapshotDate).toBeNull();
    expect(p.snapshotSkippedOn).toBeNull();
    expect(p.snapshotSkippedContracts).toEqual([]);
    expect(p.openPnlCurve).toHaveLength(1);
  });

  it('fetchedAt is the time the request was ISSUED, set only on ok', async () => {
    const d = deferred<Response>();
    global.fetch = jest.fn().mockReturnValue(d.promise) as unknown as typeof fetch;
    const now = jest.spyOn(Date, 'now');
    now.mockReturnValue(1_000);
    const p = usePerformanceStore.getState().fetchPerformance();
    now.mockReturnValue(9_000);
    d.resolve(jsonRes(PERF));
    await p;
    expect(usePerformanceStore.getState().fetchedAt).toBe(1_000);
  });

  it('fetchedAt and performance are unchanged on a failed or thrown fetch', async () => {
    global.fetch = jest.fn().mockResolvedValue(jsonRes(PERF)) as unknown as typeof fetch;
    jest.spyOn(Date, 'now').mockReturnValue(1_000);
    await usePerformanceStore.getState().fetchPerformance();
    global.fetch = jest.fn().mockResolvedValue(jsonRes({}, false)) as unknown as typeof fetch;
    jest.spyOn(Date, 'now').mockReturnValue(2_000);
    await usePerformanceStore.getState().fetchPerformance();
    global.fetch = jest.fn().mockRejectedValue(new Error('offline')) as unknown as typeof fetch;
    await usePerformanceStore.getState().fetchPerformance();
    expect(usePerformanceStore.getState().fetchedAt).toBe(1_000);
    expect(usePerformanceStore.getState().performance.realizedToday).toBe(1);
  });

  it('a request issued before the first sync but resolved after leaves ready false', async () => {
    const { usePortfolioStore } = await import('../portfolioStore');
    usePortfolioStore.setState({ positions: [], lastSyncAt: null, lastSyncFailedAt: null, firstSyncAt: null });
    const d = deferred<Response>();
    const now = jest.spyOn(Date, 'now');
    now.mockReturnValue(1_000);
    global.fetch = jest.fn().mockReturnValueOnce(d.promise) as unknown as typeof fetch;
    const perf = usePerformanceStore.getState().fetchPerformance(); // issued at 1000
    now.mockReturnValue(2_000);
    global.fetch = jest.fn().mockResolvedValue(jsonRes([])) as unknown as typeof fetch;
    await usePortfolioStore.getState().syncFromBackend(true);      // first sync at 2000
    now.mockReturnValue(3_000);
    d.resolve(jsonRes(PERF));
    await perf;
    const { firstSyncAt } = usePortfolioStore.getState();
    const { fetchedAt } = usePerformanceStore.getState();
    expect(firstSyncAt).toBe(2_000);
    expect(fetchedAt).toBe(1_000);
    expect(fetchedAt! >= firstSyncAt!).toBe(false);
  });

  it('an older-issued response resolving after a newer one does not overwrite it', async () => {
    const older = deferred<Response>();
    const newer = deferred<Response>();
    const now = jest.spyOn(Date, 'now');
    global.fetch = jest.fn().mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise) as unknown as typeof fetch;
    now.mockReturnValue(1_000);
    const p1 = usePerformanceStore.getState().fetchPerformance();
    now.mockReturnValue(2_000);
    const p2 = usePerformanceStore.getState().fetchPerformance();
    newer.resolve(jsonRes({ ...PERF, realizedToday: 22 }));
    await p2;
    older.resolve(jsonRes({ ...PERF, realizedToday: 11 }));
    await p1;
    expect(usePerformanceStore.getState().performance.realizedToday).toBe(22);
    expect(usePerformanceStore.getState().fetchedAt).toBe(2_000);
  });

  it('clearAllHistory resets to the empty performance with the new fields', async () => {
    global.fetch = jest.fn().mockResolvedValue(jsonRes({ ...PERF, lastSnapshotDate: '2026-10-23' })) as unknown as typeof fetch;
    await usePerformanceStore.getState().fetchPerformance();
    global.fetch = jest.fn().mockResolvedValue({ ok: true, status: 204, json: async () => ({}) }) as unknown as typeof fetch;
    await usePerformanceStore.getState().clearAllHistory();
    const p = usePerformanceStore.getState().performance;
    expect(p.lastSnapshotDate).toBeNull();
    expect(p.snapshotSkippedContracts).toEqual([]);
  });
});
