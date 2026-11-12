'use client';

import { type ReactNode, useState } from 'react';
import { Text, Data } from '@/components/primitives';
import styles from './StockPositionCard.module.css';

type View = 'ladder' | 'monteCarlo' | 'arithmetic';
const methods: { key: View; name: string; region: string }[] = [
  { key: 'ladder', name: 'Ladder', region: 'Original ladder evidence' },
  { key: 'monteCarlo', name: 'Monte Carlo', region: 'Monte Carlo evidence' },
  { key: 'arithmetic', name: 'Arithmetic', region: 'Arithmetic evidence' },
];

/** Viewing is local presentation state; execution intent remains in MethodPickSelector. */
export function StockMethodWorkspace({ ladder, monteCarlo, arithmetic }: Record<View, ReactNode>) {
  const [view, setView] = useState<View>('ladder');
  const [compare, setCompare] = useState(false);
  const [compared, setCompared] = useState<View[]>(['monteCarlo', 'arithmetic']);
  const content = { ladder, monteCarlo, arithmetic };
  const visible = compare ? compared : [view];
  return <>
    <div role="group" aria-label="View method results" className={styles.methodViews}>
      {methods.map(({ key, name }) => <button key={key} type="button" className={styles.actionBtn}
        aria-pressed={visible.includes(key)} disabled={compare && compared.length === 2 && compared.includes(key)}
        onClick={() => compare ? setCompared(current => current.includes(key) ? current.filter(item => item !== key) : [...current, key]) : setView(key)}>{name}</button>)}
      <button type="button" className={styles.actionBtn} aria-pressed={compare} onClick={() => setCompare(current => !current)}>Compare</button>
    </div>
    <Text size={11} tone="dim">Viewing or comparing performs no calculation and does not choose a method for this trade.</Text>
    <div className={compare ? styles.methodComparison : styles.methodSingle}>
      {methods.map(({ key, region }) => <section key={key} aria-label={region} hidden={!visible.includes(key)}
        data-testid={visible.includes(key) ? 'visible-method-card' : undefined} className={styles.methodCard}>{content[key]}</section>)}
    </div>
  </>;
}

export function MethodResults({ rows, shares, window }: {
  rows: { label: string; labelTone?: 'dim'; price: string; priceTone?: 'pass'; probability?: number; days?: number | null; outcome: string }[];
  shares: number; window?: number;
}) {
  return <div className={styles.methodResults}>
    <Text size={11} tone="secondary">Probability window: {window == null ? 'Not supplied' : `${window} trading days`}</Text>
    <table className={styles.resultTable}>
      <thead><tr>{['Target', 'Stock price', 'Probability', 'Conditional median', `Full exit / ${shares} shares`].map(label => <th key={label} scope="col"><Text size={11} tone="secondary">{label}</Text></th>)}</tr></thead>
      <tbody>{rows.map((row, i) => <tr key={i}>
        <th scope="row"><Text size={12} tone={row.labelTone}>{row.label}</Text></th>
        <td><Data size={12} tone={row.priceTone}>{row.price}</Data></td>
        <td><Data size={12} tone={row.probability == null ? 'dim' : row.probability >= .5 ? 'pass' : row.probability >= .25 ? 'caution' : 'reject'}>{row.probability == null ? 'Not supplied' : `${(row.probability * 100).toFixed(0)}%`}</Data></td>
        <td><Data size={12} tone="dim">{row.probability == null ? 'Not supplied' : row.days == null ? 'unlikely' : `~${row.days} trading days`}</Data></td>
        <td><Data size={12}>{row.outcome}</Data></td>
      </tr>)}</tbody>
    </table>
  </div>;
}
