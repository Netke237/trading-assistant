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

describe('hitTestDrawing — arrow', () => {
  const d: Drawing = {
    id: 'x', symbol: 'S', interval: '1D' as const,
    kind: 'arrow',
    points: [{ time: 0, price: 0 }, { time: 100, price: 0 }],
    color: '#fff', width: 1, createdAt: '',
  };
  const toX = (t: number) => t as number;
  const toY = (p: number) => p as number;
  it('hits near midpoint of line', () => {
    expect(hitTestDrawing(d, 50, 3, toX, toY, 8).hit).toBe(true);
  });
  it('misses far from line', () => {
    expect(hitTestDrawing(d, 50, 30, toX, toY, 8).hit).toBe(false);
  });
  it('handle p0 near first point', () => {
    expect(hitTestDrawing(d, 2, 2, toX, toY, 8).handle).toBe('p0');
  });
  it('handle p1 near second point', () => {
    expect(hitTestDrawing(d, 98, 2, toX, toY, 8).handle).toBe('p1');
  });
  it('returns { hit: false, handle: null } for degenerate arrow with only 1 point', () => {
    const single: Drawing = { ...d, points: [{ time: 0, price: 0 }] };
    expect(hitTestDrawing(single, 0, 0, toX, toY, 8)).toEqual({ hit: false, handle: null });
  });
});

describe('hitTestDrawing — trendline', () => {
  const toX = (t: number) => t as number;
  const toY = (p: number) => p as number;
  it('returns { hit: false, handle: null } for degenerate trendline with only 1 point', () => {
    const single: Drawing = {
      id: 'x', symbol: 'S', interval: '1D' as const,
      kind: 'trendline',
      points: [{ time: 0, price: 0 }],
      color: '#fff', width: 1, createdAt: '',
    };
    expect(hitTestDrawing(single, 0, 0, toX, toY, 8)).toEqual({ hit: false, handle: null });
  });
});

describe('hitTestDrawing — arrow_up', () => {
  const d: Drawing = {
    id: 'x', symbol: 'S', interval: '1D' as const,
    kind: 'arrow_up',
    points: [{ time: 50, price: 50 }],
    color: '#fff', width: 1, createdAt: '',
  };
  const toX = (t: number) => t as number;
  const toY = (p: number) => p as number;
  it('hits inside rendered triangle area (above price)', () => {
    expect(hitTestDrawing(d, 50, 38, toX, toY, 8).hit).toBe(true);
  });
  it('misses below price point (wrong direction)', () => {
    expect(hitTestDrawing(d, 50, 65, toX, toY, 8).hit).toBe(false);
  });
  it('misses far to the side', () => {
    expect(hitTestDrawing(d, 100, 38, toX, toY, 8).hit).toBe(false);
  });
});

describe('hitTestDrawing — arrow_down', () => {
  const d: Drawing = {
    id: 'x', symbol: 'S', interval: '1D' as const,
    kind: 'arrow_down',
    points: [{ time: 50, price: 50 }],
    color: '#fff', width: 1, createdAt: '',
  };
  const toX = (t: number) => t as number;
  const toY = (p: number) => p as number;
  it('hits inside rendered triangle area (below price)', () => {
    expect(hitTestDrawing(d, 50, 62, toX, toY, 8).hit).toBe(true);
  });
  it('misses above price point (wrong direction)', () => {
    expect(hitTestDrawing(d, 50, 35, toX, toY, 8).hit).toBe(false);
  });
  it('misses far to the side', () => {
    expect(hitTestDrawing(d, 100, 62, toX, toY, 8).hit).toBe(false);
  });
});

describe('hitTestDrawing — circle', () => {
  const d: Drawing = {
    id: 'x', symbol: 'S', interval: '1D' as const,
    kind: 'circle',
    points: [{ time: 100, price: 100 }, { time: 100, price: 150 }],
    color: '#fff', width: 1, createdAt: '',
  };
  const toX = (t: number) => t as number;
  const toY = (p: number) => p as number;
  it('hits near circumference (right side, tol=8)', () => {
    expect(hitTestDrawing(d, 150, 100, toX, toY, 8).hit).toBe(true);
  });
  it('hits at centre (inside filled area)', () => {
    expect(hitTestDrawing(d, 100, 100, toX, toY, 8).hit).toBe(true);
  });
  it('misses well outside', () => {
    expect(hitTestDrawing(d, 200, 100, toX, toY, 8).hit).toBe(false);
  });
  it('returns { hit: false, handle: null } for degenerate circle with only 1 point', () => {
    const single: Drawing = { ...d, points: [{ time: 100, price: 100 }] };
    expect(hitTestDrawing(single, 100, 100, toX, toY, 8)).toEqual({ hit: false, handle: null });
  });
});

describe('hitTestDrawing — path', () => {
  const d: Drawing = {
    id: 'x', symbol: 'S', interval: '1D' as const,
    kind: 'path',
    points: [{ time: 0, price: 0 }, { time: 50, price: 50 }, { time: 100, price: 0 }],
    color: '#fff', width: 1, createdAt: '',
  };
  const toX = (t: number) => t as number;
  const toY = (p: number) => p as number;
  it('hits near first segment', () => {
    expect(hitTestDrawing(d, 25, 28, toX, toY, 8).hit).toBe(true);
  });
  it('hits near second segment', () => {
    expect(hitTestDrawing(d, 75, 22, toX, toY, 8).hit).toBe(true);
  });
  it('misses far from all segments', () => {
    expect(hitTestDrawing(d, 50, 80, toX, toY, 8).hit).toBe(false);
  });
  it('returns false for single-point path', () => {
    const single: Drawing = { ...d, points: [{ time: 0, price: 0 }] };
    expect(hitTestDrawing(single, 0, 0, toX, toY, 8).hit).toBe(false);
  });
});
