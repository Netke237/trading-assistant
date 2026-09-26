/**
 * P2 (premium stop & position editing) -- portfolioStore items P2-01, P2-06,
 * P2-07, P2-08, P2-09 and P2-10. Plan:
 * docs/superpowers/plans/2026-09-25-p2-premium-stop-position-editing-plan.md
 */
import { act } from '@testing-library/react';
import {
  usePortfolioStore, migratePortfolioPersist, applyPersistedPosition, withServerEntry,
} from '@/lib/portfolioStore';
import { useRiskStore } from '@/lib/riskStore';
import type { PortfolioPosition } from '@/types/domain';

let n = 0;
const pos = (o: Partial<PortfolioPosition> = {}): PortfolioPosition => ({
  symbol: 'AAPL', contract: `AAPL|190|2026-05-16|C${++n}`, direction: 'Bullish',
  entryDate: '2026-04-08', expiry: '2026-05-16', dteRemaining: 28, dteTotal: 38,
  entryPrice: 5.20, currentPrice: 5.20, pnlDollar: 0, pnlPct: 0,
  stop: 180, targets: [], status: 'PASS', contracts: 1, recId: `REC-P2-${n}`,
  ...o,
});
const json = (body: unknown, status = 201) =>
  ({ ok: status < 400, status, json: async () => body }) as unknown as Response;
const postBodies = () => (global.fetch as jest.Mock).mock.calls
  .filter(([, init]) => (init as RequestInit | undefined)?.method === 'POST')
  .map(([, init]) => JSON.parse((init as RequestInit).body as string));

const originalFetch = global.fetch;
beforeEach(() => {
  useRiskStore.setState({ limits: { ...useRiskStore.getState().limits, portfolioValue: 50000 } } as never);
  act(() => {
    usePortfolioStore.setState({
      positions: [], lastSyncError: null, lastPremiumStopDropped: null, premiumStopDropQueue: [],
    });
  });
});
afterEach(() => { global.fetch = originalFetch; localStorage.clear(); });

describe('P2-06 -- premiumStopDollar is dropped on every promotion to synced', () => {
  it('skipPost promotion drops it', async () => {
    global.fetch = jest.fn();
    await act(async () => {
      await usePortfolioStore.getState().addPosition(pos({ premiumStopDollar: 2 }), { skipPost: true });
    });
    const row = usePortfolioStore.getState().positions[0]!;
    expect(row.syncStatus).toBe('synced');
    expect('premiumStopDollar' in row).toBe(false);
  });

  it('ok-path promotion drops it', async () => {
    global.fetch = jest.fn().mockResolvedValue(json({ premiumStopPct: 0.4, entryPrice: 5.0 }));
    await act(async () => {
      await usePortfolioStore.getState().addPosition(pos({ premiumStopDollar: 2 }));
    });
    const row = usePortfolioStore.getState().positions[0]!;
    expect(row.syncStatus).toBe('synced');
    expect('premiumStopDollar' in row).toBe(false);
  });
});

describe('P2-07 -- migrate gates each step by version; v5 -> v6 cleans synced rows', () => {
  const migrate = (rows: Record<string, unknown>[], version: number) =>
    (migratePortfolioPersist({ positions: rows }, version) as { positions: Record<string, unknown>[] }).positions;

  it('version 5: a synced row loses premiumStopDollar; a pending row keeps it', () => {
    const [synced, pending] = migrate([
      { contract: 'A', syncStatus: 'synced', premiumStopDollar: 2, premiumStopPct: 0.4 },
      { contract: 'B', syncStatus: 'pending', premiumStopDollar: 3 },
    ], 5);
    expect('premiumStopDollar' in synced!).toBe(false);
    expect(pending!.premiumStopDollar).toBe(3);
  });

  it('version 5: premiumStopPct undefined is NOT rewritten (v2->v3 is gated)', () => {
    const [row] = migrate([{ contract: 'A', syncStatus: 'synced' }], 5);
    expect('premiumStopPct' in row!).toBe(false);
  });

  it('version 2: premiumStopPct undefined IS normalised to null', () => {
    const [row] = migrate([{ contract: 'A', syncStatus: 'synced' }], 2);
    expect(row!.premiumStopPct).toBeNull();
  });

  it('version 3: the v3->v4 stopIsUserSet normalisation runs; version 4: it does not', () => {
    const [v3] = migrate([{ contract: 'A', syncStatus: 'synced' }], 3);
    expect(v3!.stopIsUserSet).toBe(false);
    const [v4] = migrate([{ contract: 'A', syncStatus: 'synced' }], 4);
    expect('stopIsUserSet' in v4!).toBe(false);
  });
});

