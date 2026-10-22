/*
 * STOCKS-HORIZON-T1 H6 -- a stock position raises TIME_STOP once it has been
 * held `holdMaxDays` (end-of-day rule: days held >= hold), mirroring the
 * backend's alert_generator. Options TIME_STOP (<= 3 DTE) is unchanged; a
 * stock row with no hold never fires it.
 */
import { act } from '@testing-library/react';
import { scanPortfolio, type AlertPosition } from '@/lib/alertEngine';
import { usePortfolioStore, persistPosition, migratePortfolioPersist } from '@/lib/portfolioStore';
import { buildPaperStockPosition } from '@/lib/paperTrade';

// Local noon, 2026-10-09: "today" for both the engine and the entry dates.
const NOW = new Date(2026, 9, 9, 12, 0, 0);

function stock(overrides: Partial<AlertPosition> = {}): AlertPosition {
  return {
    recId: 'r-stk', symbol: 'AAPL', contract: 'AAPL|STOCK',
    currentPrice: 100, currentStockPrice: 100, entryPrice: 100,
    stop: null, targets: [], dteRemaining: 0, dteTotal: 0, pnlPct: 0,
    direction: 'Bullish',
    entryDate: '2026-09-24',   // 15 days before NOW
    holdMaxDays: 15,
    ...overrides,
  };
}
const timeStops = (p: AlertPosition) => scanPortfolio([p]).filter((a) => a.alertType === 'TIME_STOP');

describe('alertEngine -- stock TIME_STOP at the hold', () => {
  beforeEach(() => { jest.useFakeTimers(); jest.setSystemTime(NOW); });
  afterEach(() => { jest.useRealTimers(); });

  it('held 15 days, hold 15 -> one TIME_STOP', () => {
    const out = timeStops(stock());
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({
      recId: 'r-stk', kind: 'Action', symbol: 'AAPL', alertType: 'TIME_STOP',
      reason: 'Time stop — AAPL held 15d (hold 15d)', referenceValue: 15,
      direction: 'Bullish', contract: 'AAPL|STOCK',
    });
  });

  it('held past the hold still fires', () => {
    expect(timeStops(stock({ holdMaxDays: 10 }))[0]?.reason).toBe('Time stop — AAPL held 15d (hold 10d)');
  });

  it('held 14 days, hold 15 -> none', () => {
    expect(timeStops(stock({ entryDate: '2026-09-25' }))).toEqual([]);
  });

  it('no hold -> never', () => {
    expect(timeStops(stock({ holdMaxDays: null, entryDate: '2025-01-01' }))).toEqual([]);
    expect(timeStops(stock({ holdMaxDays: undefined, entryDate: '2025-01-01' }))).toEqual([]);
  });

  it('a muted TIME_STOP raises nothing', () => {
    expect(timeStops(stock({ alertOverrides: { TIME_STOP: false } }))).toEqual([]);
    expect(scanPortfolio([stock()], { enabledTypes: [] }).some((a) => a.alertType === 'TIME_STOP')).toBe(false);
  });

  it('options TIME_STOP is unchanged', () => {
    const opt = stock({ contract: 'AAPL|190|2026-10-11|C', dteRemaining: 2, holdMaxDays: null });
    expect(timeStops(opt).map((a) => a.reason)).toEqual(['Time stop — AAPL 2 DTE']);
    expect(timeStops({ ...opt, dteRemaining: 30 })).toEqual([]);
  });
});

describe('portfolioStore -- holdMaxDays', () => {
  const originalFetch = global.fetch;
  afterEach(() => { global.fetch = originalFetch; });

  it('persist version is 7', () => {
    expect(usePortfolioStore.persist.getOptions().version).toBe(7);
  });

  it('migrate v6 -> v7 sets holdMaxDays null on stored rows; a v7 row keeps its value', () => {
    const migrate = (rows: Record<string, unknown>[], version: number) =>
      (migratePortfolioPersist({ positions: rows }, version) as { positions: Record<string, unknown>[] }).positions;
    const [old] = migrate([{ contract: 'A|STOCK', syncStatus: 'synced' }], 6);
    expect(old!.holdMaxDays).toBeNull();
    const [cur] = migrate([{ contract: 'A|STOCK', syncStatus: 'synced', holdMaxDays: 45 }], 7);
    expect(cur!.holdMaxDays).toBe(45);
  });

  it('the create body carries the hold; a position without one sends null', async () => {
    const bodies: Record<string, unknown>[] = [];
    global.fetch = jest.fn().mockImplementation(async (_url: string, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body));
      bodies.push(body);
      return { ok: true, status: 201, json: async () => body };
    }) as unknown as typeof fetch;
    await persistPosition({ ...buildPaperStockPosition('AAPL', 100, 5, 'Bullish'), holdMaxDays: 185 });
    await persistPosition(buildPaperStockPosition('MSFT', 100, 5, 'Bullish'));
    expect(bodies.map((b) => b.holdMaxDays)).toEqual([185, null]);
  });

  it('a backend row carries holdMaxDays into the store', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true, status: 200,
      json: async () => ([{
        id: 'x', recId: 'REC-1', symbol: 'AAPL', contract: 'AAPL|STOCK', direction: 'Bullish',
        entryPrice: 100, qty: 5, entryDate: '2026-10-01', stop: null, targets: [],
        dteTotal: null, createdAt: '2026-10-01T00:00:00Z', holdMaxDays: 60,
      }]),
    }) as unknown as typeof fetch;
    act(() => usePortfolioStore.setState({ positions: [] }));
    await act(async () => { await usePortfolioStore.getState().syncFromBackend(true); });
    expect(usePortfolioStore.getState().positions.map((p) => p.holdMaxDays)).toEqual([60]);
  });
});
