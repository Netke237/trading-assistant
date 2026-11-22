import { usePerformanceStore, type ClosedPosition } from '../performanceStore';

const row = (id: string): ClosedPosition => ({
  id, recId: `rec-${id}`, symbol: 'NFLX', contract: 'NFLX|82|2027-01-15|C', direction: 'long',
  entryPrice: 1, exitPrice: 2, exitDate: '2026-11-01', qtyClosed: 1,
  realizedPnlDollar: 100, realizedPnlPct: 100, closedAt: '2026-11-01T00:00:00Z',
});

describe('performanceStore.removeHistory', () => {
  const originalFetch = global.fetch;
  beforeEach(() => { usePerformanceStore.setState({ history: [row('a'), row('b')] }); });
  afterEach(() => { global.fetch = originalFetch; });

  const ids = () => usePerformanceStore.getState().history.map((h) => h.id);

  it.each([200, 204, 404])('drops the row and returns true on %i', async (status) => {
    const fetchMock = jest.fn().mockResolvedValue({ ok: status >= 200 && status < 300, status });
    global.fetch = fetchMock as unknown as typeof fetch;
    const removed = await usePerformanceStore.getState().removeHistory('a');
    expect(removed).toBe(true);
    expect(ids()).toEqual(['b']);
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/portfolio\/history\/a$/);
    expect(fetchMock.mock.calls[0][1]).toEqual({ method: 'DELETE' });
  });

  it('keeps the row and returns false on 500', async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 500 }) as unknown as typeof fetch;
    const removed = await usePerformanceStore.getState().removeHistory('a');
    expect(removed).toBe(false);
    expect(ids()).toEqual(['a', 'b']);
  });

  it('keeps the row and returns false on a network error', async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error('offline')) as unknown as typeof fetch;
    const removed = await usePerformanceStore.getState().removeHistory('a');
    expect(removed).toBe(false);
    expect(ids()).toEqual(['a', 'b']);
  });
});
