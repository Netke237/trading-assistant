import { renderHook, act } from '@testing-library/react';
import { api } from '@/lib/api';
import { useConfigHealthStore, useConfigHealthView, sawPidReturn } from '@/lib/configHealthStore';
import { MAX_REPORT_AGE_MS, FETCH_TIMEOUT_MS } from '@/lib/configHealth';
import { CLEAN_REPORT, ERROR_REPORT, WARNING_REPORT } from '@/lib/testFixtures/configHealth';

jest.mock('@/lib/api', () => ({ api: { getConfigHealth: jest.fn() } }));
const getHealth = api.getConfigHealth as jest.Mock;

const INITIAL = useConfigHealthStore.getState();
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));

function deferred<T>() {
  let resolve!: (v: T) => void; let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

beforeEach(() => {
  useConfigHealthStore.setState({ ...INITIAL, now: Date.now() }, true);
  getHealth.mockReset();
});
afterEach(() => jest.useRealTimers());

const poll = () => useConfigHealthStore.getState().poll();
const st = () => useConfigHealthStore.getState();

describe('configHealthStore', () => {
  it('S1: a good poll is ready, parsed, pid recorded', async () => {
    getHealth.mockResolvedValue(clone(CLEAN_REPORT));
    await poll();
    expect(st().status).toBe('ready');
    expect(st().report).toEqual(CLEAN_REPORT);
    expect(st().pids).toEqual([4242]);
    expect(st().error).toBeNull();
  });

  it('S2: a rejection or a malformed payload fails and CLEARS the ready report', async () => {
    getHealth.mockResolvedValueOnce(clone(CLEAN_REPORT));
    await poll();
    getHealth.mockRejectedValueOnce(new Error('API /api/config/health → 500'));
    await poll();
    expect(st()).toMatchObject({ status: 'failed', report: null, fetchedAt: null });
    expect(st().error).toContain('500');

    getHealth.mockResolvedValueOnce(clone(CLEAN_REPORT));
    await poll();
    getHealth.mockResolvedValueOnce({ ...clone(CLEAN_REPORT), ok: false });
    await poll();
    expect(st()).toMatchObject({ status: 'failed', report: null });
    expect(st().error).toContain('contradicts');
    expect(st().pids).toEqual([4242, 4242]);
  });

  it('S3: only the latest poll writes, whatever the earlier one does', async () => {
    for (const aFails of [false, true]) {
      useConfigHealthStore.setState({ ...INITIAL }, true);
      const a = deferred<unknown>(); const b = deferred<unknown>();
      getHealth.mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise);
      const pa = poll(); const pb = poll();
      b.resolve(clone(ERROR_REPORT));
      await pb;
      if (aFails) a.reject(new Error('late failure')); else a.resolve(clone(CLEAN_REPORT));
      await pa;
      expect(st().report).toEqual(ERROR_REPORT);
      expect(st().status).toBe('ready');
    }
  });

  it('S4: no answer within 10 s fails with the abort message', async () => {
    jest.useFakeTimers();
    getHealth.mockImplementation((signal: AbortSignal) => new Promise((_, rej) => {
      signal.addEventListener('abort', () => rej(new Error('The operation was aborted.')));
    }));
    const p = poll();
    await act(async () => { jest.advanceTimersByTime(FETCH_TIMEOUT_MS); });
    await p;
    expect(st().status).toBe('failed');
    expect(st().error).toBe('no answer within 10 s');
  });

  it('S5: a restart is not multi-worker; a pid coming back is; it falls away', async () => {
    const withPid = (pid: number) => ({ ...clone(CLEAN_REPORT), pid });
    for (const pid of [1, 1, 2, 2]) { getHealth.mockResolvedValueOnce(withPid(pid)); await poll(); }
    expect(st().multiWorker).toBe(false);
    expect(st().restartedAt).not.toBeNull();

    useConfigHealthStore.setState({ ...INITIAL }, true);
    for (const pid of [1, 2, 1]) { getHealth.mockResolvedValueOnce(withPid(pid)); await poll(); }
    expect(st().multiWorker).toBe(true);
    for (let i = 0; i < 10; i++) { getHealth.mockResolvedValueOnce(withPid(2)); await poll(); }
    expect(st().multiWorker).toBe(false);
    expect(st().pids).toHaveLength(10);

    expect(sawPidReturn([1, 2, 3])).toBe(false);
    expect(sawPidReturn([1, 1, 2, 2, 1])).toBe(true);
  });

  it('S6: while loading after ready, the old report stays in hand', async () => {
    getHealth.mockResolvedValueOnce(clone(WARNING_REPORT));
    await poll();
    const d = deferred<unknown>();
    getHealth.mockReturnValueOnce(d.promise);
    const p = poll();
    expect(st().status).toBe('loading');
    expect(st().report).toEqual(WARNING_REPORT);
    d.resolve(clone(CLEAN_REPORT));
    await p;
  });

  it('S8: tick() ages a clean report into unknown; a poll after a failure keeps the error', async () => {
    jest.useFakeTimers({ now: 5_000_000 });
    getHealth.mockResolvedValueOnce(clone(CLEAN_REPORT));
    await poll();
    const { result } = renderHook(() => useConfigHealthView());
    expect(result.current.tier).toBe('clean');
    jest.setSystemTime(5_000_000 + MAX_REPORT_AGE_MS + 1);
    expect(result.current.tier).toBe('clean');     // no tick yet: the store clock has not moved
    act(() => st().tick());
    expect(result.current.tier).toBe('unknown');
    expect(result.current.unknownReason).toContain('older than 70 s');

    getHealth.mockRejectedValueOnce(new Error('down'));
    await act(async () => { await poll(); });
    getHealth.mockReturnValueOnce(new Promise(() => {}));
    act(() => { void poll(); });
    expect(st().status).toBe('loading');
    expect(st().error).toBe('down');
    expect(result.current.tier).toBe('unknown');
  });

  it('S7: collapse holds only for the collapsed fingerprint', async () => {
    getHealth.mockResolvedValueOnce(clone(WARNING_REPORT));
    await poll();
    const { result } = renderHook(() => useConfigHealthView());
    const fp = result.current.fingerprint;
    act(() => st().setCollapsed(true, fp));
    expect(result.current.collapsed).toBe(true);
    const changed = { ...clone(WARNING_REPORT),
      warnings: [{ ...WARNING_REPORT.warnings[0], message: 'something else' }] };
    getHealth.mockResolvedValueOnce(changed);
    await act(async () => { await poll(); });
    expect(result.current.collapsed).toBe(false);
  });
});
