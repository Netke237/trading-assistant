import React from 'react';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import type { Status } from '@/lib/status';
import type { ScanReportCategory } from '@/lib/scanReports';
import styles from './SavedScanResultsTable.module.css';

interface Props {
  category: ScanReportCategory | 'legacy';
  rows: Record<string, unknown>[];
}

const statuses: readonly string[] = ['PASS', 'CAUTION', 'REJECT', 'PENDING', 'NO_DATA'];
function recorded(row: Record<string, unknown>, key: string): unknown {
  return row[`${key}_unavailable`] === true ? undefined : row[key];
}
function text(value: unknown): string {
  return typeof value === 'string' && value.trim() ? value : 'Unavailable';
}
function number(value: unknown, prefix = ''): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${prefix}${value}` : 'Unavailable';
}

export function SavedScanResultsTable({ category, rows }: Props) {
  const legacy = category === 'legacy';
  const stock = category === 'options' || category === 'stocks' || category === 'pullback';
  const scoreKey = category === 'options' ? 'stockScore' : 'stock_score';
  const statusKey = category === 'options' ? 'stockConfidence' : 'stock_status';
  return <div className={styles.scroll}>
    <table className={styles.table}>
      <caption>{legacy ? 'Saved candidate records' : 'Saved accepted results'}</caption>
      <thead><tr>
        <th scope="col">Symbol</th><th scope="col">Direction</th>
        {stock && <th scope="col">Price</th>}
        {!legacy && <th scope="col">{stock ? 'Stock score' : 'Confidence'}</th>}
        {stock && <th scope="col">Stock status</th>}
        <th scope="col">Recorded details</th>
      </tr></thead>
      <tbody>{rows.map((row, index) => {
        const status = recorded(row, statusKey);
        return <tr key={index}>
          <th scope="row">{text(recorded(row, 'symbol'))}</th>
          <td>{text(recorded(row, 'direction'))}</td>
          {stock && <td className={styles.numeric}>{number(recorded(row, 'price'), '$')}</td>}
          {!legacy && <td className={styles.numeric}>{number(recorded(row, stock ? scoreKey : 'confidence'))}</td>}
          {stock && <td>{typeof status === 'string' && statuses.includes(status)
            ? <StatusBadge status={status as Status} /> : 'Unavailable'}</td>}
          <td><details className={styles.record}><summary>Raw record</summary><pre>{JSON.stringify(row, null, 2)}</pre></details></td>
        </tr>;
      })}</tbody>
    </table>
    {rows.length === 0 && <p className={styles.empty}>{legacy ? 'No candidate records saved.' : 'No accepted results recorded.'}</p>}
  </div>;
}
