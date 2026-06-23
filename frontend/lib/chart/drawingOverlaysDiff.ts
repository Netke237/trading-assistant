import type { Drawing } from '@/types/overlays';
import type { UpdatablePrimitive } from '@/lib/chartPrimitives/types';

export interface AttachedEntry {
  primitive: UpdatablePrimitive;
  drawing: Drawing;
}

export interface DiffResult {
  toAdd: Drawing[];
  toRemove: AttachedEntry[];
  toUpdate: { entry: AttachedEntry; drawing: Drawing }[];
}

/**
 * Computes which drawing primitives need to be added, removed, or updated.
 * Uses object reference equality for update detection — Zustand produces a new
 * Drawing object any time a field changes, so reference check is sufficient.
 */
export function diffDrawings(
  prev: Map<string, AttachedEntry>,
  next: Drawing[],
): DiffResult {
  // Build id→drawing map once (O(m)) to avoid O(n×m) inner find() per prev entry.
  const nextById = new Map(next.map((d) => [d.id, d]));
  const toRemove: AttachedEntry[] = [];
  const toUpdate: { entry: AttachedEntry; drawing: Drawing }[] = [];
  const toAdd: Drawing[] = [];

  prev.forEach((entry, id) => {
    const nextDrawing = nextById.get(id);
    if (!nextDrawing) {
      toRemove.push(entry);
    } else if (entry.drawing !== nextDrawing) {
      toUpdate.push({ entry, drawing: nextDrawing });
    }
  });

  // Iterate nextById (not next) so duplicate ids in next only produce one toAdd entry.
  nextById.forEach((drawing, id) => {
    if (!prev.has(id)) {
      toAdd.push(drawing);
    }
  });

  return { toAdd, toRemove, toUpdate };
}
