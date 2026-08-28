'use client';

/*
 * CandlestickChart — thin wrapper around TradingView Lightweight Charts v5.
 *
 * - Pane 0: candles (OHLC)
 * - Additional panes managed by IndicatorPanel for Volume / RSI / MACD
 *
 * Colors are read from tokens at mount and re-applied on theme change
 * (subscribed to useThemeStore). Drift log G8.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  createChart,
  CandlestickSeries,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from 'lightweight-charts';
import { useThemeStore } from '@/lib/theme';
import { IndicatorPanel } from '@/components/molecules/IndicatorPanel';
import { calculateRSI, calculateMACD, calculateVolume } from '@/lib/chart/indicators';
import type { Candle, IndicatorType } from '@/types/chart';
import styles from './CandlestickChart.module.css';

interface CandlestickChartProps {
  data: Candle[];
  /**
   * Fixed pixel height. Omit (or pass `'auto'`) to make the chart fill its
   * container — the wrapper uses ResizeObserver to track parent size.
   */
  height?: number | 'auto';
  className?: string;
  showToggles?: boolean;
  defaultIndicators?: IndicatorType[];
}

/** Read a CSS custom property off :root. */
function token(name: string): string {
  if (typeof window === 'undefined') return '';
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

const INDICATOR_ORDER: IndicatorType[] = ['volume', 'rsi', 'macd'];

export function CandlestickChart({
  data,
  height = 320,
  className,
  showToggles = true,
  defaultIndicators = ['volume', 'rsi'],
}: CandlestickChartProps) {
  const theme = useThemeStore((s) => s.theme);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const [chartVersion, setChartVersion] = useState(0);
  const [activeIndicators, setActiveIndicators] = useState<IndicatorType[]>(defaultIndicators);

  const autoFill = height === 'auto';

  // Chart lifecycle — recreate only when layout/theme changes, never on data.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const bg = token('--bg-surface') || '#1E2335';
    const gridSoft = token('--border-subtle') || '#2A2E42';
    const textDim = token('--text-secondary') || '#787B86';
    const passColor = token('--pass') || '#26A69A';
    const rejColor = token('--reject') || '#EF5350';

    const initialHeight = autoFill ? (el.clientHeight || 320) : (height as number);

    const chart = createChart(el, {
      width: el.clientWidth,
      height: initialHeight,
      layout: {
        background: { color: bg },
        textColor: textDim,
        fontFamily: 'var(--font-mono), JetBrains Mono, monospace',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: gridSoft },
        horzLines: { color: gridSoft },
      },
      rightPriceScale: { borderColor: gridSoft },
      timeScale: { borderColor: gridSoft, timeVisible: false },
      crosshair: { mode: 1 },
    });
    chartRef.current = chart;

    const candle = chart.addSeries(CandlestickSeries, {
      upColor: passColor,
      downColor: rejColor,
      borderUpColor: passColor,
      borderDownColor: rejColor,
      wickUpColor: passColor,
      wickDownColor: rejColor,
    }) as ISeriesApi<'Candlestick'>;
    candleSeriesRef.current = candle;
    setChartVersion((v) => v + 1);

    const applySize = () => {
      chart.applyOptions({
        width: el.clientWidth,
        ...(autoFill ? { height: el.clientHeight } : {}),
      });
    };
    const ro = new ResizeObserver(applySize);
    ro.observe(el);
    window.addEventListener('resize', applySize);

    return () => {
      ro.disconnect();
      window.removeEventListener('resize', applySize);
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
    };
  }, [height, theme, autoFill]);

  // Data update — never recreates the chart, just replaces series data.
  // chartVersion dep ensures this re-runs after a theme-triggered chart rebuild.
  useEffect(() => {
    const candle = candleSeriesRef.current;
    if (!candle) return;
    // Upstream OHLCV providers occasionally emit a NaN bar (thin/halted
    // trading days) that round-trips through JSON as null — lightweight-charts
    // asserts on any non-number field and would otherwise crash the whole chart.
    candle.setData(
      data
        .filter(
          (c) =>
            Number.isFinite(c.open) &&
            Number.isFinite(c.high) &&
            Number.isFinite(c.low) &&
            Number.isFinite(c.close),
        )
        .map((c) => ({
          time: c.time as Time,
          open: c.open,
          high: c.high,
          low: c.low,
          close: c.close,
        })),
    );
    chartRef.current?.timeScale().fitContent();
  }, [data, chartVersion]);

  const indicatorData = useMemo(
    () => ({
      volume: calculateVolume(data),
      rsi: calculateRSI(data),
      macd: calculateMACD(data),
    }),
    [data],
  );

  const toggleIndicator = (type: IndicatorType) => {
    setActiveIndicators((prev) => {
      if (prev.includes(type)) return prev.filter((t) => t !== type);
      return INDICATOR_ORDER.filter((t) => t === type || prev.includes(t));
    });
  };

  return (
    <div className={`${styles.wrapper} ${autoFill ? styles.wrapperAuto : ''}`}>
      {showToggles && (
        <div className={styles.toggleBar}>
          <button className={styles.toggleBtnActive} disabled>
            Candle
          </button>
          {INDICATOR_ORDER.map((ind) => {
            const active = activeIndicators.includes(ind);
            return (
              <button
                key={ind}
                className={active ? styles.toggleBtnActive : styles.toggleBtn}
                onClick={() => toggleIndicator(ind)}
              >
                {ind === 'volume' ? 'Volume' : ind === 'rsi' ? 'RSI' : 'MACD'}
              </button>
            );
          })}
        </div>
      )}
      <div
        ref={containerRef}
        className={`${styles.chart} ${className ?? ''}`}
        data-autofill={autoFill ? 'true' : undefined}
      />
      {chartRef.current &&
        activeIndicators.map((type) => (
          <IndicatorPanel
            key={`${chartVersion}-${type}`}
            chart={chartRef.current!}
            data={indicatorData[type]}
            type={type}
          />
        ))}
    </div>
  );
}
