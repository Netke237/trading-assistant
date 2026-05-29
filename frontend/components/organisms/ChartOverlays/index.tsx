'use client';

import { useEffect, useRef } from 'react';
import type { IChartApi, ISeriesApi, ISeriesPrimitive } from 'lightweight-charts';
import type { SignalKind, StructureSignal, ZoneSignal } from '@/types/structure';
import { FVGPrimitive } from '@/lib/chartPrimitives/FVGPrimitive';
import { BOSPrimitive } from '@/lib/chartPrimitives/BOSPrimitive';
import { OrderBlockPrimitive } from '@/lib/chartPrimitives/OrderBlockPrimitive';
import { FibPrimitive } from '@/lib/chartPrimitives/FibPrimitive';
import { DivergencePrimitive } from '@/lib/chartPrimitives/DivergencePrimitive';
import { ConfluencePrimitive } from '@/lib/chartPrimitives/ConfluencePrimitive';

interface Props {
  chart: IChartApi | null;
  mainSeries: ISeriesApi<'Candlestick'> | null;
  signals: StructureSignal[];
  visibility: Record<SignalKind, boolean>;
  visible: boolean;
}

export function ChartOverlays({ chart, mainSeries, signals, visibility, visible }: Props) {
  const attachedRef = useRef<ISeriesPrimitive[]>([]);

  useEffect(() => {
    if (!chart || !mainSeries) return;
    const series = mainSeries;

    for (const p of attachedRef.current) {
      try { series.detachPrimitive(p); } catch { /* ignore */ }
    }
    attachedRef.current = [];

    if (!visible) return;

    for (const signal of signals) {
      if (!visibility[signal.kind]) continue;
      let primitive: ISeriesPrimitive | null = null;
      switch (signal.kind) {
        case 'FVG':
          primitive = new FVGPrimitive(signal);
          break;
        case 'OrderBlock':
          primitive = new OrderBlockPrimitive(signal as ZoneSignal);
          break;
        case 'BOS':
        case 'CHoCH':
          primitive = new BOSPrimitive(signal);
          break;
        case 'Fibonacci':
          primitive = new FibPrimitive(signal);
          break;
        case 'Divergence':
          primitive = new DivergencePrimitive(signal);
          break;
        case 'Confluence':
          primitive = new ConfluencePrimitive(signal);
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
  }, [chart, mainSeries, signals, visibility, visible]);

  return null;
}
