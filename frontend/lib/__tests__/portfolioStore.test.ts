import { renderHook, act } from '@testing-library/react';
import { usePortfolioStore, persistPosition, migratePortfolioPersist } from '@/lib/portfolioStore';
import { useRiskStore } from '@/lib/riskStore';
import type { PortfolioPosition } from '@/types/domain';

const makeBackendPosition = () => ({
  id: 'p1',
  recId: 'REC-BACKEND',
  symbol: 'KDP',
  contract: 'KDP|33|2026-08-21|C',
  direction: 'Bullish',
  entryPrice: 2.1,
  qty: 1,
  entryDate: '2026-07-01',
  stop: null,
  targets: [],
  dteTotal: 42,
  createdAt: '2026-07-01T00:00:00Z',
});

function jsonResponse(body: unknown, ok = true, status = 200) {
  return { ok, status, json: async () => body } as unknown as Response;
}

let _recIdCounter = 0;
const makePosition = (overrides: Partial<PortfolioPosition> = {}): PortfolioPosition => ({
  symbol: 'AAPL',
  contract: 'AAPL 190C 05/16',
  direction: 'Bullish',
  entryDate: '2026-04-08',
  expiry: '2026-05-16',
  dteRemaining: 28,
  dteTotal: 38,
  entryPrice: 4.15,
  currentPrice: 5.02,
  pnlDollar: 870,
  pnlPct: 20.96,
  stop: 180.0,
  targets: [{ id: 'tp1', stockPrice: 198.0, contractsToSell: 2, status: 'PENDING' }],
  status: 'PASS',
  contracts: 2,
  recId: `REC-TEST-${++_recIdCounter}`,
  ...overrides,
});

