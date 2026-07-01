import type { Drawing } from '@/types/overlays';
import { ARROW_MARKER_S, ARROW_MARKER_H, ARROW_MARKER_OFFSET } from '@/lib/chartPrimitives/ArrowUpPrimitive';

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

  // 1-point directional markers — bounding rect matches rendered triangle area
  if (d.kind === 'arrow_up') {
    const x = toX(p0.time), y = toY(p0.price);
    if (x == null || y == null) return { hit: false, handle: null };
    const tipY  = y - ARROW_MARKER_OFFSET - ARROW_MARKER_H;
    const baseY = y - ARROW_MARKER_OFFSET;
    const hit = px >= x - ARROW_MARKER_S - tol && px <= x + ARROW_MARKER_S + tol && py >= tipY - tol && py <= baseY + tol;
    return { hit, handle: 'whole' };
  }
  if (d.kind === 'arrow_down') {
    const x = toX(p0.time), y = toY(p0.price);
    if (x == null || y == null) return { hit: false, handle: null };
    const tipY  = y + ARROW_MARKER_OFFSET + ARROW_MARKER_H;
    const baseY = y + ARROW_MARKER_OFFSET;
    const hit = px >= x - ARROW_MARKER_S - tol && px <= x + ARROW_MARKER_S + tol && py >= baseY - tol && py <= tipY + tol;
    return { hit, handle: 'whole' };
  }

  // path: hit if near any segment
  if (d.kind === 'path') {
    if (d.points.length < 2) return { hit: false, handle: null };
    for (let i = 0; i < d.points.length - 1; i++) {
      const ax = toX(d.points[i].time), ay = toY(d.points[i].price);
      const bx = toX(d.points[i + 1].time), by = toY(d.points[i + 1].price);
      if (ax == null || ay == null || bx == null || by == null) continue;
      if (distToSegment(px, py, ax, ay, bx, by) <= tol) return { hit: true, handle: 'whole' };
    }
    return { hit: false, handle: null };
  }

  // circle: hit if within filled area (distance from centre ≤ radius + tol)
  if (d.kind === 'circle') {
    const x0 = toX(p0.time), y0 = toY(p0.price);
    const x1 = toX(d.points[1].time), y1 = toY(d.points[1].price);
    if (x0 == null || y0 == null || x1 == null || y1 == null) return { hit: false, handle: null };
    const radius = Math.hypot(x1 - x0, y1 - y0);
    const dist = Math.hypot(px - x0, py - y0);
    return { hit: dist <= radius + tol, handle: 'whole' };
  }

  // 2-point kinds: arrow / trendline / rect
  const p1 = d.points[1];
  const x0 = toX(p0.time), y0 = toY(p0.price), x1 = toX(p1?.time ?? p0.time), y1 = toY(p1?.price ?? p0.price);
  if (x0 == null || y0 == null || x1 == null || y1 == null) return { hit: false, handle: null };
  if (near(x0, y0)) return { hit: true, handle: 'p0' };
  if (near(x1, y1)) return { hit: true, handle: 'p1' };
  if (d.kind === 'trendline' || d.kind === 'arrow') {
    return { hit: distToSegment(px, py, x0, y0, x1, y1) <= tol, handle: 'whole' };
  }
  // rect: near any of the 4 borders
  const onBorder =
    distToSegment(px, py, x0, y0, x1, y0) <= tol || distToSegment(px, py, x1, y0, x1, y1) <= tol ||
    distToSegment(px, py, x1, y1, x0, y1) <= tol || distToSegment(px, py, x0, y1, x0, y0) <= tol;
  return { hit: onBorder, handle: 'whole' };
}
