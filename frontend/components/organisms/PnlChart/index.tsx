'use client';

/*
 * PnlChart — whole-portfolio P&L evolution line, built on TradingView
 * Lightweight Charts v5 (same setup pattern as CandlestickChart).
 *
 * Side buttons pick which curve to show — Total account value (equityCurve)
 * or cumulative Realized P&L (realizedCurve) — and the time axis can be
 * resampled to Days / Weeks / Months. Both source curves come straight from
 * GET /api/portfolio/performance.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  createChart,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from 'lightweight-charts';
import { useThemeStore } from '@/lib/theme';
import { Text } from '@/components/primitives';
import type { PerfPoint } from '@/lib/performanceStore';
import styles from './PnlChart.module.css';

type SeriesKind = 'open' | 'equity' | 'realized';
type Granularity = 'day' | 'week' | 'month';

interface PnlChartProps {
  equityCurve: PerfPoint[];
  realizedCurve: PerfPoint[];
  openPnlCurve?: PerfPoint[];
  height?: number;
  defaultKind?: SeriesKind;
}

function token(name: string): string {
  if (typeof window === 'undefined') return '';
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** Monday-anchored ISO date string for the week containing `dateStr`. */
function weekKey(dateStr: string): string {
  const d = new Date(`${dateStr}T00:00:00`);
  const mondayOffset = (d.getDay() + 6) % 7; // Mon = 0 … Sun = 6
  d.setDate(d.getDate() - mondayOffset);
  return d.toISOString().slice(0, 10);
}

/**
 * Collapse a daily curve to one point per week/month. The curves are
 * cumulative (realized) or end-of-day snapshots (equity), so the correct
 * representative for a period is its LAST observation — hence last-wins.
 * Assumes `points` is ascending by date.
 */
function resample(points: PerfPoint[], gran: Granularity): PerfPoint[] {
  if (gran === 'day') return points;
  const lastByKey = new Map<string, PerfPoint>();
  for (const p of points) {
    const key = gran === 'month' ? p.date.slice(0, 7) : weekKey(p.date);
    lastByKey.set(key, p);
  }
  return Array.from(lastByKey.values()).sort((a, b) => a.date.localeCompare(b.date));
}

export function PnlChart({ equityCurve, realizedCurve, openPnlCurve, height = 260, defaultKind = 'equity' }: PnlChartProps) {
  const theme = useThemeStore((s) => s.theme);
  const [kind, setKind] = useState<SeriesKind>(defaultKind);
  const [gran, setGran] = useState<Granularity>('day');

  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const [chartVersion, setChartVersion] = useState(0);

  const data = useMemo(() => {
    const source =
      kind === 'open' ? (openPnlCurve ?? [])
      : kind === 'equity' ? equityCurve
      : realizedCurve;
    const ascending = [...source].sort((a, b) => a.date.localeCompare(b.date));
    return resample(ascending, gran);
  }, [kind, gran, equityCurve, realizedCurve, openPnlCurve]);

  // Chart lifecycle — recreate only on theme change, never on data.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const bg = token('--bg-surface') || '#1E2335';
    const gridSoft = token('--border-subtle') || '#2A2E42';
    const textDim = token('--text-secondary') || '#787B86';

    const chart = createChart(el, {
      width: el.clientWidth,
      height,
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

    const line = chart.addSeries(LineSeries, {
      color: token('--accent') || '#2962FF',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
    }) as ISeriesApi<'Line'>;
    seriesRef.current = line;
    setChartVersion((v) => v + 1);

    const applySize = () => chart.applyOptions({ width: el.clientWidth });
    const ro = new ResizeObserver(applySize);
    ro.observe(el);
    window.addEventListener('resize', applySize);

    return () => {
      ro.disconnect();
      window.removeEventListener('resize', applySize);
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, [theme, height]);

  // Data update — replaces series data; re-runs after a theme rebuild.
  useEffect(() => {
    const line = seriesRef.current;
    if (!line) return;
    line.setData(data.map((p) => ({ time: p.date as Time, value: p.value })));
    chartRef.current?.timeScale().fitContent();
  }, [data, chartVersion]);

  const empty = data.length === 0;

  return (
    <div className={styles.wrap}>
      <div className={styles.side}>
        <div className={styles.group}>
          <Text size={10} tone="dim">CURVE</Text>
          {openPnlCurve && (
            <button
              type="button"
              className={kind === 'open' ? styles.btnActive : styles.btn}
              onClick={() => setKind('open')}
            >
              Open P&amp;L
            </button>
          )}
          <button
            type="button"
            className={kind === 'equity' ? styles.btnActive : styles.btn}
            onClick={() => setKind('equity')}
          >
            Total value
          </button>
          <button
            type="button"
            className={kind === 'realized' ? styles.btnActive : styles.btn}
            onClick={() => setKind('realized')}
          >
            Realized P&amp;L
          </button>
        </div>
        <div className={styles.group}>
          <Text size={10} tone="dim">AXIS</Text>
          {(['day', 'week', 'month'] as Granularity[]).map((g) => (
            <button
              key={g}
              type="button"
              className={gran === g ? styles.btnActive : styles.btn}
              onClick={() => setGran(g)}
            >
              {g === 'day' ? 'Days' : g === 'week' ? 'Weeks' : 'Months'}
            </button>
          ))}
        </div>
      </div>
      <div className={styles.chartArea}>
        <div ref={containerRef} className={styles.chart} />
        {empty && (
          <div className={styles.empty}>
            <Text size={12} tone="secondary">No performance data yet.</Text>
          </div>
        )}
      </div>
    </div>
  );
}
