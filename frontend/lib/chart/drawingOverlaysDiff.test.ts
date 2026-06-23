import { diffDrawings } from './drawingOverlaysDiff';
import type { AttachedEntry } from './drawingOverlaysDiff';
import type { Drawing } from '@/types/overlays';

const d = (id: string, price = 100): Drawing => ({
  id, symbol: 'SPY', interval: '1D' as const,
  kind: 'hline', points: [{ time: 1000, price }],
  color: '#fff', width: 1, createdAt: '',
});

const mockEntry = (drawing: Drawing): AttachedEntry => ({
  primitive: { update: jest.fn(), attached: jest.fn(), paneViews: jest.fn(() => []) },
  drawing,
});

describe('diffDrawings', () => {
  it('adds all drawings when prev map is empty', () => {
    const result = diffDrawings(new Map(), [d('a'), d('b')]);
    expect(result.toAdd).toHaveLength(2);
    expect(result.toRemove).toHaveLength(0);
    expect(result.toUpdate).toHaveLength(0);
  });

  it('removes drawings absent from next', () => {
    const prev = new Map([['a', mockEntry(d('a'))]]);
    const result = diffDrawings(prev, []);
    expect(result.toRemove).toHaveLength(1);
    expect(result.toRemove[0].drawing.id).toBe('a');
    expect(result.toAdd).toHaveLength(0);
  });

  it('updates drawings whose object reference changed', () => {
    const original = d('a', 100);
    const updated = d('a', 200);
    const prev = new Map([['a', mockEntry(original)]]);
    const result = diffDrawings(prev, [updated]);
    expect(result.toUpdate).toHaveLength(1);
    expect(result.toUpdate[0].drawing).toBe(updated);
    expect(result.toAdd).toHaveLength(0);
    expect(result.toRemove).toHaveLength(0);
  });

  it('skips update when drawing reference is identical', () => {
    const drawing = d('a');
    const prev = new Map([['a', mockEntry(drawing)]]);
    const result = diffDrawings(prev, [drawing]);
    expect(result.toUpdate).toHaveLength(0);
    expect(result.toAdd).toHaveLength(0);
    expect(result.toRemove).toHaveLength(0);
  });

  it('deduplicates drawings with the same id in next (last entry wins)', () => {
    const result = diffDrawings(new Map(), [d('a', 100), d('a', 200)]);
    expect(result.toAdd).toHaveLength(1);
    expect(result.toAdd[0].points[0].price).toBe(200);
    expect(result.toRemove).toHaveLength(0);
    expect(result.toUpdate).toHaveLength(0);
  });

  it('handles add + remove + update in one call', () => {
    const existing = d('a');
    const modified = d('a', 999);
    const toBeRemoved = d('b');
    const toBeAdded = d('c');
    const prev = new Map([
      ['a', mockEntry(existing)],
      ['b', mockEntry(toBeRemoved)],
    ]);
    const result = diffDrawings(prev, [modified, toBeAdded]);
    expect(result.toAdd).toHaveLength(1);
    expect(result.toAdd[0].id).toBe('c');
    expect(result.toRemove).toHaveLength(1);
    expect(result.toRemove[0].drawing.id).toBe('b');
    expect(result.toUpdate).toHaveLength(1);
    expect(result.toUpdate[0].drawing.id).toBe('a');
  });
});
