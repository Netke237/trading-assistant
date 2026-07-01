import { HorizontalLinePrimitive } from './HorizontalLinePrimitive';
import { TrendLinePrimitive } from './TrendLinePrimitive';
import { RectanglePrimitive } from './RectanglePrimitive';
import { TextPrimitive } from './TextPrimitive';
import { ArrowPrimitive } from './ArrowPrimitive';
import { ArrowUpPrimitive } from './ArrowUpPrimitive';
import { ArrowDownPrimitive } from './ArrowDownPrimitive';
import { CirclePrimitive } from './CirclePrimitive';
import { PathPrimitive } from './PathPrimitive';
import type { Drawing } from '@/types/overlays';

const baseDrawing = (price = 100): Drawing => ({
  id: 'test', symbol: 'SPY', interval: '1D' as const,
  kind: 'hline', points: [{ time: 1000, price }],
  color: '#fff', width: 1, createdAt: '',
});

const trendDrawing = (p0 = 100, p1 = 110): Drawing => ({
  id: 'test', symbol: 'SPY', interval: '1D' as const,
  kind: 'trendline',
  points: [{ time: 1000, price: p0 }, { time: 2000, price: p1 }],
  color: '#fff', width: 1, createdAt: '',
});

const mockParam = (requestUpdate: jest.Mock) => ({
  chart: { timeScale: () => ({ timeToCoordinate: jest.fn(() => null) }) },
  series: { priceToCoordinate: jest.fn(() => null) },
  requestUpdate,
  paneId: '0',
} as never);

describe('HorizontalLinePrimitive.update()', () => {
  it('calls requestUpdate on update after attach', () => {
    const req = jest.fn();
    const prim = new HorizontalLinePrimitive(baseDrawing());
    prim.attached(mockParam(req));
    req.mockClear();
    prim.update(baseDrawing(200));
    expect(req).toHaveBeenCalledTimes(1);
  });

  it('does not throw when called before attach', () => {
    const prim = new HorizontalLinePrimitive(baseDrawing());
    expect(() => prim.update(baseDrawing(200))).not.toThrow();
  });
});

describe('TrendLinePrimitive.update()', () => {
  it('calls requestUpdate on update after attach', () => {
    const req = jest.fn();
    const prim = new TrendLinePrimitive(trendDrawing());
    prim.attached(mockParam(req));
    req.mockClear();
    prim.update(trendDrawing(150, 160));
    expect(req).toHaveBeenCalledTimes(1);
  });
});

describe('RectanglePrimitive.update()', () => {
  it('calls requestUpdate on update after attach', () => {
    const req = jest.fn();
    const d: Drawing = { ...trendDrawing(), kind: 'rect' };
    const prim = new RectanglePrimitive(d);
    prim.attached(mockParam(req));
    req.mockClear();
    prim.update({ ...d, color: '#f00' });
    expect(req).toHaveBeenCalledTimes(1);
  });
});

describe('TextPrimitive.update()', () => {
  it('calls requestUpdate on update after attach', () => {
    const req = jest.fn();
    const d: Drawing = { ...baseDrawing(), kind: 'text', text: 'hello' };
    const prim = new TextPrimitive(d);
    prim.attached(mockParam(req));
    req.mockClear();
    prim.update({ ...d, text: 'world' });
    expect(req).toHaveBeenCalledTimes(1);
  });
});

const arrowDrawing = (): Drawing => ({
  id: 'a', symbol: 'SPY', interval: '1D' as const,
  kind: 'arrow',
  points: [{ time: 1000, price: 100 }, { time: 2000, price: 110 }],
  color: '#fff', width: 1, createdAt: '',
});

const onePointDrawing = (kind: Drawing['kind']): Drawing => ({
  id: 'b', symbol: 'SPY', interval: '1D' as const,
  kind,
  points: [{ time: 1000, price: 100 }],
  color: '#fff', width: 1, createdAt: '',
});

const pathDrawing = (): Drawing => ({
  id: 'c', symbol: 'SPY', interval: '1D' as const,
  kind: 'path',
  points: [{ time: 1000, price: 100 }, { time: 2000, price: 110 }, { time: 3000, price: 105 }],
  color: '#fff', width: 1, createdAt: '',
});

describe('ArrowPrimitive.update()', () => {
  it('calls requestUpdate after attach', () => {
    const req = jest.fn();
    const prim = new ArrowPrimitive(arrowDrawing());
    prim.attached(mockParam(req));
    req.mockClear();
    prim.update(arrowDrawing());
    expect(req).toHaveBeenCalledTimes(1);
  });
  it('does not throw before attach', () => {
    const prim = new ArrowPrimitive(arrowDrawing());
    expect(() => prim.update(arrowDrawing())).not.toThrow();
  });
});

describe('ArrowUpPrimitive.update()', () => {
  it('calls requestUpdate after attach', () => {
    const req = jest.fn();
    const prim = new ArrowUpPrimitive(onePointDrawing('arrow_up'));
    prim.attached(mockParam(req));
    req.mockClear();
    prim.update(onePointDrawing('arrow_up'));
    expect(req).toHaveBeenCalledTimes(1);
  });
  it('does not throw before attach', () => {
    const prim = new ArrowUpPrimitive(onePointDrawing('arrow_up'));
    expect(() => prim.update(onePointDrawing('arrow_up'))).not.toThrow();
  });
});

describe('ArrowDownPrimitive.update()', () => {
  it('calls requestUpdate after attach', () => {
    const req = jest.fn();
    const prim = new ArrowDownPrimitive(onePointDrawing('arrow_down'));
    prim.attached(mockParam(req));
    req.mockClear();
    prim.update(onePointDrawing('arrow_down'));
    expect(req).toHaveBeenCalledTimes(1);
  });
  it('does not throw before attach', () => {
    const prim = new ArrowDownPrimitive(onePointDrawing('arrow_down'));
    expect(() => prim.update(onePointDrawing('arrow_down'))).not.toThrow();
  });
});

describe('CirclePrimitive.update()', () => {
  it('calls requestUpdate after attach', () => {
    const req = jest.fn();
    const d: Drawing = { ...arrowDrawing(), kind: 'circle' };
    const prim = new CirclePrimitive(d);
    prim.attached(mockParam(req));
    req.mockClear();
    prim.update(d);
    expect(req).toHaveBeenCalledTimes(1);
  });
  it('does not throw before attach', () => {
    const d: Drawing = { ...arrowDrawing(), kind: 'circle' };
    const prim = new CirclePrimitive(d);
    expect(() => prim.update(d)).not.toThrow();
  });
});

describe('PathPrimitive.update()', () => {
  it('calls requestUpdate after attach', () => {
    const req = jest.fn();
    const prim = new PathPrimitive(pathDrawing());
    prim.attached(mockParam(req));
    req.mockClear();
    prim.update(pathDrawing());
    expect(req).toHaveBeenCalledTimes(1);
  });
  it('does not throw with single point before attach', () => {
    const d: Drawing = { ...pathDrawing(), points: [{ time: 1000, price: 100 }] };
    const prim = new PathPrimitive(d);
    expect(() => prim.update(d)).not.toThrow();
  });
});
