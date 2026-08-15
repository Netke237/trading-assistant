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
import { useThemeStore } from '@/lib/theme';
import styles from './ChartPane.module.css';

export interface SeriesConfig {
  id: string;
  type: 'Candlestick' | 'Bar' | 'Line' | 'Histogram';
  data: Candle[] | Point[];
  color?: string;
  priceScaleId?: string;
  paneIndex?: number;
}

interface Props {
  series: SeriesConfig[];
  onCrosshairMove?: (time: string | null, values: Record<string, number>) => void;
  height?: number;   // 0 or omitted = fill container height
  chartApiRef?: React.MutableRefObject<IChartApi | null>;
  mainSeriesRef?: React.MutableRefObject<ISeriesApi<'Candlestick'> | null>;
  /** Called whenever the pane-0 main series is created or replaced (e.g. chart-type switch). */
  onSeriesReady?: (chart: IChartApi, series: ISeriesApi<'Candlestick'>) => void;
}

/** Read a CSS custom property off :root. Mirrors CandlestickChart's helper. */
function token(name: string): string {
  if (typeof window === 'undefined') return '';
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

interface ThemeColors {
  bg: string;
  gridSoft: string;
  textDim: string;
  passColor: string;
  rejColor: string;
}

function readThemeColors(): ThemeColors {
  return {
    bg:        token('--bg-surface')     || '#0b0b14',
    gridSoft:  token('--border-subtle')  || '#1e1e35',
    textDim:   token('--text-secondary') || '#888',
    passColor: token('--pass')           || '#4caf50',
    rejColor:  token('--reject')         || '#e05050',
  };
}

export default function ChartPane({ series, onCrosshairMove, height = 0, chartApiRef, mainSeriesRef, onSeriesReady }: Props) {
  const theme = useThemeStore((s) => s.theme);
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const colorsRef = useRef<ThemeColors>(readThemeColors());
  const seriesMap = useRef<Map<string, ISeriesApi<'Candlestick' | 'Bar' | 'Line' | 'Histogram'>>>(new Map());
  const onCrosshairMoveRef = useRef(onCrosshairMove);
  const prevPaneCountRef = useRef(0);
  const isFirstThemeRunRef = useRef(true);
  const seriesRef = useRef(series);
  useEffect(() => { seriesRef.current = series; }, [series]);
  useEffect(() => { onCrosshairMoveRef.current = onCrosshairMove; }, [onCrosshairMove]);
  const onSeriesReadyRef = useRef(onSeriesReady);
  useEffect(() => { onSeriesReadyRef.current = onSeriesReady; }, [onSeriesReady]);

  const getHeight = useCallback(() => {
    if (height > 0) return height;
    return containerRef.current?.clientHeight || 400;
  }, [height]);

  const initChart = useCallback(() => {
    if (!containerRef.current) return;
    const colors = readThemeColors();
    colorsRef.current = colors;
    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: colors.bg },
        textColor: colors.textDim,
      },
      grid: {
        vertLines: { color: colors.gridSoft },
        horzLines: { color: colors.gridSoft },
      },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: colors.gridSoft },
      timeScale: { borderColor: colors.gridSoft, timeVisible: true },
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
  }, [getHeight, chartApiRef]);

  // Chart lifecycle — mount/unmount ONLY. Colors are read once at creation
  // time (correct for the common case: theme was already set in Settings
  // before this component ever mounted). Deliberately NOT keyed on `theme` —
  // see the live-restyle effect below for why a full recreate-on-toggle is
  // avoided here.
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
      prevPaneCountRef.current = 0;
    };
  }, [initChart]);

  // Live theme toggle while already mounted — restyle in place via
  // lightweight-charts' own applyOptions API, never remove()/createChart()
  // again. ChartWorkspace hangs volume-profile/preview overlays, drag
  // handlers, and a regime-overlay series off this exact chart/series
  // instance; a full teardown-and-recreate on every toggle would put all of
  // that at risk for a color change. Only series tracked in seriesMap (this
  // component's own `series` prop) are restyled; series ChartWorkspace adds
  // directly to the chart outside that prop are untouched, same as before.
  useEffect(() => {
    if (isFirstThemeRunRef.current) { isFirstThemeRunRef.current = false; return; }
    const chart = chartRef.current;
    if (!chart) return;
    const colors = readThemeColors();
    colorsRef.current = colors;
    chart.applyOptions({
      layout: { background: { color: colors.bg }, textColor: colors.textDim },
      grid: {
        vertLines: { color: colors.gridSoft },
        horzLines: { color: colors.gridSoft },
      },
      rightPriceScale: { borderColor: colors.gridSoft },
      timeScale: { borderColor: colors.gridSoft },
    });
    seriesMap.current.forEach((s, id) => {
      const cfg = seriesRef.current.find((c) => c.id === id);
      if (!cfg) return;
      if (cfg.type === 'Candlestick') {
        (s as ISeriesApi<'Candlestick'>).applyOptions({
          upColor: colors.passColor, downColor: colors.rejColor,
          wickUpColor: colors.passColor, wickDownColor: colors.rejColor,
        });
      } else if (cfg.type === 'Bar') {
        (s as ISeriesApi<'Bar'>).applyOptions({
          upColor: colors.passColor, downColor: colors.rejColor,
        });
      } else if (!cfg.color) {
        // Only restyle indicator series that didn't request an explicit
        // color — one that did (cfg.color set) keeps the caller's choice.
        (s as ISeriesApi<'Line' | 'Histogram'>).applyOptions({
          color: cfg.type === 'Line' ? colors.passColor : colors.gridSoft,
        });
      }
    });
    // theme is the only real trigger here — series is read via seriesRef
    // (not a dep) so this doesn't refire on every live data tick, only on
    // an actual theme toggle.
  }, [theme]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const { passColor, rejColor } = colorsRef.current;

    // Remove series not in current config
    seriesMap.current.forEach((s, id) => {
      if (!series.find(c => c.id === id)) {
        chart.removeSeries(s);
        seriesMap.current.delete(id);
      }
    });

    // Remove panes that are now empty (lightweight-charts does not auto-remove them).
    // Iterate from the last pane downward so that removing by index stays correct.
    const panesAfterRemove = chart.panes();
    for (let i = panesAfterRemove.length - 1; i >= 1; i--) {
      if (panesAfterRemove[i].getSeries().length === 0) {
        chart.removePane(i);
      }
    }

    // Add or update series
    series.forEach((cfg) => {
      let s = seriesMap.current.get(cfg.id);
      if (!s) {
        if (cfg.type === 'Candlestick') {
          s = chart.addSeries(CandlestickSeries, {
            upColor: passColor,
            downColor: rejColor,
            borderVisible: false,
            wickUpColor: passColor,
            wickDownColor: rejColor,
          }, cfg.paneIndex ?? 0);
          if ((cfg.paneIndex ?? 0) === 0) {
            if (mainSeriesRef) mainSeriesRef.current = s as ISeriesApi<'Candlestick'>;
            onSeriesReadyRef.current?.(chart, s as ISeriesApi<'Candlestick'>);
          }
        } else if (cfg.type === 'Bar') {
          s = chart.addSeries(BarSeries, {
            upColor: passColor, downColor: rejColor,
          }, cfg.paneIndex ?? 0);
          if ((cfg.paneIndex ?? 0) === 0) {
            if (mainSeriesRef) mainSeriesRef.current = s as unknown as ISeriesApi<'Candlestick'>;
            onSeriesReadyRef.current?.(chart, s as unknown as ISeriesApi<'Candlestick'>);
          }
        } else if (cfg.type === 'Histogram') {
          s = chart.addSeries(HistogramSeries, {
            color: cfg.color ?? colorsRef.current.gridSoft,
            priceScaleId: cfg.priceScaleId ?? 'right',
          }, cfg.paneIndex ?? 0);
        } else {
          s = chart.addSeries(LineSeries, {
            color: cfg.color ?? passColor,
            lineWidth: 1,
            priceScaleId: cfg.priceScaleId ?? 'right',
          }, cfg.paneIndex ?? 0);
          if ((cfg.paneIndex ?? 0) === 0) {
            if (mainSeriesRef) mainSeriesRef.current = s as unknown as ISeriesApi<'Candlestick'>;
            onSeriesReadyRef.current?.(chart, s as unknown as ISeriesApi<'Candlestick'>);
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

    // Set proportional pane heights only when the pane count changes, not on every data tick.
    // Main pane (0) gets 60%, remaining 40% is split evenly among sub-panes.
    const panes = chart.panes();
    const currentPaneCount = panes.length;
    if (currentPaneCount !== prevPaneCountRef.current) {
      prevPaneCountRef.current = currentPaneCount;
      if (currentPaneCount > 1) {
        const totalHeight = containerRef.current?.clientHeight || getHeight();
        const mainHeight = Math.round(totalHeight * 0.6);
        const subHeight = Math.round((totalHeight - mainHeight) / (currentPaneCount - 1));
        panes[0].setHeight(mainHeight);
        for (let i = 1; i < currentPaneCount; i++) {
          panes[i].setHeight(subHeight);
        }
      }
    }
  }, [series, getHeight, mainSeriesRef]);

  return (
    <div
      ref={containerRef}
      className={styles.pane}
      style={height > 0 ? { height } : { height: '100%' }}
    />
  );
}
