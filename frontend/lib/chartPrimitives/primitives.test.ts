import { HorizontalLinePrimitive } from './HorizontalLinePrimitive';
import { TrendLinePrimitive } from './TrendLinePrimitive';
import { RectanglePrimitive } from './RectanglePrimitive';
import { TextPrimitive } from './TextPrimitive';
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