describe('P2-08 -- premium-stop drop notices queue instead of first-wins', () => {
  const pendingRow = (contract: string, symbol: string) =>
    pos({ contract, symbol, syncStatus: 'pending', premiumStopDollar: 4.5 });

  function mockSync(remote: unknown[]) {
    global.fetch = jest.fn((url: string, init?: RequestInit) => {
      if (init?.method === 'POST') return Promise.resolve(json({ premiumStopPct: null, entryPrice: 4.2 }));
      return Promise.resolve(json(remote, 200));
    }) as unknown as typeof fetch;
  }
  const backendRow = (contract: string, recId: string, symbol: string) => ({
    recId, symbol, contract, direction: 'Bullish', entryPrice: 4.2, qty: 1,
    entryDate: '2026-07-01', stop: null, targets: [], dteTotal: 30,
  });

  it('two drops in two cycles: the first is named, dismissing it names the second', async () => {
    act(() => usePortfolioStore.setState({ positions: [pendingRow('X|1|2026-06-19|C', 'XXX')] }));
    mockSync([]);
    await act(async () => { await usePortfolioStore.getState().syncFromBackend(true); });
    act(() => {
      usePortfolioStore.setState((s) => ({ positions: [...s.positions, pendingRow('Y|1|2026-06-19|C', 'YYY')] }));
    });
    mockSync([backendRow('X|1|2026-06-19|C', usePortfolioStore.getState().positions[0]!.recId, 'XXX')]);
    await act(async () => { await usePortfolioStore.getState().syncFromBackend(true); });
    expect(usePortfolioStore.getState().lastPremiumStopDropped?.symbol).toBe('XXX');
    act(() => usePortfolioStore.getState().clearPremiumStopDropped());
    expect(usePortfolioStore.getState().lastPremiumStopDropped?.symbol).toBe('YYY');
    act(() => usePortfolioStore.getState().clearPremiumStopDropped());
    expect(usePortfolioStore.getState().lastPremiumStopDropped).toBeNull();
  });

  it('closing the named position drops its notice and names the next one', async () => {
    act(() => usePortfolioStore.setState({
      positions: [pendingRow('X|1|2026-06-19|C', 'XXX'), pendingRow('Y|1|2026-06-19|C', 'YYY')],
    }));
    mockSync([]);
    await act(async () => { await usePortfolioStore.getState().syncFromBackend(true); });
    expect(usePortfolioStore.getState().lastPremiumStopDropped?.symbol).toBe('XXX');
    // Next GET: X is gone (closed elsewhere), Y is still held.
    const y = usePortfolioStore.getState().positions.find((p) => p.symbol === 'YYY')!;
    mockSync([backendRow('Y|1|2026-06-19|C', y.recId, 'YYY')]);
    act(() => usePortfolioStore.setState((s) => ({
      positions: s.positions.map((p) => ({ ...p, syncedAt: 0 })),
    })));
    await act(async () => { await usePortfolioStore.getState().syncFromBackend(true); });
    expect(usePortfolioStore.getState().lastPremiumStopDropped?.symbol).toBe('YYY');
  });
});

