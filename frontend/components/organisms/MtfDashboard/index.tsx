'use client';
import { Text } from '@/components/primitives';
import type { MtfRow } from '@/types/overlays';
import styles from './MtfDashboard.module.css';

export default function MtfDashboard({ rows }: { rows: MtfRow[] }) {
  if (rows.length === 0) return null;
  return (
    <div className={styles.box}>
      <div className={styles.head}>
        <Text size={10} tone="dim">TF</Text>
        <Text size={10} tone="dim">Trend</Text>
        <Text size={10} tone="dim">RSI</Text>
        <Text size={10} tone="dim">Chg%</Text>
      </div>
      {rows.map((r) => (
        <div key={r.tf} className={styles.row}>
          <Text size={11}>{r.tf}</Text>
          <Text size={11} tone={r.trendUp ? 'pass' : 'reject'}>{r.trendUp ? '▲' : '▼'}</Text>
          <Text size={11}>{r.rsi.toFixed(0)}</Text>
          <Text size={11} tone={r.changePct >= 0 ? 'pass' : 'reject'}>{r.changePct.toFixed(1)}</Text>
        </div>
      ))}
    </div>
  );
}
