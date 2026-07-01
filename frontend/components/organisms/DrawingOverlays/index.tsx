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
import { ArrowPrimitive } from '@/lib/chartPrimitives/ArrowPrimitive';
import { ArrowUpPrimitive } from '@/lib/chartPrimitives/ArrowUpPrimitive';
import { ArrowDownPrimitive } from '@/lib/chartPrimitives/ArrowDownPrimitive';
import { CirclePrimitive } from '@/lib/chartPrimitives/CirclePrimitive';
import { PathPrimitive } from '@/lib/chartPrimitives/PathPrimitive';

interface Props {
  chart: IChartApi | null;
  mainSeries: ISeriesApi<'Candlestick'> | null;
  drawings: Drawing[];
}

function makePrimitive(drawing: Drawing): UpdatablePrimitive | null {
  switch (drawing.kind) {
    case 'hline':      return new HorizontalLinePrimitive(drawing);
    case 'trendline':  return new TrendLinePrimitive(drawing);
    case 'rect':       return new RectanglePrimitive(drawing);
    case 'text':       return new TextPrimitive(drawing);
    case 'arrow':      return new ArrowPrimitive(drawing);
    case 'arrow_up':   return new ArrowUpPrimitive(drawing);
    case 'arrow_down': return new ArrowDownPrimitive(drawing);
    case 'circle':     return new CirclePrimitive(drawing);
    case 'path':       return new PathPrimitive(drawing);
    default: {
      const _exhaustive: never = drawing.kind;
      void _exhaustive;
      return null;
    }
  }
}

export default function DrawingOverlays({ chart, mainSeries, drawings }: Props) {
  const attachedRef = useRef<Map<string, AttachedEntry>>(new Map());

  useEffect(() => {
    if (!chart || !mainSeries) return;
    const attached = attachedRef.current;
    const { toAdd, toRemove, toUpdate } = diffDrawings(attached, drawings);

    for (const entry of toRemove) {
      try {
        mainSeries.detachPrimitive(entry.primitive);
      } catch (e) {
        if (process.env.NODE_ENV !== 'production') throw e;
      }
      attached.delete(entry.drawing.id);
    }

    for (const { entry, drawing } of toUpdate) {
      entry.primitive.update(drawing);
      attached.set(drawing.id, { primitive: entry.primitive, drawing });
    }

    for (const drawing of toAdd) {
      const primitive = makePrimitive(drawing);
      if (!primitive) continue;
      mainSeries.attachPrimitive(primitive);
      attached.set(drawing.id, { primitive, drawing });
    }
  }, [chart, mainSeries, drawings]);

  useEffect(() => {
    return () => {
      const attached = attachedRef.current;
      for (const entry of attached.values()) {
        try {
          mainSeries?.detachPrimitive(entry.primitive);
        } catch (e) {
          if (process.env.NODE_ENV !== 'production') throw e;
        }
      }
      attached.clear();
    };
  }, [chart, mainSeries]);

  return null;
}
