import { useDrawingStore } from './drawingStore';
import type { Drawing } from '@/types/overlays';

// avoid real network in unit test
beforeAll(() => { global.fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve([]) })) as unknown as typeof fetch; });
beforeEach(() => { useDrawingStore.setState({ drawings: [] }); });

const d = (id: string): Drawing => ({ id, symbol: 'AAPL', interval: '1D', kind: 'hline', points: [{ time: 0, price: 100 }], color: '#fff', width: 1, createdAt: '2026-06-04T00:00:00Z' });

describe('drawingStore', () => {
  it('adds and removes a drawing', () => {
    useDrawingStore.getState().addDrawing(d('x1'));
    expect(useDrawingStore.getState().drawings).toHaveLength(1);
    useDrawingStore.getState().removeDrawing('x1');
    expect(useDrawingStore.getState().drawings).toHaveLength(0);
  });
  it('clearForSymbol removes only matching symbol+interval', () => {
    useDrawingStore.getState().addDrawing(d('a'));
    useDrawingStore.getState().addDrawing({ ...d('b'), symbol: 'MSFT' });
    useDrawingStore.getState().clearForSymbol('AAPL', '1D');
    expect(useDrawingStore.getState().drawings.map((x) => x.id)).toEqual(['b']);
  });
  it('clearForSymbol calls DELETE API for each matching drawing', () => {
    (global.fetch as jest.Mock).mockClear();
    useDrawingStore.getState().addDrawing(d('c1'));
    useDrawingStore.getState().addDrawing(d('c2'));
    useDrawingStore.getState().addDrawing({ ...d('c3'), symbol: 'MSFT' });
    (global.fetch as jest.Mock).mockClear();
    useDrawingStore.getState().clearForSymbol('AAPL', '1D');
    expect(useDrawingStore.getState().drawings.map((x) => x.id)).toEqual(['c3']);
    expect(global.fetch).toHaveBeenCalledTimes(2);
    expect((global.fetch as jest.Mock).mock.calls[0][0]).toContain('/chart/drawings/c1');
    expect((global.fetch as jest.Mock).mock.calls[0][1]).toMatchObject({ method: 'DELETE' });
    expect((global.fetch as jest.Mock).mock.calls[1][0]).toContain('/chart/drawings/c2');
    expect((global.fetch as jest.Mock).mock.calls[1][1]).toMatchObject({ method: 'DELETE' });
  });
  it('updateDrawing updates local state and re-POSTs to API', () => {
    (global.fetch as jest.Mock).mockClear();
    useDrawingStore.getState().addDrawing(d('u1'));
    (global.fetch as jest.Mock).mockClear();
    useDrawingStore.getState().updateDrawing('u1', { color: '#ff0000' });
    const updated = useDrawingStore.getState().drawings.find((x) => x.id === 'u1');
    expect(updated?.color).toBe('#ff0000');
    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect((global.fetch as jest.Mock).mock.calls[0][0]).toContain('/chart/drawings');
    expect((global.fetch as jest.Mock).mock.calls[0][1]).toMatchObject({ method: 'POST' });
  });
});
