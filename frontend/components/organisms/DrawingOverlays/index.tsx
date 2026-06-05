'use client';

import { useEffect, useRef } from 'react';
import type { IChartApi, ISeriesApi, ISeriesPrimitive } from 'lightweight-charts';
import type { Drawing } from '@/types/overlays';
import { HorizontalLinePrimitive } from '@/lib/chartPrimitives/HorizontalLinePrimitive';
import { TrendLinePrimitive } from '@/lib/chartPrimitives/TrendLinePrimitive';
import { RectanglePrimitive } from '@/lib/chartPrimitives/RectanglePrimitive';
import { TextPrimitive } from '@/lib/chartPrimitives/TextPrimitive';

interface Props {
  chart: IChartApi | null;
  mainSeries: ISeriesApi<'Candlestick'> | null;
  drawings: Drawing[];
}

export default function DrawingOverlays({ chart, mainSeries, drawings }: Props) {
  const attachedRef = useRef<ISeriesPrimitive[]>([]);

  useEffect(() => {
    if (!chart || !mainSeries) return;
    const series = mainSeries;

    for (const p of attachedRef.current) {
      try { series.detachPrimitive(p); } catch { /* ignore */ }
    }
    attachedRef.current = [];

    for (const drawing of drawings) {
      let primitive: ISeriesPrimitive | null = null;
      switch (drawing.kind) {
        case 'hline':
          primitive = new HorizontalLinePrimitive(drawing);
          break;
        case 'trendline':
          primitive = new TrendLinePrimitive(drawing);
          break;
        case 'rect':
          primitive = new RectanglePrimitive(drawing);
          break;
        case 'text':
          primitive = new TextPrimitive(drawing);
          break;
      }
      if (primitive) {
        series.attachPrimitive(primitive);
        attachedRef.current.push(primitive);
      }
    }

    return () => {
      for (const p of attachedRef.current) {
        try { series.detachPrimitive(p); } catch { /* ignore */ }
      }
      attachedRef.current = [];
    };
  }, [chart, mainSeries, drawings]);

  return null;
}
