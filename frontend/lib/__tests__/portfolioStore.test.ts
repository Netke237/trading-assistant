import { renderHook, act } from '@testing-library/react';
import { usePortfolioStore, persistPosition, migratePortfolioPersist, applyPersistedPosition } from '@/lib/portfolioStore';
import { useRiskStore } from '@/lib/riskStore';
import type { PortfolioPosition } from '@/types/domain';
import { premiumStopThresholdPrice } from '@/lib/premiumStop';

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
        maxLossPerTradePct: 0.0375,
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

  it('floors stop/structuralStop of 0 in addPosition\'s own optimistic write', async () => {
    // Round-6 audit finding: buildPaperStockPosition (paperTrade.ts) sends
    // stop: 0 for every paper stock buy, and addPosition's optimistic set()
    // was the one write site of eight that let it straight through to live
    // state, unfloored — a real false STOP_REACHED on the dashboard for a
    // Bearish position, before the next sync corrected it.
    const { result } = renderHook(() => usePortfolioStore());

    await act(async () => {
      await result.current.addPosition(makePosition({ direction: 'Bearish', stop: 0, structuralStop: 0 }));
    });

    expect(result.current.positions[0].stop).toBeNull();
    expect(result.current.positions[0].structuralStop).toBeNull();
  });

  it('floors stop/structuralStop of 0 passed to hydrate', () => {
    const { result } = renderHook(() => usePortfolioStore());

    act(() => {
      result.current.hydrate([makePosition({ recId: 'REC-HYDRATE-ZERO', stop: 0, structuralStop: 0 })]);
    });

    expect(result.current.positions[0].stop).toBeNull();
    expect(result.current.positions[0].structuralStop).toBeNull();
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

  it('a pending stock row the retry books SMALLER takes the booked size and scaled rungs (stock code round 1)', async () => {
    // STOCK-SENDS-SAVE-FIRST-THEN-REAL-SHARES: a stock save can be resized, and
    // this 30s retry is a save path. The writer books 100 and stores 33/33/34,
    // so the local row must too -- a drawer rung edit before the next GET would
    // otherwise PATCH rungs selling 200 of 100 held.
    global.fetch = jest.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST') {
        const body = JSON.parse(String(init.body));
        return { ok: true, status: 201, json: async () => ({ ...body, adjustedQty: 100 }) };
      }
      return { ok: true, status: 200, json: async () => [] };
    }) as unknown as typeof fetch;

    act(() => {
      usePortfolioStore.setState({
        positions: [makePosition({
          symbol: 'AAA', contract: 'AAA|STOCK', recId: 'REC-STOCK', contracts: 200,
          targets: [
            { stockPrice: 55, contractsToSell: 66 }, { stockPrice: 56, contractsToSell: 66 }, { stockPrice: 57, contractsToSell: 68 },
          ],
          syncStatus: 'pending', syncPendingSince: Date.now(),
        })],
        lastSyncError: null,
      });
    });

    await act(async () => {
      await usePortfolioStore.getState().syncFromBackend();
    });

    const row = usePortfolioStore.getState().positions.find((p) => p.recId === 'REC-STOCK')!;
    expect(row.syncStatus).toBe('synced');
    expect(row.contracts).toBe(100);
    expect(row.targets.map((t) => t.contractsToSell)).toEqual([33, 33, 34]);
    expect(usePortfolioStore.getState().lastSyncError?.detail).toMatch(/Size reduced to 100/);
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

  it('floors a stop/structuralStop of 0 already in localStorage on rehydrate, even with no version bump', async () => {
    // Round-5 audit finding: `merge` runs on EVERY rehydration (migrate only
    // runs on a version change), so it's the actual backstop for a browser
    // that already has a pre-round-2 stop:0 row saved — this must floor
    // independent of whatever migratePortfolioPersist does.
    localStorage.setItem(
      'bamendjou-portfolio-v1',
      JSON.stringify({
        version: 2, // current version — migrate will NOT run
        state: {
          positions: [
            makePosition({
              symbol: 'ABT', contract: 'ABT|97|2027-01-15|C', recId: 'REC-STALE-ZERO',
              direction: 'Bearish', stop: 0, structuralStop: 0,
            }),
          ],
        },
      }),
    );

    await act(async () => {
      await usePortfolioStore.persist.rehydrate();
    });

    const position = usePortfolioStore.getState().positions.find((p) => p.recId === 'REC-STALE-ZERO');
    expect(position?.stop).toBeNull();
    expect(position?.structuralStop).toBeNull();
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

    it('a 404 re-save booked SMALLER does not close; the row takes the booked size (stock code round 2)', async () => {
      // STOCK-SENDS-SAVE-FIRST-THEN-REAL-SHARES: the re-POST after a close 404
      // can now be resized. Closing then would close the smaller booked row and
      // drop the full local one -- a wrong close in History.
      const pos = makePosition({
        recId: 'REC-RS', symbol: 'AAA', contract: 'AAA|STOCK', contracts: 100,
        targets: [{ stockPrice: 160, contractsToSell: 50 }, { stockPrice: 170, contractsToSell: 50 }],
      });
      act(() => { usePortfolioStore.setState({ positions: [pos], lastSyncError: null }); });

      const closes: string[] = [];
      global.fetch = jest.fn((url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET';
        if (url.includes('/close') && method === 'POST') {
          closes.push(url);
          return Promise.resolve(jsonResponse({ detail: 'not found' }, false, 404));
        }
        if (url.endsWith('/api/portfolio') && method === 'POST') {
          const body = JSON.parse(String(init?.body));
          return Promise.resolve(jsonResponse({ ...body, adjustedQty: 33 }, true, 201));
        }
        return Promise.resolve(jsonResponse([], true, 200));
      }) as unknown as typeof fetch;

      const res = await usePortfolioStore.getState().closePositionRemote(
        'REC-RS', { qtyToClose: null, exitPrice: 150, exitDate: '2026-09-26' },
      );

      expect(res.ok).toBe(false);
      expect(res.detail).toMatch(/re-saved this position at 33 shares.*close was NOT sent/);
      expect(closes).toHaveLength(1);   // only the first (404) close; no second close
      const row = usePortfolioStore.getState().positions.find((p) => p.recId === 'REC-RS')!;
      expect(row.contracts).toBe(33);
      expect(row.targets.map((t) => t.contractsToSell)).toEqual([16, 17]);
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

    it('v2 -> v3: normalises premiumStopPct to null and drops the create-only dollar', () => {
      // CLAUDE.md asks for a version bump and a branch whenever a persisted
      // field is added; piece 4 added two without one. Benign by luck (a v2 row
      // has neither key, and `undefined` already reads as "inherit"), which is
      // exactly why it is worth pinning rather than leaving the next reader to
      // re-derive it from resolvePremiumStopPct.
      const migrated = migratePortfolioPersist(
        {
          positions: [
            { recId: 'V2-ROW', symbol: 'ABT', contract: 'ABT|97|2027-01-15|C' },
            { recId: 'SYNCED', symbol: 'ABT', contract: 'ABT|98|2027-01-15|C',
              syncStatus: 'synced', premiumStopPct: 0.45, premiumStopDollar: 2.0 },
          ],
        },
        2,
      ) as { positions: Array<Record<string, unknown>> };

      // A legacy row inherits the global, and says so explicitly.
      expect(migrated.positions[0]!.premiumStopPct).toBeNull();
      // An explicit per-position value is preserved, never normalised away.
      expect(migrated.positions[1]!.premiumStopPct).toBe(0.45);
      // premiumStopDollar is CREATE-ONLY transport: the server divided it by
      // the persisted entry and stored the fraction, so on a synced row it
      // describes nothing and nothing reads it back.
      expect('premiumStopDollar' in migrated.positions[1]!).toBe(false);
    });

    it('v2 -> v3: a PENDING row keeps premiumStopDollar, because its retry re-posts it', () => {
      // The condition on that delete is load-bearing, and getting it wrong is
      // silent: syncFromBackend retries a pending row through postPosition,
      // whose toBackendPayload sends premiumStopDollar for the SERVER to divide
      // by the entry price it persists. Stripping it here would hand that row
      // to the global on every offline-then-recovered save, with nothing to
      // show a stop had been asked for.
      const migrated = migratePortfolioPersist(
        {
          positions: [{
            recId: 'PENDING', symbol: 'ABT', contract: 'ABT|99|2027-01-15|C',
            syncStatus: 'pending', premiumStopDollar: 2.0,
          }],
        },
        2,
      ) as { positions: Array<Record<string, unknown>> };
      expect(migrated.positions[0]!.premiumStopDollar).toBe(2.0);
    });

    it('v4 -> v5: drops the unattributable pre-split ivRank off a persisted row', () => {
      // ROUND 1 finding (b). Before the Phase A split, `ivRank` held EITHER a
      // true percentile (IBKR/tastytrade) OR raw IV x 100 (every other chain),
      // with nothing saying which. Rehydrating one makes the portfolio table
      // print "IV rank 45" for what is most likely a 45% absolute IV — the
      // exact mislabel Phase A removes. The basis is not recoverable, so the
      // figure is dropped, not guessed; see lib/ivBasis.ts.
      //
      // Worse here than in scanStore: syncFromBackend refreshes these fields
      // only on rows the reconcile confirms, so on a row it keeps as
      // pending/offline a stale figure would never be replaced.
      const migrated = migratePortfolioPersist(
        {
          positions: [{
            recId: 'LEGACY-IV', symbol: 'ABT', contract: 'ABT|97|2027-01-15|C',
            syncStatus: 'pending', ivRank: 45, entryPrice: 10.45,
          }],
        },
        4,
      ) as { positions: Array<Record<string, unknown>> };
      expect(migrated.positions[0]!.ivRank).toBeNull();
      // Nothing else on the row is disturbed.
      expect(migrated.positions[0]!.entryPrice).toBe(10.45);
      expect(migrated.positions[0]!.syncStatus).toBe('pending');
    });

    it('v4 -> v5: the drop is VERSION-GATED, unlike every other branch here', () => {
      // The other branches are idempotent and ignore the version. This one is
      // destructive: a post-split row's `ivRank` IS a real percentile, so
      // running it unconditionally would throw away good data on every load.
      const migrated = migratePortfolioPersist(
        {
          positions: [{
            recId: 'POST-SPLIT', symbol: 'ABT', contract: 'ABT|97|2027-01-15|C',
            syncStatus: 'synced', ivRank: 62, iv: null,
          }],
        },
        5,
      ) as { positions: Array<Record<string, unknown>> };
      expect(migrated.positions[0]!.ivRank).toBe(62);
    });

    it('floors a stop/structuralStop of 0 already sitting in a pre-round-2 localStorage row', () => {
      // Round-5 audit finding: a row saved to localStorage before the
      // stop=0 fix (round 2) rehydrates straight into live state on every
      // app load — floor it here too, not just on the live write paths.
      const migrated = migratePortfolioPersist(
        {
          positions: [{
            recId: 'LEGACY-ZERO', symbol: 'ABT', contract: 'ABT|97|2027-01-15|C',
            direction: 'Bearish', stop: 0, structuralStop: 0,
          }],
        },
        0,
      ) as { positions: Array<Record<string, unknown>> };
      expect(migrated.positions[0]!.stop).toBeNull();
      expect(migrated.positions[0]!.structuralStop).toBeNull();
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

    it('persistPosition includes exitPlan in the POST body — regression guard for a round-2 audit finding where the create payload silently dropped it', async () => {
      // A plan computed pre-trade via TradeCard's "Compute Exit Plan" and
      // attached to the position before sending to broker must actually
      // reach the backend on creation, not just on a later PATCH edit — the
      // create path (toBackendPayload) had no exitPlan field at all until
      // this fix, so the very next syncFromBackend silently erased it.
      const exitPlan = {
        computedAt: '2026-08-26T12:00:00.000Z',
        stop: {
          price: 89.0, source: 'structural' as const, contractPrice: 1.1, rrModel: 'Heston repriced' as const,
          structuralSource: 'order_block' as const, structuralConfidence: 80,
          structuralPrice: 89.0, atrFloorPrice: 85.0, distanceDollar: 4.0,
        },
        targets: [],
        atr: 2.0,
      };
      const fetchMock = jest.fn().mockResolvedValue({ ok: true, status: 201, json: async () => ({}) });
      (global as unknown as { fetch: jest.Mock }).fetch = fetchMock;
      await persistPosition({ ...abt, recId: 'REC-EP-1', exitPlan });
      const body = JSON.parse(fetchMock.mock.calls[0][1].body);
      expect(body.exitPlan).toEqual(exitPlan);
    });

    it('persistPosition sends exitPlan as null when the position has none', async () => {
      const fetchMock = jest.fn().mockResolvedValue({ ok: true, status: 201, json: async () => ({}) });
      (global as unknown as { fetch: jest.Mock }).fetch = fetchMock;
      await persistPosition({ ...abt, recId: 'REC-EP-2' });
      const body = JSON.parse(fetchMock.mock.calls[0][1].body);
      expect(body.exitPlan).toBeNull();
    });

    it('persistPosition includes maxLossOverride in the POST body (Feature 5) — the create payload has no such key at all without this, so a pre-trade override appears to work in optimistic local UI state but the backend never receives it, and the next sync silently overwrites it with null', async () => {
      const fetchMock = jest.fn().mockResolvedValue({ ok: true, status: 201, json: async () => ({}) });
      (global as unknown as { fetch: jest.Mock }).fetch = fetchMock;
      await persistPosition({ ...abt, recId: 'REC-MLO-1', maxLossOverride: { mode: 'percent', value: 0.05 } });
      const body = JSON.parse(fetchMock.mock.calls[0][1].body);
      expect(body.maxLossOverride).toEqual({ mode: 'percent', value: 0.05 });
    });

    it('persistPosition sends maxLossOverride as null when the position has none', async () => {
      const fetchMock = jest.fn().mockResolvedValue({ ok: true, status: 201, json: async () => ({}) });
      (global as unknown as { fetch: jest.Mock }).fetch = fetchMock;
      await persistPosition({ ...abt, recId: 'REC-MLO-2' });
      const body = JSON.parse(fetchMock.mock.calls[0][1].body);
      expect(body.maxLossOverride).toBeNull();
    });

    it('persistPosition surfaces adjustedQty when the backend auto-reduces the size', async () => {
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockResolvedValue({ ok: true, status: 201, json: async () => ({ adjustedQty: 2 }) });
      const res = await persistPosition({ ...abt, recId: 'REC-AV-2', contracts: 5 });
      expect(res.ok).toBe(true);
      expect(res.adjustedQty).toBe(2);
    });

    it('persistPosition includes all five picked_* fields in the POST body — regression guard for the send-path wiring gap found 2026-09-15, same genre as exitPlan/maxLossOverride above: every send-path caller now sets these on the object it passes in, but toBackendPayload itself had no allowlist entry for them, so the values would still have been silently dropped on the wire even after every caller was fixed', async () => {
      const fetchMock = jest.fn().mockResolvedValue({ ok: true, status: 201, json: async () => ({}) });
      (global as unknown as { fetch: jest.Mock }).fetch = fetchMock;
      await persistPosition({
        ...abt, recId: 'REC-PICK-1',
        pickedMethod: 'monte_carlo', pickedRowStockPrice: 197.5, pickedRowOptionPrice: 6.24,
        pickedStopBasis: 'stock', pickedAt: '2026-09-14T10:00:00.000Z',
      });
      const body = JSON.parse(fetchMock.mock.calls[0][1].body);
      expect(body.pickedMethod).toBe('monte_carlo');
      expect(body.pickedRowStockPrice).toBe(197.5);
      expect(body.pickedRowOptionPrice).toBe(6.24);
      expect(body.pickedStopBasis).toBe('stock');
      expect(body.pickedAt).toBe('2026-09-14T10:00:00.000Z');
    });

    it('persistPosition sends all five picked_* fields as explicit null when the position has none — the S5 auto-executor\'s shape (spec §7.3), never an omitted key', async () => {
      const fetchMock = jest.fn().mockResolvedValue({ ok: true, status: 201, json: async () => ({}) });
      (global as unknown as { fetch: jest.Mock }).fetch = fetchMock;
      await persistPosition({ ...abt, recId: 'REC-PICK-2' });
      const body = JSON.parse(fetchMock.mock.calls[0][1].body);
      expect(body.pickedMethod).toBeNull();
      expect(body.pickedRowStockPrice).toBeNull();
      expect(body.pickedRowOptionPrice).toBeNull();
      expect(body.pickedStopBasis).toBeNull();
      expect(body.pickedAt).toBeNull();
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

    it('surfaces adjustedQty and updates the local row when the backend auto-reduces the size', async () => {
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockResolvedValue({ ok: true, status: 201, json: async () => ({ adjustedQty: 1 }) });
      const res = await usePortfolioStore.getState().addPosition({ ...abt, contracts: 5 });
      expect(res.ok).toBe(true);
      expect(res.adjustedQty).toBe(1);
      expect(usePortfolioStore.getState().positions.find((p) => p.recId === 'REC-ABT-1')?.contracts).toBe(1);
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

    it('renders a Pydantic validation 422 as text instead of storing a list', async () => {
      // ROUND 5. FastAPI's `detail` is a STRING for a risk rejection but a LIST
      // of error objects for a validation failure, and every parse site cast it
      // to string. The list went into `lastSyncError.detail`, and the Portfolio
      // page's `rejectionMessage` does `detail.split(' ')` inside JSX --
      // `TypeError: detail.split is not a function`, which takes the whole page
      // down. The position vanished AND the screen that would say why went with
      // it. Newly reachable because piece 4 added `entryPrice: Field(gt=0)`,
      // and a $0 mid on an illiquid or deep-OTM quote is a state this codebase
      // handles explicitly elsewhere.
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockResolvedValue({
          ok: false,
          status: 422,
          json: async () => ({
            detail: [
              { type: 'greater_than', loc: ['body', 'entry_price'], msg: 'Input should be greater than 0', input: 0 },
            ],
          }),
        });
      const res = await usePortfolioStore.getState().addPosition(abt);
      expect(res.status).toBe('rejected');
      expect(typeof res.detail).toBe('string');
      // Prefixed with the field since this path moved onto lib/pydanticError.ts,
      // the same helper apiError uses. The old unprefixed form was pinned here
      // on the rationale that "these are all single-position posts" — but a
      // single position posts several `gt=0` fields whose messages are
      // byte-identical, so the sibling test below rendered "Input should be
      // greater than 0; Input should be greater than 0" and named neither.
      expect(res.detail).toBe('entry_price: Input should be greater than 0');
      const stored = usePortfolioStore.getState().lastSyncError?.detail;
      expect(typeof stored).toBe('string');
      // The page formatter must survive it -- that is the actual crash.
      expect(() => (stored as string).split(' ')).not.toThrow();
    });

    it('joins multiple validation errors rather than dropping all but one', async () => {
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockResolvedValue({
          ok: false,
          status: 422,
          json: async () => ({
            detail: [
              { msg: 'Input should be greater than 0' },
              { msg: 'Input should be less than 1' },
            ],
          }),
        });
      const res = await usePortfolioStore.getState().addPosition(abt);
      expect(res.detail).toBe('Input should be greater than 0; Input should be less than 1');
    });

    it('falls back to the status code when the error body carries no usable text', async () => {
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockResolvedValue({ ok: false, status: 422, json: async () => ({ detail: [{ loc: ['body'] }] }) });
      const res = await usePortfolioStore.getState().addPosition(abt);
      expect(res.detail).toBe('HTTP 422');
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

  // ── Double-POST fix (#13): persistPosition's offline field + addPosition's ──
  // skipPost option, and the 3-way offline/rejected/confirmed-success branch
  // the step-7-trade-card call sites use around them.
  describe('persistPosition offline distinction + addPosition skipPost', () => {
    it('persistPosition returns ok:false, offline:true (NOT ok:true) on a network failure', async () => {
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn().mockRejectedValue(new Error('network'));
      const res = await persistPosition({ ...abt, recId: 'REC-OFFLINE-1' });
      // Regression guard: the old behavior optimistically returned {ok: true} on
      // a network failure, which let a naive "skip re-POST when saved.ok" caller
      // mark a never-persisted position as synced (see addPosition skipPost test
      // below for the full failure mode this prevents).
      expect(res.ok).toBe(false);
      expect(res.offline).toBe(true);
    });

    it('addPosition({skipPost:true}) marks the row synced WITHOUT issuing its own POST', async () => {
      const fetchMock = jest.fn().mockResolvedValue({ ok: true, status: 201, json: async () => ({}) });
      (global as unknown as { fetch: jest.Mock }).fetch = fetchMock;
      const res = await usePortfolioStore.getState().addPosition({ ...abt, recId: 'REC-SKIP-1' }, { skipPost: true });
      expect(res.ok).toBe(true);
      expect(fetchMock).not.toHaveBeenCalled();
      expect(usePortfolioStore.getState().positions.find((p) => p.recId === 'REC-SKIP-1')?.syncStatus).toBe('synced');
    });

    // ── Regression-critical (per PLAN_TIER3_CLEANUP.md #13): this is the
    // exact failure mode both rounds of adversarial review flagged. Simulates
    // the corrected call-site 3-way branch (offline / rejected / confirmed-
    // success) that step-7-trade-card's placeLimitPaper/placeMarketNow use
    // around persistPosition + addPosition, and proves a network failure
    // during persistPosition does NOT get treated as a confirmed success. ──
    describe('call-site 3-way branch simulation', () => {
      /** Mirrors the exact branch shape from step-7-trade-card's
       *  placeLimitPaper/placeMarketNow, so this test exercises the real
       *  decision logic, not just the store primitives in isolation. */
      async function runCallSiteBranch(pos: PortfolioPosition) {
        const saved = await persistPosition(pos);
        if (saved.offline) {
          return usePortfolioStore.getState().addPosition(pos);
        } else if (!saved.ok) {
          return { ok: false as const, status: 'rejected' as const, detail: saved.detail };
        } else {
          return usePortfolioStore.getState().addPosition(pos, { skipPost: true });
        }
      }

      it('a network failure during persistPosition ends up pending (retryable), not synced or dropped', async () => {
        // persistPosition's own POST fails (offline)...
        (global as unknown as { fetch: jest.Mock }).fetch = jest.fn().mockRejectedValue(new Error('network'));

        await runCallSiteBranch({ ...abt, recId: 'REC-NET-FAIL-1' });

        const row = usePortfolioStore.getState().positions.find((p) => p.recId === 'REC-NET-FAIL-1');
        // Must exist locally — never silently dropped.
        expect(row).toBeDefined();
        // Must NOT be marked synced — that would be the data-loss bug: a
        // syncFromBackend reconcile treats a synced-but-absent-from-backend
        // row as a genuine phantom and deletes it (see the "genuine phantom"
        // branch in syncFromBackend below).
        expect(row?.syncStatus).toBe('pending');
      });

      it('the pending row from a network failure is retried and confirmed by syncFromBackend, not silently dropped', async () => {
        (global as unknown as { fetch: jest.Mock }).fetch = jest.fn().mockRejectedValue(new Error('network'));
        await runCallSiteBranch({ ...abt, recId: 'REC-NET-FAIL-2' });
        expect(usePortfolioStore.getState().positions.find((p) => p.recId === 'REC-NET-FAIL-2')?.syncStatus).toBe('pending');

        // Backend comes back online. syncFromBackend's reconcile retries any
        // pending row via its own POST (postPosition) before treating an
        // absent-from-GET row as a phantom to drop.
        (global as unknown as { fetch: jest.Mock }).fetch = jest.fn((url: string, init?: RequestInit) => {
          const method = init?.method ?? 'GET';
          if (url.endsWith('/api/portfolio') && method === 'GET') {
            return Promise.resolve(jsonResponse([], true, 200)); // backend still has nothing yet
          }
          if (url.endsWith('/api/portfolio') && method === 'POST') {
            return Promise.resolve(jsonResponse({}, true, 201)); // retry succeeds
          }
          return Promise.resolve(jsonResponse({}, false, 500));
        });

        await usePortfolioStore.getState().syncFromBackend();

        const row = usePortfolioStore.getState().positions.find((p) => p.recId === 'REC-NET-FAIL-2');
        expect(row).toBeDefined();
        expect(row?.syncStatus).toBe('synced');
      });

      it('the retried row keeps the premiumStopPct the SERVER derived, not undefined', async () => {
        // Piece 4. addPosition and applyPersistedPosition both fold the
        // server-derived fraction onto the local row; this third call site --
        // the offline retry -- did not, and nothing covered it. A trade sent
        // while the backend was unreachable went pending, this reconcile saved
        // it successfully, and the row stayed at `premiumStopPct: undefined`,
        // so alertEngine.scanPortfolio resolved it to the GLOBAL 0.60 while the
        // backend's alert_generator used the derived 0.78. That is the two-
        // engines-disagree window piece 4 exists to close, and it self-healed
        // only on the next GET.
        (global as unknown as { fetch: jest.Mock }).fetch = jest.fn().mockRejectedValue(new Error('network'));
        await runCallSiteBranch({ ...abt, recId: 'REC-NET-FAIL-PCT' });
        expect(usePortfolioStore.getState().positions.find((p) => p.recId === 'REC-NET-FAIL-PCT')?.premiumStopPct)
          .toBeUndefined();

        (global as unknown as { fetch: jest.Mock }).fetch = jest.fn((url: string, init?: RequestInit) => {
          const method = init?.method ?? 'GET';
          if (url.endsWith('/api/portfolio') && method === 'GET') {
            return Promise.resolve(jsonResponse([], true, 200));
          }
          if (url.endsWith('/api/portfolio') && method === 'POST') {
            // What the router returns once it has divided premiumStopDollar by
            // the entry price it actually persisted.
            return Promise.resolve(jsonResponse({ premiumStopPct: 0.78 }, true, 201));
          }
          return Promise.resolve(jsonResponse({}, false, 500));
        });

        await usePortfolioStore.getState().syncFromBackend();

        const row = usePortfolioStore.getState().positions.find((p) => p.recId === 'REC-NET-FAIL-PCT');
        expect(row?.syncStatus).toBe('synced');
        expect(row?.premiumStopPct).toBe(0.78);
      });

      it('a genuine rejection from persistPosition is surfaced and does NOT call addPosition a second time', async () => {
        (global as unknown as { fetch: jest.Mock }).fetch = jest.fn().mockResolvedValue({
          ok: false, status: 422, json: async () => ({ detail: 'single_trade_exposure_too_high' }),
        });
        const res = await runCallSiteBranch({ ...abt, recId: 'REC-REJECTED-1' });
        expect(res.ok).toBe(false);
        expect((res as { detail?: string }).detail).toBe('single_trade_exposure_too_high');
        // Rejected by persistPosition means addPosition is never reached — no
        // local row should exist for it.
        expect(usePortfolioStore.getState().positions.find((p) => p.recId === 'REC-REJECTED-1')).toBeUndefined();
      });

      it('a confirmed success issues exactly one POST total (not two)', async () => {
        const fetchMock = jest.fn().mockResolvedValue({ ok: true, status: 201, json: async () => ({}) });
        (global as unknown as { fetch: jest.Mock }).fetch = fetchMock;
        const res = await runCallSiteBranch({ ...abt, recId: 'REC-CONFIRMED-1' });
        expect(res.ok).toBe(true);
        expect(fetchMock).toHaveBeenCalledTimes(1); // persistPosition's POST only — addPosition skips its own
        expect(usePortfolioStore.getState().positions.find((p) => p.recId === 'REC-CONFIRMED-1')?.syncStatus).toBe('synced');
      });
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

    it('maps currentStockPrice from the backend response, not currentPrice', async () => {
      usePortfolioStore.setState({ positions: [] } as never);
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn().mockResolvedValue(
        jsonResponse([{ ...makeBackendPosition(), currentPrice: 5.25, currentStockPrice: 182.4 }])
      );
      await usePortfolioStore.getState().syncFromBackend();
      const p = usePortfolioStore.getState().positions[0];
      expect(p.currentPrice).toBe(5.25);
      expect(p.currentStockPrice).toBe(182.4);   // must NOT equal currentPrice
    });

    it('floors a stray stop/structuralStop of 0 in the backend GET response before it reaches state', async () => {
      // Round-5 audit finding: fromBackend was a raw passthrough for `stop`
      // and only coerced null/undefined (not 0) for `structuralStop` — any
      // GET response carrying a stray 0 (a not-yet-migrated row, a bug in
      // some other write path) landed straight in local state on every poll.
      usePortfolioStore.setState({ positions: [] } as never);
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn().mockResolvedValue(
        jsonResponse([{ ...makeBackendPosition(), stop: 0, structuralStop: 0 }])
      );
      await usePortfolioStore.getState().syncFromBackend();
      const p = usePortfolioStore.getState().positions[0];
      expect(p.stop).toBeNull();
      expect(p.structuralStop).toBeNull();
    });

    it('maps the Feature D alert/TP fields off the backend GET response', async () => {
      usePortfolioStore.setState({ positions: [] } as never);
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn().mockResolvedValue(
        jsonResponse([{
          ...makeBackendPosition(),
          activeTpMethod: 'exit_plan_2r',
          resolvedTpPrice: 230,
          resolvedTpUpdatedAt: '2026-08-27T00:00:00.000Z',
          alertOverrides: { STOP_REACHED: false },
        }])
      );
      await usePortfolioStore.getState().syncFromBackend();
      const p = usePortfolioStore.getState().positions[0];
      expect(p.activeTpMethod).toBe('exit_plan_2r');
      expect(p.resolvedTpPrice).toBe(230);
      expect(p.resolvedTpUpdatedAt).toBe('2026-08-27T00:00:00.000Z');
      expect(p.alertOverrides).toEqual({ STOP_REACHED: false });
    });

    it('maps the Phase G picked_* fields off the backend GET response — same genre as activeTpMethod/resolvedTpPrice above, found missing 2026-09-15: without this, a picked_method correctly persisted server-side (once the send-path wiring gap is closed) would still vanish from the client on the very next portfolio sync', async () => {
      usePortfolioStore.setState({ positions: [] } as never);
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn().mockResolvedValue(
        jsonResponse([{
          ...makeBackendPosition(),
          pickedMethod: 'barrier_race',
          pickedRowStockPrice: null,
          pickedRowOptionPrice: 6.24,
          pickedStopBasis: 'premium',
          pickedAt: '2026-09-14T10:00:00.000Z',
        }])
      );
      await usePortfolioStore.getState().syncFromBackend();
      const p = usePortfolioStore.getState().positions[0];
      expect(p.pickedMethod).toBe('barrier_race');
      expect(p.pickedRowStockPrice).toBeNull();
      expect(p.pickedRowOptionPrice).toBe(6.24);
      expect(p.pickedStopBasis).toBe('premium');
      expect(p.pickedAt).toBe('2026-09-14T10:00:00.000Z');
    });

    it('leaves a genuinely absent pick as null, never defaulting it the way activeTpMethod defaults to ladder', async () => {
      // Unlike activeTpMethod (whose absence means "predates the column" and
      // is normalised to 'ladder'), NULL is a real, already-supported state
      // for pickedMethod — a pre-G position, or one from the S5 auto-executor
      // (spec §7.3) — and must render as "—", never as a method nobody chose.
      usePortfolioStore.setState({ positions: [] } as never);
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn().mockResolvedValue(
        jsonResponse([{ ...makeBackendPosition() }])
      );
      await usePortfolioStore.getState().syncFromBackend();
      const p = usePortfolioStore.getState().positions[0];
      expect(p.pickedMethod).toBeNull();
    });

    it('normalises a missing activeTpMethod to ladder and overrides to {}', async () => {
      // A row written before the column default (or a payload that omits the
      // keys) must not leave the drawer's selector and alertEngine handling a
      // null method.
      usePortfolioStore.setState({ positions: [] } as never);
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn().mockResolvedValue(
        jsonResponse([{ ...makeBackendPosition(), activeTpMethod: null, alertOverrides: null }])
      );
      await usePortfolioStore.getState().syncFromBackend();
      const p = usePortfolioStore.getState().positions[0];
      expect(p.activeTpMethod).toBe('ladder');
      expect(p.alertOverrides).toEqual({});
      expect(p.resolvedTpPrice).toBeNull();
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

    it('re-sends tradeCardSnapshot on the pending-row retry (stored on the position, not a one-off arg)', async () => {
      // This is the scenario the audit flagged: a buy made while the backend
      // is unreachable must not silently lose its "why was this bought"
      // snapshot when syncFromBackend later retries the POST.
      const snapshot = { stockScore: 82, stockBreakdown: { trend: 'PASS' } };
      usePortfolioStore.setState({
        positions: [mkLocal('PEND-SNAP', {
          syncStatus: 'pending', syncPendingSince: Date.now(), tradeCardSnapshot: snapshot,
        })],
      } as never);
      let retryBody: Record<string, unknown> | null = null;
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockImplementation((_url: string, init?: { method?: string; body?: string }) => {
          if ((init?.method ?? 'GET') === 'GET') return Promise.resolve({ ok: true, json: async () => [] });
          retryBody = JSON.parse(init!.body as string);
          return Promise.resolve({ ok: true, status: 201, json: async () => ({}) });
        });
      await usePortfolioStore.getState().syncFromBackend();
      expect(usePortfolioStore.getState().positions.find((p) => p.recId === 'PEND-SNAP')?.syncStatus).toBe('synced');
      expect(retryBody).toMatchObject({ tradeCardSnapshot: snapshot });
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

  // Exercises the REAL exported applyPersistedPosition — the exact function
  // step-7-trade-card's placeLimitPaper/placeMarketNow both call — not a
  // hand-reimplemented copy of its branching logic. This is what step-7-trade-card
  // itself has no direct test coverage for; extracting the branch here and testing
  // the extracted function is what makes that real production logic testable at all.
  describe('applyPersistedPosition — the offline/rejected/confirmed-success branch', () => {
    it('offline: falls through to addPosition with no skipPost, so the pending/retry path still engages', () => {
      const pos = makePosition({ recId: 'REC-OFFLINE' });
      const addPosition = jest.fn();
      const onAdjusted = jest.fn();

      const result = applyPersistedPosition({ ok: false, offline: true }, pos, addPosition, onAdjusted);

      expect(result.rejected).toBe(false);
      expect(addPosition).toHaveBeenCalledWith(pos);
      expect(addPosition).not.toHaveBeenCalledWith(pos, { skipPost: true });
      expect(onAdjusted).not.toHaveBeenCalled();
    });

    it('reports a premium stop the server could NOT apply, instead of silently inheriting the global', () => {
      // ROUND 8 finding 9. `add_position` derives pct = premiumStopDollar /
      // entry_price against the price it persists -- the save-time live quote,
      // not the card's mid -- and when that ratio reaches 1 it logs a warning
      // and falls back to `premiumStopPct`, which the card never sends. The row
      // is created with NULL, i.e. the global, and the router's own comment
      // concedes "nothing on screen says why". Reachable through an ordinary
      // fill: $4.50 stop typed against a $5.20 mid, filled at $4.20.
      const pos = makePosition({ recId: 'REC-DROPPED', premiumStopDollar: 4.5 });
      const addPosition = jest.fn();
      const onDropped = jest.fn();

      const result = applyPersistedPosition(
        { ok: true, premiumStopPct: null }, pos, addPosition, undefined, onDropped,
      );

      expect(result.rejected).toBe(false);
      expect(onDropped).toHaveBeenCalledWith(4.5);
    });

    it('does NOT report a drop when the server applied the stop, or when none was asked for', () => {
      const addPosition = jest.fn();
      const onDropped = jest.fn();

      applyPersistedPosition(
        { ok: true, premiumStopPct: 0.6 },
        makePosition({ recId: 'REC-APPLIED', premiumStopDollar: 3 }),
        addPosition, undefined, onDropped,
      );
      applyPersistedPosition(
        { ok: true, premiumStopPct: null },
        makePosition({ recId: 'REC-INHERITS' }),   // no dollar stop requested
        addPosition, undefined, onDropped,
      );

      expect(onDropped).not.toHaveBeenCalled();
    });

    it('adopts the server ENTRY alongside the server fraction, so both engines fire at one price', () => {
      // ROUND 9 finding 2. The router replaces the submitted entry with its
      // save-time quote and derives pct against THAT. Adopting the fraction
      // while keeping the client's mid put the two engines on different
      // thresholds: card mid $5.20, typed stop $3.12, filled at $4.00 ->
      // server stores 0.78 and fires at $0.88, while a local row still
      // carrying 5.20 fires at 5.20 x 0.22 = $1.144. At a $1.00 quote the
      // frontend raises a PREMIUM_STOP toast that the backend does not.
      //
      // Round 7 rejected the sibling entry-limit finding on the identity
      // entry x (1 - dollar/entry) = entry - dollar. That holds only when ONE
      // entry is used for the derivation AND the threshold; here they differed,
      // and the implied dollar stop became $4.06 rather than the $3.12 typed.
      const pos = makePosition({ recId: 'REC-ENTRY-PAIR', entryPrice: 5.20, premiumStopDollar: 3.12 });
      const addPosition = jest.fn();

      applyPersistedPosition(
        { ok: true, premiumStopPct: 0.78, entryPrice: 4.00 }, pos, addPosition,
      );

      const row = addPosition.mock.calls[0][0] as typeof pos;
      expect(row.premiumStopPct).toBeCloseTo(0.78, 10);
      expect(row.entryPrice).toBeCloseTo(4.00, 10);
      // The pair reproduces the DOLLAR the user actually typed...
      expect(premiumStopThresholdPrice(row.entryPrice, row.premiumStopPct!))
        .toBeCloseTo(4.00 - 3.12, 10);
      // ...and matches what the backend computes off its own stored row.
      expect(premiumStopThresholdPrice(4.00, 0.78)).toBeCloseTo(
        premiumStopThresholdPrice(row.entryPrice, row.premiumStopPct!), 10,
      );
    });

    it('addPosition reports a dropped premium stop, so the basket path can say so too', async () => {
      // ROUND 9 finding 7. The notice covered 2 of the 4 create paths: it was
      // wired on placeLimitPaper and placeMarketPaper, while the BASKET path
      // calls addPosition, whose result carried no premium-stop outcome at all
      // -- so it could not report the fallback even in principle. The row
      // inherits the 60% global, which is TIGHTER than the stop asked for.
      const fetchMock = jest.fn().mockResolvedValue({
        ok: true, json: async () => ({ premiumStopPct: null, entryPrice: 4.2 }),
      });
      (global as unknown as { fetch: jest.Mock }).fetch = fetchMock;

      const { result } = renderHook(() => usePortfolioStore());
      act(() => { usePortfolioStore.setState({ positions: [] }); });

      let res!: Awaited<ReturnType<typeof result.current.addPosition>>;
      await act(async () => {
        res = await result.current.addPosition(
          makePosition({ recId: 'REC-BASKET-DROP', premiumStopDollar: 4.5 }),
        );
      });

      expect(res.status).toBe('ok');
      expect(res.premiumStopDropped).toBe(4.5);
    });

    it('addPosition reports NO drop when the server applied the stop', async () => {
      const fetchMock = jest.fn().mockResolvedValue({
        ok: true, json: async () => ({ premiumStopPct: 0.6, entryPrice: 4.2 }),
      });
      (global as unknown as { fetch: jest.Mock }).fetch = fetchMock;

      const { result } = renderHook(() => usePortfolioStore());
      act(() => { usePortfolioStore.setState({ positions: [] }); });

      let res!: Awaited<ReturnType<typeof result.current.addPosition>>;
      await act(async () => {
        res = await result.current.addPosition(
          makePosition({ recId: 'REC-BASKET-OK', premiumStopDollar: 2.0 }),
        );
      });

      expect(res.premiumStopDropped).toBeUndefined();
    });

    it('leaves the entry alone when the server did not report one', () => {
      // A response without a usable entry must not blank the row's own.
      const pos = makePosition({ recId: 'REC-NO-ENTRY', entryPrice: 5.20 });
      const addPosition = jest.fn();

      applyPersistedPosition({ ok: true, premiumStopPct: 0.6 }, pos, addPosition);

      expect((addPosition.mock.calls[0][0] as typeof pos).entryPrice).toBeCloseTo(5.20, 10);
    });

    it('rejected: does NOT call addPosition at all, and surfaces the detail for the caller to show', () => {
      const pos = makePosition({ recId: 'REC-REJECTED' });
      const addPosition = jest.fn();

      const result = applyPersistedPosition({ ok: false, detail: 'exposure limit exceeded' }, pos, addPosition);

      expect(result).toEqual({ rejected: true, detail: 'exposure limit exceeded' });
      expect(addPosition).not.toHaveBeenCalled();
    });

    it('confirmed success: skips addPosition\'s own POST via skipPost, since persistPosition already saved it', () => {
      const pos = makePosition({ recId: 'REC-OK' });
      const addPosition = jest.fn();
      const onAdjusted = jest.fn();

      const result = applyPersistedPosition({ ok: true }, pos, addPosition, onAdjusted);

      expect(result.rejected).toBe(false);
      // `premiumStopPct: null` is carried onto the row (piece 4) — the server
      // derives it from the dollar stop and a response without one means
      // "inherit the global".
      expect(addPosition).toHaveBeenCalledWith({ ...pos, premiumStopPct: null }, { skipPost: true });
      expect(onAdjusted).not.toHaveBeenCalled();
    });

    it('confirmed success with an adjusted quantity: calls the onAdjusted callback with the backend-reported qty', () => {
      const pos = makePosition({ recId: 'REC-ADJUSTED' });
      const addPosition = jest.fn();
      const onAdjusted = jest.fn();

      applyPersistedPosition({ ok: true, adjustedQty: 3 }, pos, addPosition, onAdjusted);

      expect(onAdjusted).toHaveBeenCalledWith(3);
      expect(addPosition).toHaveBeenCalledWith({ ...pos, premiumStopPct: null }, { skipPost: true });
    });

    it('carries the server-derived premium stop onto the row it adds locally', () => {
      // The client posts DOLLARS; only the server knows the fraction, because
      // only the server knows the entry price it persisted. Dropping it left
      // the local row inheriting the global until the next 30s sync, so the
      // in-app alert engine and the backend generator armed the same position
      // at two different percentages.
      const pos = makePosition({ recId: 'REC-PS' });
      const addPosition = jest.fn();

      applyPersistedPosition({ ok: true, premiumStopPct: 0.78 }, pos, addPosition);

      expect(addPosition).toHaveBeenCalledWith(
        { ...pos, premiumStopPct: 0.78 }, { skipPost: true },
      );
    });

    it('regression guard: a naive "skip addPosition whenever saved.ok would be truthy" bug would fail this — offline must never take the skipPost path', () => {
      // saved.ok is false here (network failure never reports ok:true — see persistPosition's
      // own doc comment), so this specifically proves the offline branch is keyed on
      // `saved.offline`, not on treating "not explicitly rejected" as success.
      const pos = makePosition({ recId: 'REC-REGRESSION' });
      const addPosition = jest.fn();

      applyPersistedPosition({ ok: false, offline: true }, pos, addPosition);

      expect(addPosition).not.toHaveBeenCalledWith(pos, { skipPost: true });
    });
  });

  // Every test below that needs the debounced patch to actually fire uses
  // `await jest.advanceTimersByTimeAsync(600)`, NOT `jest.advanceTimersByTime(600)`
  // followed by a bare `await Promise.resolve()`. The debounced callback chains
  // through `_flushOne` -> `patchPosition`'s `await fetch()` -> `await res.json()`
  // -> the outer `await patchPosition(...)` in `_flushOne` — more microtask turns
  // than a single `Promise.resolve()` unwinds. `advanceTimersByTimeAsync` yields
  // to the event loop after each timer fires, draining that whole chain before
  // the `act()` block returns; using the sync form here would leave assertions
  // that depend on a post-await side effect (e.g. `lastSyncError`) checking state
  // before it actually updates.
  describe('updatePosition persists to the backend', () => {
    beforeEach(() => {
      jest.useFakeTimers();
    });

    afterEach(() => {
      jest.runOnlyPendingTimers();
      jest.useRealTimers();
    });

    it('debounces a PATCH to /api/portfolio/{recId} after inactivity', async () => {
      const { result } = renderHook(() => usePortfolioStore());
      const pos = makePosition({ recId: 'REC-PATCH-1', contract: 'AAPL 190C 05/16' });
      act(() => {
        usePortfolioStore.setState({ positions: [pos] });
      });

      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockResolvedValue(jsonResponse({}));

      act(() => {
        result.current.updatePosition('AAPL 190C 05/16', { stop: 185 });
      });
      expect(global.fetch).not.toHaveBeenCalled();

      await act(async () => {
        // The async variant (not sync advanceTimersByTime + one Promise.resolve())
        // — see the note above the first test in this block for why.
        await jest.advanceTimersByTimeAsync(600);
      });

      expect(global.fetch).toHaveBeenCalledTimes(1);
      const [url, init] = (global.fetch as jest.Mock).mock.calls[0];
      expect(url).toContain('/api/portfolio/REC-PATCH-1');
      expect(init.method).toBe('PATCH');
      expect(JSON.parse(init.body)).toEqual({ stop: 185 });
    });

    it('sends the Feature D fields in the PATCH payload', async () => {
      const { result } = renderHook(() => usePortfolioStore());
      const pos = makePosition({ recId: 'REC-PATCH-FD', contract: 'AAPL 190C 05/16' });
      act(() => {
        usePortfolioStore.setState({ positions: [pos] });
      });
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockResolvedValue(jsonResponse({}));

      act(() => {
        result.current.updatePosition('AAPL 190C 05/16', {
          activeTpMethod: 'exit_plan_2r',
          resolvedTpPrice: 230,
          resolvedTpUpdatedAt: '2026-08-27T00:00:00.000Z',
          alertOverrides: { STOP_REACHED: false },
        });
      });
      await act(async () => {
        await jest.advanceTimersByTimeAsync(600);
      });

      const [, init] = (global.fetch as jest.Mock).mock.calls[0];
      expect(JSON.parse(init.body)).toEqual({
        activeTpMethod: 'exit_plan_2r',
        resolvedTpPrice: 230,
        resolvedTpUpdatedAt: '2026-08-27T00:00:00.000Z',
        alertOverrides: { STOP_REACHED: false },
      });
    });

    it('sends an explicit null resolvedTpPrice when switching back to the ladder', async () => {
      // `'resolvedTpPrice' in patch` (not a truthiness check) is what lets the
      // ladder CLEAR a stale snapshot — a dropped null would leave the backend
      // still alerting on the previous method's price.
      const { result } = renderHook(() => usePortfolioStore());
      const pos = makePosition({ recId: 'REC-PATCH-LADDER', contract: 'AAPL 190C 05/16' });
      act(() => {
        usePortfolioStore.setState({ positions: [pos] });
      });
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockResolvedValue(jsonResponse({}));

      act(() => {
        result.current.updatePosition('AAPL 190C 05/16', {
          activeTpMethod: 'ladder', resolvedTpPrice: null,
        });
      });
      await act(async () => {
        await jest.advanceTimersByTimeAsync(600);
      });

      expect(JSON.parse((global.fetch as jest.Mock).mock.calls[0][1].body))
        .toEqual({ activeTpMethod: 'ladder', resolvedTpPrice: null });
    });

    it('floors stop/structuralStop to null at the store level, not just in the drawer UI', async () => {
      // Round-4 audit finding: only the drawer's EditField coerced 0 -> null
      // inline before calling updatePosition — any OTHER caller reaching this
      // action directly (a future call site, a test, a bulk edit) would have
      // put stop: 0 straight into local state, which alertEngine.ts reads as
      // a permanent breach independent of what gets sent over the network.
      const { result } = renderHook(() => usePortfolioStore());
      const pos = makePosition({
        recId: 'REC-PATCH-FLOOR', contract: 'AAPL 190C 05/16', stop: 150, structuralStop: 148,
      });
      act(() => {
        usePortfolioStore.setState({ positions: [pos] });
      });
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockResolvedValue(jsonResponse({}));

      act(() => {
        result.current.updatePosition('AAPL 190C 05/16', { stop: 0, structuralStop: 0 });
      });

      // Local optimistic state is floored immediately, before the PATCH even fires.
      const local = usePortfolioStore.getState().positions.find((p) => p.recId === 'REC-PATCH-FLOOR');
      expect(local?.stop).toBeNull();
      expect(local?.structuralStop).toBeNull();

      await act(async () => {
        await jest.advanceTimersByTimeAsync(600);
      });

      expect(global.fetch).toHaveBeenCalledTimes(1);
      const [, init] = (global.fetch as jest.Mock).mock.calls[0];
      expect(JSON.parse(init.body)).toEqual({ stop: null, structuralStop: null });
    });

    it('coalesces rapid edits into a single PATCH with the merged fields', async () => {
      const { result } = renderHook(() => usePortfolioStore());
      const pos = makePosition({ recId: 'REC-PATCH-2', contract: 'AAPL 190C 05/16' });
      act(() => {
        usePortfolioStore.setState({ positions: [pos] });
      });
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockResolvedValue(jsonResponse({}));

      act(() => {
        result.current.updatePosition('AAPL 190C 05/16', { stop: 185 });
      });
      act(() => {
        jest.advanceTimersByTime(200);
        result.current.updatePosition('AAPL 190C 05/16', { structuralStop: 182 });
      });

      await act(async () => {
        // The async variant (not sync advanceTimersByTime + one Promise.resolve())
        // — see the note above the first test in this block for why.
        await jest.advanceTimersByTimeAsync(600);
      });

      expect(global.fetch).toHaveBeenCalledTimes(1);
      const [, init] = (global.fetch as jest.Mock).mock.calls[0];
      expect(JSON.parse(init.body)).toEqual({ stop: 185, structuralStop: 182 });
    });

    it('includes portfolioValue when the patch touches contracts (qty), for the backend risk re-check', async () => {
      const { result } = renderHook(() => usePortfolioStore());
      const pos = makePosition({ recId: 'REC-PATCH-QTY', contract: 'AAPL 190C 05/16' });
      act(() => {
        usePortfolioStore.setState({ positions: [pos] });
      });
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockResolvedValue(jsonResponse({}));

      act(() => {
        result.current.updatePosition('AAPL 190C 05/16', { contracts: 3 });
      });

      await act(async () => {
        await jest.advanceTimersByTimeAsync(600);
      });

      expect(global.fetch).toHaveBeenCalledTimes(1);
      const [, init] = (global.fetch as jest.Mock).mock.calls[0];
      // portfolioValue: 50000 is set on useRiskStore in the outer beforeEach.
      expect(JSON.parse(init.body)).toEqual({ qty: 3, portfolioValue: 50000 });
    });

    it('does not call the backend for a patch with no persistable fields', async () => {
      const { result } = renderHook(() => usePortfolioStore());
      const pos = makePosition({ recId: 'REC-PATCH-3', contract: 'AAPL 190C 05/16' });
      act(() => {
        usePortfolioStore.setState({ positions: [pos] });
      });
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockResolvedValue(jsonResponse({}));

      act(() => {
        result.current.updatePosition('AAPL 190C 05/16', { currentPrice: 5.5, pnlDollar: 10, pnlPct: 1 });
      });

      await act(async () => {
        // The async variant (not sync advanceTimersByTime + one Promise.resolve())
        // — see the note above the first test in this block for why.
        await jest.advanceTimersByTimeAsync(600);
      });

      expect(global.fetch).not.toHaveBeenCalled();
    });

    it('surfaces lastSyncError when the backend rejects the PATCH', async () => {
      const { result } = renderHook(() => usePortfolioStore());
      const pos = makePosition({ recId: 'REC-PATCH-4', contract: 'AAPL 190C 05/16', symbol: 'AAPL' });
      act(() => {
        usePortfolioStore.setState({ positions: [pos], lastSyncError: null });
      });
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockResolvedValue(jsonResponse({ detail: 'qty must be at least 1.' }, false, 422));

      act(() => {
        result.current.updatePosition('AAPL 190C 05/16', { contracts: 0 });
      });

      await act(async () => {
        // The async variant (not sync advanceTimersByTime + one Promise.resolve())
        // — see the note above the first test in this block for why.
        await jest.advanceTimersByTimeAsync(600);
      });

      expect(usePortfolioStore.getState().lastSyncError?.detail).toBe('qty must be at least 1.');
      expect(usePortfolioStore.getState().lastSyncError?.symbol).toBe('AAPL');
    });

    it('corrects local contracts and surfaces a notice when the backend soft-reduces a qty increase', async () => {
      const { result } = renderHook(() => usePortfolioStore());
      const pos = makePosition({ recId: 'REC-PATCH-ADJ', contract: 'AAPL 190C 05/16', contracts: 5 });
      act(() => {
        usePortfolioStore.setState({ positions: [pos], lastSyncError: null });
      });
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockResolvedValue(jsonResponse({ adjustedQty: 2 }));

      act(() => {
        result.current.updatePosition('AAPL 190C 05/16', { contracts: 5 });
      });

      await act(async () => {
        await jest.advanceTimersByTimeAsync(600);
      });

      const updated = usePortfolioStore.getState().positions.find((p) => p.recId === 'REC-PATCH-ADJ');
      expect(updated?.contracts).toBe(2);
      expect(usePortfolioStore.getState().lastSyncError?.detail).toContain('2 contracts');
    });

    it('reverts the optimistic update via a forced resync when the backend rejects the PATCH', async () => {
      const { result } = renderHook(() => usePortfolioStore());
      const pos = makePosition({
        recId: 'REC-PATCH-ROLLBACK', contract: 'AAPL 190C 05/16', symbol: 'AAPL', contracts: 5,
      });
      act(() => {
        usePortfolioStore.setState({ positions: [pos], lastSyncError: null });
      });

      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockImplementation((_url: string, init?: { method?: string }) => {
          if ((init?.method ?? 'GET') === 'PATCH') {
            return Promise.resolve(jsonResponse({ detail: 'exposure limit exceeded' }, false, 422));
          }
          // The forced resync (GET /api/portfolio) — the backend's true, unchanged qty.
          return Promise.resolve(jsonResponse([{
            ...makeBackendPosition(),
            recId: 'REC-PATCH-ROLLBACK', contract: 'AAPL 190C 05/16', symbol: 'AAPL', qty: 5,
          }]));
        });

      act(() => {
        result.current.updatePosition('AAPL 190C 05/16', { contracts: 20 });
      });
      // Optimistic update lands immediately, before the PATCH even fires.
      expect(usePortfolioStore.getState().positions.find((p) => p.recId === 'REC-PATCH-ROLLBACK')?.contracts).toBe(20);

      await act(async () => {
        await jest.advanceTimersByTimeAsync(600);
        await Promise.resolve();
        await Promise.resolve();
      });

      const calls = (global.fetch as jest.Mock).mock.calls;
      expect(calls.filter(([, init]) => init?.method === 'PATCH')).toHaveLength(1);
      expect(calls.filter(([, init]) => (init?.method ?? 'GET') === 'GET').length).toBeGreaterThanOrEqual(1);
      // The rejected value must not linger — the forced resync snaps it back
      // to what the backend actually holds, not just surface an error toast.
      expect(usePortfolioStore.getState().positions.find((p) => p.recId === 'REC-PATCH-ROLLBACK')?.contracts).toBe(5);
    });

    it('serializes overlapping PATCHes so an in-flight edit is never overtaken by a newer one', async () => {
      const { result } = renderHook(() => usePortfolioStore());
      const pos = makePosition({ recId: 'REC-PATCH-RACE', contract: 'AAPL 190C 05/16' });
      act(() => {
        usePortfolioStore.setState({ positions: [pos], lastSyncError: null });
      });

      const calls: Array<{ body: unknown; resolve: () => void }> = [];
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockImplementation((_url: string, init?: { body?: string }) => new Promise((resolve) => {
          calls.push({ body: JSON.parse(init!.body as string), resolve: () => resolve(jsonResponse({})) });
        }));

      act(() => {
        result.current.updatePosition('AAPL 190C 05/16', { stop: 100 });
      });
      await act(async () => {
        await jest.advanceTimersByTimeAsync(600);
      });
      expect(calls).toHaveLength(1); // first PATCH sent, left unresolved (in flight)

      // A second edit arrives WHILE the first PATCH is still in flight.
      act(() => {
        result.current.updatePosition('AAPL 190C 05/16', { stop: 90 });
      });
      await act(async () => {
        await jest.advanceTimersByTimeAsync(600);
      });
      // Must wait for the in-flight request rather than firing a second,
      // independent one whose response could land before the first's.
      expect(calls).toHaveLength(1);

      await act(async () => {
        calls[0].resolve();
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(calls).toHaveLength(2);
      expect(calls[1].body).toEqual({ stop: 90 });

      await act(async () => {
        calls[1].resolve();
        await Promise.resolve();
      });
    });

    it('syncFromBackend keeps the local value while a PATCH is in flight, not only while debounced', async () => {
      const { result } = renderHook(() => usePortfolioStore());
      const pos = makePosition({ recId: 'REC-PATCH-INFLIGHT', contract: 'AAPL 190C 05/16', stop: 100 });
      act(() => {
        usePortfolioStore.setState({ positions: [pos], lastSyncError: null });
      });

      let resolvePatch: (() => void) | null = null;
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockImplementation((_url: string, init?: { method?: string }) => {
          if ((init?.method ?? 'GET') === 'PATCH') {
            return new Promise((resolve) => { resolvePatch = () => resolve(jsonResponse({})); });
          }
          // The poll — backend still has the OLD stop, since the in-flight
          // PATCH hasn't landed yet.
          return Promise.resolve(jsonResponse([{
            ...makeBackendPosition(), recId: 'REC-PATCH-INFLIGHT', contract: 'AAPL 190C 05/16', stop: 100,
          }]));
        });

      act(() => {
        result.current.updatePosition('AAPL 190C 05/16', { stop: 95 });
      });
      await act(async () => {
        await jest.advanceTimersByTimeAsync(600);
      });
      expect(usePortfolioStore.getState().positions.find((p) => p.recId === 'REC-PATCH-INFLIGHT')?.stop).toBe(95);

      // The 30s poll fires while the PATCH above is still in flight.
      await act(async () => {
        await usePortfolioStore.getState().syncFromBackend();
      });
      expect(usePortfolioStore.getState().positions.find((p) => p.recId === 'REC-PATCH-INFLIGHT')?.stop).toBe(95);

      await act(async () => {
        resolvePatch?.();
        await Promise.resolve();
      });
    });

    it('does not surface an error or force a resync for a PATCH whose position was closed while in flight', async () => {
      const { result } = renderHook(() => usePortfolioStore());
      const pos = makePosition({ recId: 'REC-PATCH-CLOSED', contract: 'AAPL 190C 05/16' });
      act(() => {
        usePortfolioStore.setState({ positions: [pos], lastSyncError: null });
      });

      let resolvePatch: (() => void) | null = null;
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockImplementation((_url: string, init?: { method?: string }) => {
          if ((init?.method ?? 'GET') === 'PATCH') {
            return new Promise((resolve) => {
              resolvePatch = () => resolve(jsonResponse({ detail: 'rejected' }, false, 422));
            });
          }
          return Promise.resolve(jsonResponse([]));
        });

      act(() => {
        result.current.updatePosition('AAPL 190C 05/16', { stop: 100 });
      });
      await act(async () => {
        await jest.advanceTimersByTimeAsync(600);
      });
      // PATCH is now in flight, unresolved.

      // The position is removed locally (e.g. a close completing) while that
      // stale PATCH is still in the air — cancelPendingPositionPatch can only
      // drop a not-yet-sent edit, not one already sent.
      act(() => {
        usePortfolioStore.setState({ positions: [] });
      });

      await act(async () => {
        resolvePatch?.();
        await Promise.resolve();
        await Promise.resolve();
      });

      expect(usePortfolioStore.getState().lastSyncError).toBeNull();
      const getCalls = (global.fetch as jest.Mock).mock.calls.filter(
        ([, init]) => (init?.method ?? 'GET') === 'GET'
      );
      expect(getCalls).toHaveLength(0); // no moot forced resync for a row that's already gone
    });

    it('flushPendingPositionPatches sends immediately without waiting for the debounce', async () => {
      const { flushPendingPositionPatches } = await import('@/lib/portfolioStore');
      const { result } = renderHook(() => usePortfolioStore());
      const pos = makePosition({ recId: 'REC-PATCH-5', contract: 'AAPL 190C 05/16' });
      act(() => {
        usePortfolioStore.setState({ positions: [pos] });
      });
      (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
        .mockResolvedValue(jsonResponse({}));

      act(() => {
        result.current.updatePosition('AAPL 190C 05/16', { stop: 185 });
      });
      expect(global.fetch).not.toHaveBeenCalled();

      await act(async () => {
        flushPendingPositionPatches('REC-PATCH-5');
        await Promise.resolve();
      });

      expect(global.fetch).toHaveBeenCalledTimes(1);
    });

    it('closePosition cancels a pending patch instead of sending it after the DELETE', async () => {
      const { result } = renderHook(() => usePortfolioStore());
      const pos = makePosition({ recId: 'REC-PATCH-6', contract: 'AAPL 190C 05/16' });
      act(() => {
        usePortfolioStore.setState({ positions: [pos] });
      });
      const fetchMock = jest.fn().mockResolvedValue(jsonResponse({}));
      (global as unknown as { fetch: jest.Mock }).fetch = fetchMock;

      act(() => {
        result.current.updatePosition('AAPL 190C 05/16', { stop: 185 });
      });
      act(() => {
        result.current.closePosition('AAPL 190C 05/16');
      });

      await act(async () => {
        // The async variant (not sync advanceTimersByTime + one Promise.resolve())
        // — see the note above the first test in this block for why.
        await jest.advanceTimersByTimeAsync(600);
      });

      // Only the DELETE fired — the debounced PATCH for the same recId was cancelled.
      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(fetchMock.mock.calls[0][1]?.method).toBe('DELETE');
    });
  });
});

describe('portfolioStore — backend payload portfolioValue', () => {
  let fetchMock: jest.Mock;

  beforeEach(() => {
    act(() => {
      usePortfolioStore.setState({ positions: [] });
      useRiskStore.setState((s) => ({
        limits: { ...s.limits, portfolioValue: 73_000 },
      }));
    });
    fetchMock = jest.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({}) });
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  it('addPosition posts the riskStore-configured portfolioValue, not a hardcoded fallback', async () => {
    const { result } = renderHook(() => usePortfolioStore());
    act(() => {
      result.current.addPosition(makePosition());
    });
    // postPosition is fire-and-forget; flush microtasks
    await act(async () => { await Promise.resolve(); });

    expect(fetchMock).toHaveBeenCalled();
    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(body.portfolioValue).toBe(73_000);
  });

  it('persistPosition posts the riskStore-configured portfolioValue when called with no explicit value (matches Step 7 call sites)', async () => {
    const { persistPosition } = await import('@/lib/portfolioStore');
    await persistPosition(makePosition());

    expect(fetchMock).toHaveBeenCalled();
    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(body.portfolioValue).toBe(73_000);
  });

  it('syncToBackend posts the riskStore-configured portfolioValue for every local-only position (dashboard stale-cache recovery path)', async () => {
    act(() => {
      usePortfolioStore.setState({ positions: [makePosition(), makePosition({ symbol: 'MSFT' })] });
    });
    await act(async () => {
      await usePortfolioStore.getState().syncToBackend();
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    for (const call of fetchMock.mock.calls) {
      const body = JSON.parse(call[1].body as string);
      expect(body.portfolioValue).toBe(73_000);
    }
  });
});
