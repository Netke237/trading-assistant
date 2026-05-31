'use client';

/*
 * EarningsChart — two lightweight-charts line series:
 *  - Realized profit (cumulative, from closed trades)
 *  - Total account value (realized + open mark, from daily equity snapshots)
 * Reads theme tokens at mount, like CandlestickChart.
 */

import { useEffect, useRef } from 'react';
import { createChart, LineSeries, type IChartApi, type Time } from 'lightweight-charts';
import { useThemeStore } from '@/lib/theme';
import type { PerfPoint } from '@/lib/performanceStore';
import styles from './EarningsChart.module.css';

interface Props {
  realizedCurve: PerfPoint[];
  equityCurve: PerfPoint[];
  height?: number;
}

function token(name: string): string {
  if (typeof window === 'undefined') return '';
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function toLine(points: PerfPoint[]) {
  // lightweight-charts wants ascending unique times; backend already sorts.
  return points.map((p) => ({ time: p.date as Time, value: p.value }));
}

export function EarningsChart({ realizedCurve, equityCurve, height = 260 }: Props) {
  const theme = useThemeStore((s) => s.theme);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const chart: IChartApi = createChart(el, {
      height,
      layout: {
        background: { color: token('--bg-surface') || '#1E2335' },
        textColor: token('--text-secondary') || '#787B86',
      },
      grid: {
        vertLines: { color: token('--border-subtle') || '#2A2E42' },
        horzLines: { color: token('--border-subtle') || '#2A2E42' },
      },
      rightPriceScale: { borderColor: token('--border-subtle') || '#2A2E42' },
      timeScale: { borderColor: token('--border-subtle') || '#2A2E42' },
    });

    const equity = chart.addSeries(LineSeries, {
      color: token('--accent') || '#4C8DFF', lineWidth: 2, title: 'Account value',
    });
    const realized = chart.addSeries(LineSeries, {
      color: token('--pass') || '#27c08a', lineWidth: 2, title: 'Realized',
    });

    equity.setData(toLine(equityCurve));
    realized.setData(toLine(realizedCurve));
    chart.timeScale().fitContent();

    const ro = new ResizeObserver(() => chart.applyOptions({ width: el.clientWidth }));
    ro.observe(el);
    chart.applyOptions({ width: el.clientWidth });

    return () => { ro.disconnect(); chart.remove(); };
  }, [realizedCurve, equityCurve, height, theme]);

  return <div ref={containerRef} className={styles.chart} />;
}
