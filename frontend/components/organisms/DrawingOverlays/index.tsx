'use client';

import { useEffect, useRef } from 'react';
import type { IChartApi, ISeriesApi } from 'lightweight-charts';
import type { Drawing } from '@/types/overlays';
import type { UpdatablePrimitive } from '@/lib/chartPrimitives/types';
import type { AttachedEntry } from '@/lib/chart/drawingOverlaysDiff';
import { diffDrawings } from '@/lib/chart/drawingOverlaysDiff';
import { HorizontalLinePrimitive } from '@/lib/chartPrimitives/HorizontalLinePrimitive';
import { TrendLinePrimitive } from '@/lib/chartPrimitives/TrendLinePrimitive';
import { RectanglePrimitive } from '@/lib/chartPrimitives/RectanglePrimitive';
import { TextPrimitive } from '@/lib/chartPrimitives/TextPrimitive';

interface Props {
  chart: IChartApi | null;
  mainSeries: ISeriesApi<'Candlestick'> | null;
  drawings: Drawing[];
}

function makePrimitive(drawing: Drawing): UpdatablePrimitive | null {
  switch (drawing.kind) {
    case 'hline':     return new HorizontalLinePrimitive(drawing);
    case 'trendline': return new TrendLinePrimitive(drawing);
    case 'rect':      return new RectanglePrimitive(drawing);
    case 'text':      return new TextPrimitive(drawing);
    default:          return null;
  }
}

export default function DrawingOverlays({ chart, mainSeries, drawings }: Props) {
  // Keyed by drawing.id — persists across renders
  const attachedRef = useRef<Map<string, AttachedEntry>>(new Map());

  // Effect 1: diff-based update. No cleanup function here — that is handled by
  // Effect 2 below. If cleanup lived here, React would call it on every `drawings`
  // change (before each re-run), which would detach all primitives on every drag tick.
  useEffect(() => {
    if (!chart || !mainSeries) return;
    const attached = attachedRef.current;
    const { toAdd, toRemove, toUpdate } = diffDrawings(attached, drawings);

    for (const entry of toRemove) {
      try { mainSeries.detachPrimitive(entry.primitive); } catch { /* ignore */ }
      attached.delete(entry.drawing.id);
    }

    for (const { entry, drawing } of toUpdate) {
      entry.primitive.update(drawing);
      // Create a new AttachedEntry object rather than mutating the existing one,
      // so the map stays consistent under concurrent React scheduling.
      attached.set(drawing.id, { primitive: entry.primitive, drawing });
    }

    for (const drawing of toAdd) {
      const primitive = makePrimitive(drawing);
      if (!primitive) continue;
      mainSeries.attachPrimitive(primitive);
      attached.set(drawing.id, { primitive, drawing });
    }
  }, [chart, mainSeries, drawings]);

  // Effect 2: detach ALL primitives from the OLD series when chart/series changes.
  // Deps are intentionally [chart, mainSeries] only — not drawings — so this
  // cleanup never fires on a drawings update, only on series replacement or unmount.
  useEffect(() => {
    const attached = attachedRef.current;
    return () => {
      for (const entry of attached.values()) {
        try { mainSeries?.detachPrimitive(entry.primitive); } catch { /* ignore */ }
      }
      attached.clear();
    };
  }, [chart, mainSeries]);

  return null;
}