describe('portfolioStore', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    // Async addPosition now POSTs to the backend; give every test a benign mock
    // so no real network call fires. Tests that assert on the response set their
    // own fetch mock inside the test body (which overrides this).
    (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
      .mockResolvedValue({ ok: true, status: 201, json: async () => ({}) });
    useRiskStore.setState({
      limits: {
        maxSingleTradeExposurePct: 0.05, maxTotalExposurePct: 0.25,
        maxConcurrentPositions: 10, maxDailyRecommendations: 5, portfolioValue: 50000,
      },
    } as never);
    act(() => {
      usePortfolioStore.setState({ positions: [], lastSyncError: null });
    });
  });

  afterEach(() => {
    global.fetch = originalFetch;
    localStorage.clear();
  });

  it('starts empty', () => {
    const { result } = renderHook(() => usePortfolioStore());
    expect(result.current.positions).toEqual([]);
  });

  it('hydrates positions', () => {
    const { result } = renderHook(() => usePortfolioStore());
    const positions = [makePosition(), makePosition({ symbol: 'MSFT', contract: 'MSFT 420C 06/20' })];

    act(() => {
      result.current.hydrate(positions);
    });
    expect(result.current.positions).toHaveLength(2);
  });

  it('adds a new position', async () => {
    const { result } = renderHook(() => usePortfolioStore());

    await act(async () => {
      await result.current.addPosition(makePosition());
    });
    expect(result.current.positions).toHaveLength(1);
    expect(result.current.positions[0].symbol).toBe('AAPL');
  });

  it('merges duplicate contracts by adding contract counts', async () => {
    const { result } = renderHook(() => usePortfolioStore());

    await act(async () => {
      await result.current.addPosition(makePosition({ contracts: 2 }));
    });
    expect(result.current.positions[0].contracts).toBe(2);

    await act(async () => {
      await result.current.addPosition(makePosition({ contracts: 3 }));
    });
    expect(result.current.positions).toHaveLength(1);
    expect(result.current.positions[0].contracts).toBe(5);
  });

  it('keeps earlier entry data when merging duplicates', async () => {
    const { result } = renderHook(() => usePortfolioStore());

    await act(async () => {
      await result.current.addPosition(makePosition({ entryPrice: 4.15, currentPrice: 5.02 }));
    });

    await act(async () => {
      await result.current.addPosition(makePosition({ entryPrice: 4.50, currentPrice: 5.50 }));
    });

    expect(result.current.positions[0].entryPrice).toBe(4.15);
    expect(result.current.positions[0].currentPrice).toBe(5.02);
  });

  it('updates a position by contract', async () => {
    const { result } = renderHook(() => usePortfolioStore());

    await act(async () => {
      await result.current.addPosition(makePosition());
    });

    act(() => {
      result.current.updatePosition('AAPL 190C 05/16', { currentPrice: 6.0, pnlDollar: 1200 });
    });

    expect(result.current.positions[0].currentPrice).toBe(6.0);
    expect(result.current.positions[0].pnlDollar).toBe(1200);
    expect(result.current.positions[0].symbol).toBe('AAPL');
  });

  it('closes a position by contract', async () => {
    const { result } = renderHook(() => usePortfolioStore());

    await act(async () => {
      await result.current.addPosition(makePosition());
      await result.current.addPosition(makePosition({ symbol: 'MSFT', contract: 'MSFT 420C 06/20' }));
    });
    expect(result.current.positions).toHaveLength(2);

    act(() => {
      result.current.closePosition('AAPL 190C 05/16');
    });
    expect(result.current.positions).toHaveLength(1);
    expect(result.current.positions[0].symbol).toBe('MSFT');
  });

  // The backend rejects a second position on the same contract with a 409, so
  // `contract` is the identity of a position. These guard that invariant against
  // the three paths that used to break it.
  it('merges a re-add of the same contract even when entryDate differs', async () => {
    const { result } = renderHook(() => usePortfolioStore());

    await act(async () => {
      await result.current.addPosition(makePosition({ entryDate: '2026-04-08', entryPrice: 4.15, contracts: 2 }));
    });
    await act(async () => {
      await result.current.addPosition(makePosition({ entryDate: '2026-04-09', entryPrice: 6.0, contracts: 3 }));
    });

    expect(result.current.positions).toHaveLength(1);
    expect(result.current.positions[0].contracts).toBe(5);
    // Cost basis stays at the original fill — the backend 409s the second POST
    // and keeps the first, so averaging here would diverge from the server.
    expect(result.current.positions[0].entryPrice).toBe(4.15);
    expect(result.current.positions[0].entryDate).toBe('2026-04-08');
  });

  it('does not merge different contracts on the same symbol', async () => {
    const { result } = renderHook(() => usePortfolioStore());

    await act(async () => {
      await result.current.addPosition(makePosition({ contract: 'AAPL 190C 05/16' }));
      await result.current.addPosition(makePosition({ contract: 'AAPL 200C 05/16' }));
    });

    expect(result.current.positions).toHaveLength(2);
  });

  it('does not keep a local position whose contract already exists on the backend', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => [makeBackendPosition()],
    }) as unknown as typeof fetch;

    act(() => {
      usePortfolioStore.setState({
        positions: [
          makePosition({
            symbol: 'KDP',
            contract: 'KDP|33|2026-08-21|C',
            entryDate: '2026-07-02',
            recId: 'REC-LOCAL-PHANTOM',
          }),
        ],
      });
    });

    await act(async () => {
      await usePortfolioStore.getState().syncFromBackend();
    });

    expect(usePortfolioStore.getState().positions).toHaveLength(1);
    expect(usePortfolioStore.getState().positions[0].recId).toBe('REC-BACKEND');
  });

  it('keeps an in-flight (pending) local position for a contract the backend has not seen', async () => {
    // The retry POST inside syncFromBackend and the GET both hit this mock; ok:true
    // makes the retry "succeed", so the pending row is promoted to synced and kept.
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => [makeBackendPosition()],
    }) as unknown as typeof fetch;

    act(() => {
      usePortfolioStore.setState({
        positions: [makePosition({
          symbol: 'MSFT', contract: 'MSFT 420C 06/20', recId: 'REC-INFLIGHT',
          syncStatus: 'pending', syncPendingSince: Date.now(),
        })],
      });
    });

    await act(async () => {
      await usePortfolioStore.getState().syncFromBackend();
    });

    const recIds = usePortfolioStore.getState().positions.map((p) => p.recId);
    expect(recIds).toEqual(['REC-BACKEND', 'REC-INFLIGHT']);
  });

  it('collapses same-contract duplicates already in localStorage on rehydrate', async () => {
    localStorage.setItem(
      'bamendjou-portfolio-v1',
      JSON.stringify({
        version: 0,
        state: {
          positions: [
            makePosition({ symbol: 'KDP', contract: 'KDP|33|2026-08-21|C', recId: 'REC-A', entryDate: '2026-07-01' }),
            makePosition({ symbol: 'KDP', contract: 'KDP|33|2026-08-21|C', recId: 'REC-B', entryDate: '2026-07-02' }),
          ],
        },
      }),
    );

    await act(async () => {
      await usePortfolioStore.persist.rehydrate();
    });

    const positions = usePortfolioStore.getState().positions;
    expect(positions).toHaveLength(1);
    // The earliest row is the one the backend accepted on first POST.
    expect(positions[0].recId).toBe('REC-A');
  });

  it('reports a 409 as a rejection so a re-entry is not counted as saved', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({ detail: "Position with contract 'KDP|33|2026-08-21|C' already exists." }),
    }) as unknown as typeof fetch;

    const res = await persistPosition(makePosition({ contract: 'KDP|33|2026-08-21|C' }));

    expect(res.ok).toBe(false);
    expect(res.detail).toContain('already exists');
  });

  describe('closePositionRemote', () => {
    it('closes cleanly when the recId matches on the backend (no drift)', async () => {
      const pos = makePosition({ recId: 'REC-1', contracts: 1 });
      act(() => { usePortfolioStore.setState({ positions: [pos] }); });

      global.fetch = jest.fn((url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET';
        if (url.includes('/close') && method === 'POST') {
          return Promise.resolve(jsonResponse({ id: 'x' }, true, 201));
        }
        if (url.endsWith('/api/portfolio') && method === 'GET') {
          return Promise.resolve(jsonResponse([], true, 200));   // fully closed remotely
        }
        return Promise.resolve(jsonResponse({}, false, 500));
      }) as unknown as typeof fetch;

      const res = await usePortfolioStore.getState().closePositionRemote(
        'REC-1', { qtyToClose: null, exitPrice: 5, exitDate: '2026-07-15' },
      );

      expect(res.ok).toBe(true);
      expect(usePortfolioStore.getState().positions).toHaveLength(0);
    });

    it('drops a genuinely-gone position and reports why, without touching other positions', async () => {
      const gone = makePosition({ recId: 'REC-GONE', contract: 'GONE|1|2026-01-01|C', contracts: 1 });
      const other = makePosition({ recId: 'REC-OTHER', symbol: 'MSFT', contract: 'MSFT|1|2026-01-01|C', contracts: 1 });
      act(() => { usePortfolioStore.setState({ positions: [gone, other] }); });

      global.fetch = jest.fn((url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET';
        if (url.includes('/close') && method === 'POST') {
          return Promise.resolve(jsonResponse({ detail: 'not found' }, false, 404));
        }
        if (url.endsWith('/api/portfolio') && method === 'POST') {
          return Promise.resolve(jsonResponse({ detail: 'nope' }, false, 422));   // re-persist fails
        }
        if (url.endsWith('/api/portfolio') && method === 'GET') {
          return Promise.resolve(jsonResponse([], true, 200));   // backend confirms: no such contract
        }
        return Promise.resolve(jsonResponse({}, false, 500));
      }) as unknown as typeof fetch;

      const res = await usePortfolioStore.getState().closePositionRemote(
        'REC-GONE', { qtyToClose: null, exitPrice: 5, exitDate: '2026-07-15' },
      );

      expect(res.ok).toBe(false);
      expect(res.detail).toContain('no longer on the server');
      const recIds = usePortfolioStore.getState().positions.map((p) => p.recId);
      expect(recIds).toEqual(['REC-OTHER']);   // only the confirmed-gone row is dropped
    });

    it('recovers via recId drift when the contract exists remotely under a different recId', async () => {
      const pos = makePosition({ recId: 'REC-OLD', contract: 'DRIFT|1|2026-01-01|C', contracts: 1 });
      act(() => { usePortfolioStore.setState({ positions: [pos] }); });

      let driftCloseCalled = false;
      global.fetch = jest.fn((url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET';
        if (url.includes('/REC-OLD/close') && method === 'POST') {
          return Promise.resolve(jsonResponse({ detail: 'not found' }, false, 404));
        }
        if (url.includes('/REC-NEW/close') && method === 'POST') {
          driftCloseCalled = true;
          return Promise.resolve(jsonResponse({ id: 'x' }, true, 201));
        }
        if (url.endsWith('/api/portfolio') && method === 'POST') {
          return Promise.resolve(jsonResponse({ detail: 'already exists' }, false, 409));   // re-persist fails: drift
        }
        if (url.endsWith('/api/portfolio') && method === 'GET') {
          return Promise.resolve(jsonResponse([{
            id: 'x', recId: 'REC-NEW', symbol: 'AAPL', contract: 'DRIFT|1|2026-01-01|C',
            direction: 'Bullish', entryPrice: 2.1, qty: 1, entryDate: '2026-07-01',
            stop: null, targets: [], dteTotal: 42, createdAt: '2026-07-01T00:00:00Z',
          }], true, 200));
        }
        return Promise.resolve(jsonResponse({}, false, 500));
      }) as unknown as typeof fetch;

      const res = await usePortfolioStore.getState().closePositionRemote(
        'REC-OLD', { qtyToClose: null, exitPrice: 5, exitDate: '2026-07-15' },
      );

      expect(res.ok).toBe(true);
      expect(driftCloseCalled).toBe(true);   // closed the BACKEND's real recId, not the stale one
    });

    it('restores a partial close locally (reduced qty) if the post-close sync fails', async () => {
      const pos = makePosition({ recId: 'REC-PARTIAL', contract: 'PARTIAL|1|2026-01-01|C', contracts: 5 });
      act(() => { usePortfolioStore.setState({ positions: [pos] }); });

      global.fetch = jest.fn((url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET';
        if (url.includes('/close') && method === 'POST') {
          return Promise.resolve(jsonResponse({ id: 'x' }, true, 201));   // close succeeds
        }
        if (url.endsWith('/api/portfolio') && method === 'GET') {
          return Promise.reject(new Error('network down'));   // follow-up sync fails
        }
        return Promise.resolve(jsonResponse({}, false, 500));
      }) as unknown as typeof fetch;

      const res = await usePortfolioStore.getState().closePositionRemote(
        'REC-PARTIAL', { qtyToClose: 2, exitPrice: 5, exitDate: '2026-07-15' },
      );

      expect(res.ok).toBe(true);
      const restored = usePortfolioStore.getState().positions.find((p) => p.recId === 'REC-PARTIAL');
      expect(restored?.contracts).toBe(3);   // 5 - 2, not lost entirely
    });

    it('does NOT restore a failed-sync row after a FULL close (qtyToClose null)', async () => {
      const pos = makePosition({ recId: 'REC-FULL', contract: 'FULL|1|2026-01-01|C', contracts: 5 });
      act(() => { usePortfolioStore.setState({ positions: [pos] }); });

      global.fetch = jest.fn((url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET';
        if (url.includes('/close') && method === 'POST') {
          return Promise.resolve(jsonResponse({ id: 'x' }, true, 201));
        }
        if (url.endsWith('/api/portfolio') && method === 'GET') {
          return Promise.reject(new Error('network down'));
        }
        return Promise.resolve(jsonResponse({}, false, 500));
      }) as unknown as typeof fetch;

      const res = await usePortfolioStore.getState().closePositionRemote(
        'REC-FULL', { qtyToClose: null, exitPrice: 5, exitDate: '2026-07-15' },
      );

      expect(res.ok).toBe(true);
      expect(usePortfolioStore.getState().positions.find((p) => p.recId === 'REC-FULL')).toBeUndefined();
    });

    it('restores a drift-recovered partial close under the BACKEND recId, not the stale local one', async () => {
      // Regression test: after drift recovery closes REC-NEW-2 (the backend's real
      // id, not the caller's stale REC-OLD-2), a failed follow-up sync must restore
      // the row under REC-NEW-2 — restoring under REC-OLD-2 would 404 on any
      // subsequent action until the next successful sync heals it.
      const pos = makePosition({ recId: 'REC-OLD-2', contract: 'DRIFT2|1|2026-01-01|C', contracts: 5 });
      act(() => { usePortfolioStore.setState({ positions: [pos] }); });

      let getCallCount = 0;
      global.fetch = jest.fn((url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET';
        if (url.includes('/REC-OLD-2/close') && method === 'POST') {
          return Promise.resolve(jsonResponse({ detail: 'not found' }, false, 404));
        }
        if (url.includes('/REC-NEW-2/close') && method === 'POST') {
          return Promise.resolve(jsonResponse({ id: 'x' }, true, 201));
        }
        if (url.endsWith('/api/portfolio') && method === 'POST') {
          return Promise.resolve(jsonResponse({ detail: 'already exists' }, false, 409));
        }
        if (url.endsWith('/api/portfolio') && method === 'GET') {
          getCallCount++;
          if (getCallCount === 1) {
            // fetchRemote (drift lookup) — finds the contract under REC-NEW-2.
            return Promise.resolve(jsonResponse([{
              id: 'x', recId: 'REC-NEW-2', symbol: 'AAPL', contract: 'DRIFT2|1|2026-01-01|C',
              direction: 'Bullish', entryPrice: 2.1, qty: 5, entryDate: '2026-07-01',
              stop: null, targets: [], dteTotal: 42, createdAt: '2026-07-01T00:00:00Z',
            }], true, 200));
          }
          // syncFromBackend after the successful drift-recovered close — fails.
          return Promise.reject(new Error('network down'));
        }
        return Promise.resolve(jsonResponse({}, false, 500));
      }) as unknown as typeof fetch;

      const res = await usePortfolioStore.getState().closePositionRemote(
        'REC-OLD-2', { qtyToClose: 2, exitPrice: 5, exitDate: '2026-07-15' },
      );

      expect(res.ok).toBe(true);
      const positions = usePortfolioStore.getState().positions;
      expect(positions.find((p) => p.recId === 'REC-OLD-2')).toBeUndefined();   // stale id gone
      const restored = positions.find((p) => p.recId === 'REC-NEW-2');
      expect(restored).toBeDefined();
      expect(restored?.contracts).toBe(3);   // 5 - 2
    });

    it('does not issue a second network request for a close already in flight', async () => {
      let resolveFirst!: (v: Response) => void;
      const firstResponse = new Promise<Response>((res) => { resolveFirst = res; });
      let callCount = 0;

      global.fetch = jest.fn((url: string) => {
        if (typeof url === 'string' && url.includes('/close')) {
          callCount += 1;
          return firstResponse;
        }
        return Promise.resolve({ ok: true, json: async () => [] } as Response);
      }) as unknown as typeof fetch;

      const recId = 'REC-TEST-DOUBLE-CLOSE';
      const p1 = usePortfolioStore.getState().closePositionRemote(recId, {});
      const p2 = usePortfolioStore.getState().closePositionRemote(recId, {});

      resolveFirst({ ok: true, json: async () => ({}) } as Response);
      await Promise.all([p1, p2]);

      expect(callCount).toBe(1);
    });
  });

  // ── Single-source-of-truth: verified writes + authoritative reconcile ────────

  const abt = {
    symbol: 'ABT', contract: 'ABT|97|2027-01-15|C', direction: 'Bullish',
    entryDate: '2026-07-17', expiry: '2027-01-15', dteRemaining: 547, dteTotal: 547,
    entryPrice: 10.45, currentPrice: 10.45, pnlDollar: 0, pnlPct: 0, stop: 89.89,
    targets: [], status: 'PENDING', contracts: 1, recId: 'REC-ABT-1',
  } as unknown as PortfolioPosition;

  describe('persist migration for legacy rows', () => {
    it('tags legacy persisted rows (no syncStatus) as synced with syncedAt=0', () => {
      const migrated = migratePortfolioPersist(
        { positions: [{ recId: 'LEGACY-1', symbol: 'ABT', contract: 'ABT|97|2027-01-15|C' }] },
        0,
      ) as { positions: Array<Record<string, unknown>> };
      expect(migrated.positions[0]!.syncStatus).toBe('synced');
      expect(migrated.positions[0]!.syncedAt).toBe(0);
    });
  });

  describe('account value for backend POSTs', () => {
    it('persistPosition sends the configured account value, not the sum of premiums', async () => {
      const fetchMock = jest.fn().mockResolvedValue({ ok: true, status: 201, json: async () => ({}) });
      (global as unknown as { fetch: jest.Mock }).fetch = fetchMock;
      await persistPosition({ ...abt, recId: 'REC-AV-1' });
      const body = JSON.parse(fetchMock.mock.calls[0][1].body);
      expect(body.portfolioValue).toBe(50000);
    });
  });

  describe('addPosition verified write', () => {
    it('marks the row synced and returns ok when the backend accepts it', async () => {
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockResolvedValue({ ok: true, status: 201, json: async () => ({}) });
      const res = await usePortfolioStore.getState().addPosition(abt);
      expect(res.ok).toBe(true);
      expect(usePortfolioStore.getState().positions.find((p) => p.recId === 'REC-ABT-1')?.syncStatus).toBe('synced');
      expect(usePortfolioStore.getState().lastSyncError).toBeNull();
    });

    it('drops the row and records the reason when the backend rejects it (422)', async () => {
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockResolvedValue({ ok: false, status: 422, json: async () => ({ detail: 'single_trade_exposure_too_high' }) });
      const res = await usePortfolioStore.getState().addPosition(abt);
      expect(res.ok).toBe(false);
      expect(res.status).toBe('rejected');
      expect(res.detail).toBe('single_trade_exposure_too_high');
      expect(usePortfolioStore.getState().positions.find((p) => p.recId === 'REC-ABT-1')).toBeUndefined();
      expect(usePortfolioStore.getState().lastSyncError?.detail).toBe('single_trade_exposure_too_high');
    });

    it('keeps the row pending (status=pending) when the backend is unreachable', async () => {
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn().mockRejectedValue(new Error('network'));
      const res = await usePortfolioStore.getState().addPosition(abt);
      expect(res.ok).toBe(false);
      expect(res.status).toBe('pending');
      expect(usePortfolioStore.getState().positions.find((p) => p.recId === 'REC-ABT-1')?.syncStatus).toBe('pending');
      expect(usePortfolioStore.getState().lastSyncError).toBeNull();
    });

    it('rolls back a scale-in MERGE (different recId, same contract) when the backend rejects', async () => {
      usePortfolioStore.setState({
        positions: [{ ...abt, recId: 'REC-EXIST', contracts: 2, syncStatus: 'synced', syncedAt: Date.now() }],
      } as never);
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockResolvedValue({ ok: false, status: 422, json: async () => ({ detail: 'x' }) });
      await usePortfolioStore.getState().addPosition({ ...abt, recId: 'REC-NEW', contracts: 3 });
      const rows = usePortfolioStore.getState().positions.filter((p) => p.contract === 'ABT|97|2027-01-15|C');
      expect(rows).toHaveLength(1);
      expect(rows[0]!.recId).toBe('REC-EXIST');
      expect(rows[0]!.contracts).toBe(2);
      expect(rows[0]!.syncStatus).toBe('synced');
    });

    it('rolls back a scale-in MERGE on a 409 (backend refuses scale-in) instead of reporting false success', async () => {
      // Regression: the backend keeps one open position per contract with no
      // scale-in path, so a merge's re-POST always 409s. Treating that 409 as
      // success (like a plain duplicate-add) would report the bumped quantity
      // as saved when the backend never recorded it — silently lost on the next sync.
      usePortfolioStore.setState({
        positions: [{ ...abt, recId: 'REC-EXIST', contracts: 2, syncStatus: 'synced', syncedAt: Date.now() }],
      } as never);
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockResolvedValue({ ok: false, status: 409, json: async () => ({ detail: 'already exists' }) });
      const res = await usePortfolioStore.getState().addPosition({ ...abt, recId: 'REC-NEW', contracts: 3 });
      expect(res.ok).toBe(false);
      expect(res.status).toBe('rejected');
      const rows = usePortfolioStore.getState().positions.filter((p) => p.contract === 'ABT|97|2027-01-15|C');
      expect(rows).toHaveLength(1);
      expect(rows[0]!.recId).toBe('REC-EXIST');
      expect(rows[0]!.contracts).toBe(2);          // NOT bumped to 5
      expect(rows[0]!.syncStatus).toBe('synced');
      expect(usePortfolioStore.getState().lastSyncError).not.toBeNull();
    });

    it('rolls back a REPLACE (same recId) to the prior row when the backend rejects', async () => {
      usePortfolioStore.setState({
        positions: [{ ...abt, recId: 'REC-ABT-1', contracts: 2, entryPrice: 9.0, syncStatus: 'synced', syncedAt: Date.now() }],
      } as never);
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockResolvedValue({ ok: false, status: 422, json: async () => ({ detail: 'x' }) });
      await usePortfolioStore.getState().addPosition({ ...abt, recId: 'REC-ABT-1', contracts: 3, entryPrice: 11.0 });
      const pos = usePortfolioStore.getState().positions.find((p) => p.recId === 'REC-ABT-1');
      expect(pos?.contracts).toBe(2);
      expect(pos?.entryPrice).toBe(9.0);
      expect(pos?.syncStatus).toBe('synced');
    });
  });

  describe('syncFromBackend authoritative reconcile', () => {
    const mkLocal = (recId: string, over: Record<string, unknown> = {}) => ({
      symbol: 'ABT', contract: `ABT|${recId}|2027-01-15|C`, direction: 'Bullish',
      entryDate: '2026-07-17', expiry: '2027-01-15', dteRemaining: 1, dteTotal: 1,
      entryPrice: 10, currentPrice: 10, pnlDollar: 0, pnlPct: 0, stop: 5, targets: [],
      status: 'PENDING', contracts: 1, recId, ...over,
    }) as unknown as PortfolioPosition;

    it('drops a legacy/synced local row (syncedAt in the past) that the backend lacks', async () => {
      usePortfolioStore.setState({ positions: [mkLocal('GHOST', { syncStatus: 'synced', syncedAt: 0 })] } as never);
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockResolvedValue({ ok: true, json: async () => [] });
      await usePortfolioStore.getState().syncFromBackend();
      expect(usePortfolioStore.getState().positions).toHaveLength(0);
    });

    it('keeps a row synced AFTER this GET started (poll-race safe)', async () => {
      usePortfolioStore.setState({
        positions: [mkLocal('FRESH', { syncStatus: 'synced', syncedAt: Date.now() + 60_000 })],
      } as never);
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockResolvedValue({ ok: true, json: async () => [] });
      await usePortfolioStore.getState().syncFromBackend();
      expect(usePortfolioStore.getState().positions.map((p) => p.recId)).toContain('FRESH');
    });

    it('retries a pending local row and marks it synced when the retry POST succeeds', async () => {
      usePortfolioStore.setState({
        positions: [mkLocal('PEND', { syncStatus: 'pending', syncPendingSince: Date.now() })],
      } as never);
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockImplementation((_url: string, init?: { method?: string }) => {
          if ((init?.method ?? 'GET') === 'GET') return Promise.resolve({ ok: true, json: async () => [] });
          return Promise.resolve({ ok: true, status: 201, json: async () => ({}) });
        });
      await usePortfolioStore.getState().syncFromBackend();
      expect(usePortfolioStore.getState().positions.find((p) => p.recId === 'PEND')?.syncStatus).toBe('synced');
    });

    it('keeps a pending row (never silently drops it) when the retry POST also fails on network', async () => {
      usePortfolioStore.setState({
        positions: [mkLocal('PEND2', { syncStatus: 'pending', syncPendingSince: Date.now() - 999_999 })],
      } as never);
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockImplementation((_url: string, init?: { method?: string }) => {
          if ((init?.method ?? 'GET') === 'GET') return Promise.resolve({ ok: true, json: async () => [] });
          return Promise.reject(new Error('still down'));
        });
      await usePortfolioStore.getState().syncFromBackend();
      expect(usePortfolioStore.getState().positions.find((p) => p.recId === 'PEND2')?.syncStatus).toBe('pending');
    });
  });
});
