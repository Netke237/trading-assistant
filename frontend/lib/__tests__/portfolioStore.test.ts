import { renderHook, act } from '@testing-library/react';
import { usePortfolioStore, persistPosition } from '@/lib/portfolioStore';
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
    act(() => {
      usePortfolioStore.setState({ positions: [] });
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

  it('adds a new position', () => {
    const { result } = renderHook(() => usePortfolioStore());

    act(() => {
      result.current.addPosition(makePosition());
    });
    expect(result.current.positions).toHaveLength(1);
    expect(result.current.positions[0].symbol).toBe('AAPL');
  });

  it('merges duplicate contracts by adding contract counts', () => {
    const { result } = renderHook(() => usePortfolioStore());

    act(() => {
      result.current.addPosition(makePosition({ contracts: 2 }));
    });
    expect(result.current.positions[0].contracts).toBe(2);

    act(() => {
      result.current.addPosition(makePosition({ contracts: 3 }));
    });
    expect(result.current.positions).toHaveLength(1);
    expect(result.current.positions[0].contracts).toBe(5);
  });

  it('keeps earlier entry data when merging duplicates', () => {
    const { result } = renderHook(() => usePortfolioStore());

    act(() => {
      result.current.addPosition(makePosition({ entryPrice: 4.15, currentPrice: 5.02 }));
    });

    act(() => {
      result.current.addPosition(makePosition({ entryPrice: 4.50, currentPrice: 5.50 }));
    });

    expect(result.current.positions[0].entryPrice).toBe(4.15);
    expect(result.current.positions[0].currentPrice).toBe(5.02);
  });

  it('updates a position by contract', () => {
    const { result } = renderHook(() => usePortfolioStore());

    act(() => {
      result.current.addPosition(makePosition());
    });

    act(() => {
      result.current.updatePosition('AAPL 190C 05/16', { currentPrice: 6.0, pnlDollar: 1200 });
    });

    expect(result.current.positions[0].currentPrice).toBe(6.0);
    expect(result.current.positions[0].pnlDollar).toBe(1200);
    expect(result.current.positions[0].symbol).toBe('AAPL');
  });

  it('closes a position by contract', () => {
    const { result } = renderHook(() => usePortfolioStore());

    act(() => {
      result.current.addPosition(makePosition());
      result.current.addPosition(makePosition({ symbol: 'MSFT', contract: 'MSFT 420C 06/20' }));
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
  it('merges a re-add of the same contract even when entryDate differs', () => {
    const { result } = renderHook(() => usePortfolioStore());

    act(() => {
      result.current.addPosition(makePosition({ entryDate: '2026-04-08', entryPrice: 4.15, contracts: 2 }));
    });
    act(() => {
      result.current.addPosition(makePosition({ entryDate: '2026-04-09', entryPrice: 6.0, contracts: 3 }));
    });

    expect(result.current.positions).toHaveLength(1);
    expect(result.current.positions[0].contracts).toBe(5);
    // Cost basis stays at the original fill — the backend 409s the second POST
    // and keeps the first, so averaging here would diverge from the server.
    expect(result.current.positions[0].entryPrice).toBe(4.15);
    expect(result.current.positions[0].entryDate).toBe('2026-04-08');
  });

  it('does not merge different contracts on the same symbol', () => {
    const { result } = renderHook(() => usePortfolioStore());

    act(() => {
      result.current.addPosition(makePosition({ contract: 'AAPL 190C 05/16' }));
      result.current.addPosition(makePosition({ contract: 'AAPL 200C 05/16' }));
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

  it('keeps an in-flight local position for a contract the backend has not seen', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => [makeBackendPosition()],
    }) as unknown as typeof fetch;

    act(() => {
      usePortfolioStore.setState({
        positions: [makePosition({ symbol: 'MSFT', contract: 'MSFT 420C 06/20', recId: 'REC-INFLIGHT' })],
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
});
