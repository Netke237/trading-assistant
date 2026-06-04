'use client';
import { useEffect, useRef, useCallback } from 'react';
import {
  createChart,
  CandlestickSeries,
  BarSeries,
  LineSeries,
  HistogramSeries,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from 'lightweight-charts';
import type { Candle, Point } from '@/lib/indicators';
import styles from './ChartPane.module.css';

export interface SeriesConfig {
  id: string;
  type: 'Candlestick' | 'Bar' | 'Line' | 'Histogram';
  data: Candle[] | Point[];
  color?: string;
  priceScaleId?: string;
}

interface Props {
  series: SeriesConfig[];
  onCrosshairMove?: (time: string | null, values: Record<string, number>) => void;
  height?: number;   // 0 or omitted = fill container height
  chartApiRef?: React.MutableRefObject<IChartApi | null>;
  mainSeriesRef?: React.MutableRefObject<ISeriesApi<'Candlestick'> | null>;
}

export default function ChartPane({ series, onCrosshairMove, height = 0, chartApiRef, mainSeriesRef }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesMap = useRef<Map<string, ISeriesApi<'Candlestick' | 'Bar' | 'Line' | 'Histogram'>>>(new Map());
  const onCrosshairMoveRef = useRef(onCrosshairMove);
  useEffect(() => { onCrosshairMoveRef.current = onCrosshairMove; }, [onCrosshairMove]);

  const getHeight = useCallback(() => {
    if (height > 0) return height;
    return containerRef.current?.clientHeight || 400;
  }, [height]);

  const initChart = useCallback(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: '#0b0b14' },
        textColor: '#888',
      },
      grid: {
        vertLines: { color: '#1e1e35' },
        horzLines: { color: '#1e1e35' },
      },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: '#1e1e35' },
      timeScale: { borderColor: '#1e1e35', timeVisible: true },
      width: containerRef.current.clientWidth,
      height: getHeight(),
    });
    chartRef.current = chart;
    if (chartApiRef) chartApiRef.current = chart;

    chart.subscribeCrosshairMove((param) => {
      if (!param.time) { onCrosshairMoveRef.current?.(null, {}); return; }
      const values: Record<string, number> = {};
      seriesMap.current.forEach((s, id) => {
        const v = param.seriesData.get(s);
        if (v && 'close' in v) values[id] = (v as { close: number }).close;
        else if (v && 'value' in v) values[id] = (v as { value: number }).value;
      });
      onCrosshairMoveRef.current?.(String(param.time), values);
    });
  }, [getHeight]);

  useEffect(() => {
    initChart();
    const observer = new ResizeObserver(() => {
      if (chartRef.current && containerRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
          height: getHeight(),
        });
      }
    });
    if (containerRef.current) observer.observe(containerRef.current);
    return () => {
      observer.disconnect();
      chartRef.current?.remove();
      chartRef.current = null;
      seriesMap.current.clear();
    };
  }, [initChart]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    // Remove series not in current config
    seriesMap.current.forEach((s, id) => {
      if (!series.find(c => c.id === id)) {
        chart.removeSeries(s);
        seriesMap.current.delete(id);
      }
    });

    // Add or update series
    series.forEach((cfg) => {
      let s = seriesMap.current.get(cfg.id);
      if (!s) {
        if (cfg.type === 'Candlestick') {
          s = chart.addSeries(CandlestickSeries, {
            upColor: '#4caf50',
            downColor: '#e05050',
            borderVisible: false,
            wickUpColor: '#4caf50',
            wickDownColor: '#e05050',
          });
          if (mainSeriesRef) mainSeriesRef.current = s as ISeriesApi<'Candlestick'>;
        } else if (cfg.type === 'Bar') {
          s = chart.addSeries(BarSeries, {
            upColor: '#4caf50', downColor: '#e05050',
          });
          // Bar is used as main series — update ref so ChartOverlays still works
          if (mainSeriesRef) mainSeriesRef.current = s as unknown as ISeriesApi<'Candlestick'>;
        } else if (cfg.type === 'Histogram') {
          s = chart.addSeries(HistogramSeries, {
            color: cfg.color ?? '#4a4a6a',
            priceScaleId: cfg.priceScaleId ?? 'right',
          });
        } else {
          s = chart.addSeries(LineSeries, {
            color: cfg.color ?? '#4f8ef7',
            lineWidth: 1,
            priceScaleId: cfg.priceScaleId ?? 'right',
          });
          // Line is used as main series (line chart mode) — update ref so ChartOverlays still works
          if (mainSeriesRef && cfg.id.startsWith('candles-')) {
            mainSeriesRef.current = s as unknown as ISeriesApi<'Candlestick'>;
          }
        }
        seriesMap.current.set(cfg.id, s);
      }

      if (cfg.type === 'Candlestick' || cfg.type === 'Bar') {
        (s as ISeriesApi<'Candlestick' | 'Bar'>).setData(
          (cfg.data as Candle[]).map(c => ({
            time: c.time as Time,
            open: c.open, high: c.high, low: c.low, close: c.close,
          }))
        );
      } else {
        (s as ISeriesApi<'Line' | 'Histogram'>).setData(
          (cfg.data as Point[]).map(p => ({ time: p.time as Time, value: p.value }))
        );
      }
    });
  }, [series]);

  return (
    <div
      ref={containerRef}
      className={styles.pane}
      style={height > 0 ? { height } : { height: '100%' }}
    />
  );
}
