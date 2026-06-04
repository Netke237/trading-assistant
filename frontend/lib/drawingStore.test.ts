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
});
