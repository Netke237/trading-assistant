import type { Drawing } from '@/types/overlays';

export function distToSegment(px: number, py: number, x1: number, y1: number, x2: number, y2: number): number {
  const dx = x2 - x1, dy = y2 - y1;
  const len2 = dx * dx + dy * dy;
  let t = len2 === 0 ? 0 : ((px - x1) * dx + (py - y1) * dy) / len2;
  t = Math.max(0, Math.min(1, t));
  const cx = x1 + t * dx, cy = y1 + t * dy;
  return Math.hypot(px - cx, py - cy);
}

export type Handle = 'p0' | 'p1' | 'whole' | null;
export interface HitResult { hit: boolean; handle: Handle; }

/** toX: time->pixel, toY: price->pixel. tol in pixels. */
export function hitTestDrawing(
  d: Drawing, px: number, py: number,
  toX: (time: number) => number | null, toY: (price: number) => number | null, tol: number,
): HitResult {
  const near = (x: number | null, y: number | null) => x != null && y != null && Math.hypot(px - x, py - y) <= tol;
  const p0 = d.points[0];
  if (d.kind === 'hline') {
    const y = toY(p0.price);
    return { hit: y != null && Math.abs(py - y) <= tol, handle: 'whole' };
  }
  if (d.kind === 'text') {
    const x = toX(p0.time), y = toY(p0.price);
    return { hit: x != null && y != null && px >= x - 4 && px <= x + 120 && py >= y - 18 && py <= y + 4, handle: 'whole' };
  }
  const p1 = d.points[1];
  const x0 = toX(p0.time), y0 = toY(p0.price), x1 = toX(p1?.time ?? p0.time), y1 = toY(p1?.price ?? p0.price);
  if (x0 == null || y0 == null || x1 == null || y1 == null) return { hit: false, handle: null };
  if (near(x0, y0)) return { hit: true, handle: 'p0' };
  if (near(x1, y1)) return { hit: true, handle: 'p1' };
  if (d.kind === 'trendline') return { hit: distToSegment(px, py, x0, y0, x1, y1) <= tol, handle: 'whole' };
  // rect: near any of the 4 borders
  const onBorder =
    distToSegment(px, py, x0, y0, x1, y0) <= tol || distToSegment(px, py, x1, y0, x1, y1) <= tol ||
    distToSegment(px, py, x1, y1, x0, y1) <= tol || distToSegment(px, py, x0, y1, x0, y0) <= tol;
  return { hit: onBorder, handle: 'whole' };
}
