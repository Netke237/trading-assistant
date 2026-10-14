'use client';

import { useEffect, useMemo, useState } from 'react';
import { CandlestickChart } from '@/components/organisms/CandlestickChart';
import { Data, Text } from '@/components/primitives';
import { api } from '@/lib/api';
import type { Candle } from '@/types/chart';
import type { FibPullbackResultRow, PositionCardData, PreBreakoutResultRow } from '@/types/stockDomain';
import type { ScanMode, ScanSnapshot } from './scanThresholds';
import { scanChartLines } from './scanChartLines';
import styles from './page.module.css';

type SetupRow = PreBreakoutResultRow | FibPullbackResultRow | PositionCardData;
type ChartState = {row: SetupRow; scope: object; snapshot?: ScanSnapshot; status: 'ready'; candles: Candle[]} |
  {row: SetupRow; scope: object; snapshot?: ScanSnapshot; status: 'error'};

/** Daily symbol-only candles: api.getCandles has no interval parameter.
 * The predecessor MiniChart stale guard now includes the exact row/run scope. */
export function SelectedSetupChart({row, mode, scope, snapshot}: {row: SetupRow; mode: ScanMode; scope: object; snapshot?: ScanSnapshot}) {
  const [state, setState] = useState<ChartState | null>(null);
  const priceLines = useMemo(() => scanChartLines(row, mode), [row, mode]);
  useEffect(() => {
    let cancelled = false;
    setState(null);
    void (async () => {
      try {
        const candles = await api.getCandles(row.symbol);
        if (!cancelled) setState({row, scope, snapshot, status: 'ready', candles});
      } catch {
        if (!cancelled) setState({row, scope, snapshot, status: 'error'});
      }
    })();
    return () => {cancelled = true;};
  }, [row, scope, snapshot]);

  // Do not show old candles during the render before the effect resets state.
  const current = state?.row === row && state.scope === scope && state.snapshot === snapshot ? state : null;
  return <div className={styles.selectedChart}>
    <div className={styles.chartMeta}>
      <Text size={12} tone="secondary">{'company' in row && row.company ? row.company : 'Company unavailable'}</Text>
      <Text size={12} tone={row.direction === 'Bullish' ? 'pass' : row.direction === 'Bearish' ? 'reject' : 'dim'}>{row.direction}</Text>
      {'price' in row && Number.isFinite(row.price) && <Data size={13}>${row.price.toFixed(2)}</Data>}
      <Text size={11} tone="dim">Daily candles</Text>
    </div>
    {!current ? <Text size={12} tone="dim">Loading chart…</Text>
      : current.status === 'error' ? <Text size={12} tone="dim">Chart unavailable for {row.symbol}.</Text>
      : current.candles.length === 0 ? <Text size={12} tone="dim">No daily candles available for {row.symbol}.</Text>
      : <CandlestickChart data={current.candles} height={280} defaultIndicators={['volume', 'rsi']} priceLines={priceLines}/>}
    <Text size={11} tone="dim">{priceLines.length ? 'Price lines show scan evidence.' : 'Scan price levels unavailable.'}</Text>
  </div>;
}
