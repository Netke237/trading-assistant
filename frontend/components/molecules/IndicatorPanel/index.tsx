'use client';

import { useEffect, useRef } from 'react';
import {
  LineSeries,
  HistogramSeries,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from 'lightweight-charts';
import styles from './IndicatorPanel.module.css';

// Mirrors lib/chart/indicators.ts's calculateRSI/calculateMACD/calculateVolume
// return shapes exactly — `data` is whichever one matches the `type` prop.
type RsiPoint = { time: string | number; value: number };
type MacdPoint = { time: string | number; macd: number; signal: number; histogram: number };
type VolumePoint = { time: string | number; value: number; color: string };
type IndicatorDataPoint = RsiPoint | MacdPoint | VolumePoint;

interface IndicatorPanelProps {
  chart: IChartApi;
  data: IndicatorDataPoint[];
  type: 'rsi' | 'macd' | 'volume';
}

function token(name: string): string {
  if (typeof window === 'undefined') return '';
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function IndicatorPanel({ chart, data, type }: IndicatorPanelProps) {
  const paneIndexRef = useRef<number | null>(null);
  const seriesRef = useRef<(ISeriesApi<'Line'> | ISeriesApi<'Histogram'>)[]>([]);

  useEffect(() => {
    if (!chart) return;

    if (type === 'rsi') {
      const pane = chart.addPane();
      pane.setStretchFactor(0.3);
      paneIndexRef.current = pane.paneIndex();

      const series = pane.addSeries(LineSeries, {
        color: token('--accent') || '#2962FF',
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        autoscaleInfoProvider: () => ({
          priceRange: { minValue: 0, maxValue: 100 },
        }),
      });
      seriesRef.current = [series];

      series.createPriceLine({
        price: 30,
        color: token('--text-dim') || '#434651',
        lineWidth: 1,
        lineStyle: 2,
      });
      series.createPriceLine({
        price: 70,
        color: token('--text-dim') || '#434651',
        lineWidth: 1,
        lineStyle: 2,
      });
    } else if (type === 'macd') {
      const pane = chart.addPane();
      pane.setStretchFactor(0.3);
      paneIndexRef.current = pane.paneIndex();

      const macdSeries = pane.addSeries(LineSeries, {
        color: token('--accent') || '#2962FF',
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      const signalSeries = pane.addSeries(LineSeries, {
        color: token('--caution') || '#F59F00',
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      const histSeries = pane.addSeries(HistogramSeries, {
        color: token('--text-secondary') || '#787B86',
        priceLineVisible: false,
        lastValueVisible: false,
      });
      seriesRef.current = [macdSeries, signalSeries, histSeries];
    } else if (type === 'volume') {
      const pane = chart.addPane();
      pane.setStretchFactor(0.3);
      paneIndexRef.current = pane.paneIndex();

      const series = pane.addSeries(HistogramSeries, {
        priceFormat: { type: 'volume' },
        priceLineVisible: false,
        lastValueVisible: false,
      });
      seriesRef.current = [series];
    }

    return () => {
      if (paneIndexRef.current !== null) {
        try {
          chart.removePane(paneIndexRef.current);
        } catch {
          /* pane may already be gone */
        }
        paneIndexRef.current = null;
      }
      seriesRef.current = [];
    };
  }, [chart, type]);

  useEffect(() => {
    if (seriesRef.current.length === 0 || data.length === 0) return;

    if (type === 'rsi') {
      seriesRef.current[0].setData(
        (data as RsiPoint[]).map((d) => ({
          time: d.time as Time,
          value: d.value,
        })),
      );
    } else if (type === 'macd') {
      seriesRef.current[0].setData(
        (data as MacdPoint[]).map((d) => ({
          time: d.time as Time,
          value: d.macd,
        })),
      );
      seriesRef.current[1].setData(
        (data as MacdPoint[]).map((d) => ({
          time: d.time as Time,
          value: d.signal,
        })),
      );
      seriesRef.current[2].setData(
        (data as MacdPoint[]).map((d) => ({
          time: d.time as Time,
          value: d.histogram,
          color:
            d.histogram >= 0
              ? token('--pass') || '#26A69A'
              : token('--reject') || '#EF5350',
        })),
      );
    } else if (type === 'volume') {
      seriesRef.current[0].setData(
        (data as VolumePoint[]).map((d) => ({
          time: d.time as Time,
          value: d.value,
          color:
            d.color === 'up'
              ? token('--pass') || '#26A69A'
              : token('--reject') || '#EF5350',
        })),
      );
    }
  }, [data, type]);

  return null;
}
