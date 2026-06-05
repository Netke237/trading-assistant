import { distToSegment, hitTestDrawing } from './hitTest';
import type { Drawing } from '@/types/overlays';

describe('hit-test geometry', () => {
  it('distToSegment is ~0 on the segment, large off it', () => {
    expect(distToSegment(5, 0, 0, 0, 10, 0)).toBeCloseTo(0);
    expect(distToSegment(5, 20, 0, 0, 10, 0)).toBeCloseTo(20);
  });
  it('hitTestDrawing flags an hline when cursor is near its y', () => {
    const d = { id: 'a', symbol: 'X', interval: '1D', kind: 'hline', points: [{ time: 0, price: 100 }], color: '#fff', width: 1, createdAt: '' } as Drawing;
    // toX irrelevant for hline; toY maps price 100 -> 50px
    const hit = hitTestDrawing(d, 200, 52, () => 0, () => 50, 6);
    expect(hit.hit).toBe(true);
  });
});