describe('P2-09 -- adopting the server entry resets the mark (R1-7)', () => {
  const card = () => pos({ entryPrice: 5.20, currentPrice: 5.20, pnlDollar: 0, pnlPct: 0 });
  const expectReset = (row: PortfolioPosition) => {
    expect(row.entryPrice).toBe(4.0);
    expect(row.currentPrice).toBe(4.0);
    expect(row.pnlDollar).toBe(0);
    expect(row.pnlPct).toBe(0);
  };

  it('applyPersistedPosition', async () => {
    global.fetch = jest.fn();
    const add = usePortfolioStore.getState().addPosition;
    await act(async () => {
      applyPersistedPosition({ ok: true, premiumStopPct: 0.5, entryPrice: 4.0 }, card(), add);
    });
    expectReset(usePortfolioStore.getState().positions[0]!);
  });

  it('addPosition ok path', async () => {
    global.fetch = jest.fn().mockResolvedValue(json({ premiumStopPct: 0.5, entryPrice: 4.0 }));
    await act(async () => { await usePortfolioStore.getState().addPosition(card()); });
    expectReset(usePortfolioStore.getState().positions[0]!);
  });

  it('pending retry in syncFromBackend', async () => {
    act(() => usePortfolioStore.setState({ positions: [{ ...card(), syncStatus: 'pending' }] }));
    global.fetch = jest.fn((url: string, init?: RequestInit) =>
      Promise.resolve(init?.method === 'POST' ? json({ premiumStopPct: 0.5, entryPrice: 4.0 }) : json([], 200)),
    ) as unknown as typeof fetch;
    await act(async () => { await usePortfolioStore.getState().syncFromBackend(true); });
    expectReset(usePortfolioStore.getState().positions[0]!);
  });

  it('no reported entry leaves the row untouched; a stock row moves currentStockPrice too', () => {
    const r = card();
    expect(withServerEntry(r, null)).toBe(r);
    const stock = withServerEntry(pos({ contract: 'AAPL|STOCK', currentStockPrice: 190 }), 180);
    expect(stock.currentStockPrice).toBe(180);
  });
});

describe('P2-10 -- a synced row re-POSTs without the scan anchor (R2-2)', () => {
  it('synced sends scanStockPrice null / stopIsUserSet false; pending keeps both', async () => {
    global.fetch = jest.fn().mockResolvedValue(json({}, 409));
    act(() => usePortfolioStore.setState({
      positions: [
        pos({ symbol: 'SYN', syncStatus: 'synced', scanStockPrice: 145, stopIsUserSet: true }),
        pos({ symbol: 'PEN', syncStatus: 'pending', scanStockPrice: 145, stopIsUserSet: true }),
      ],
    }));
    await act(async () => { await usePortfolioStore.getState().syncToBackend(); });
    const bySym = Object.fromEntries(postBodies().map((b) => [b.symbol, b]));
    expect(bySym.SYN).toMatchObject({ scanStockPrice: null, stopIsUserSet: false });
    expect(bySym.PEN).toMatchObject({ scanStockPrice: 145, stopIsUserSet: true });
  });
});

describe('P2-01 -- closing at $0 posts exitPrice 0, not null', () => {
  it('closePositionRemote(..., {exitPrice: 0})', async () => {
    const row = pos({ syncStatus: 'synced' });
    act(() => usePortfolioStore.setState({ positions: [row] }));
    global.fetch = jest.fn((url: string, init?: RequestInit) =>
      Promise.resolve(init?.method === 'POST' ? json({ ok: true }, 200) : json([], 200)),
    ) as unknown as typeof fetch;
    await act(async () => {
      await usePortfolioStore.getState().closePositionRemote(row.recId, { exitPrice: 0 });
    });
    const close = postBodies().find((b) => 'exitPrice' in b)!;
    expect(close.exitPrice).toBe(0);
  });
});
