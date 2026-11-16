/*
 * BacktestTradeTable — readable rows of recorded closed trades with an Inspect button each.
 * Purely presentational: the caller formats the values and owns sorting, paging and selection
 * (always by the trade's stable id).
 */
import { Text, Data } from '@/components/primitives';
import type { DataTone } from '@/components/primitives/Data';
import styles from './BacktestTradeTable.module.css';

export interface TradeRowView {
  id: string;
  /** e.g. "Trade #a · Bearish" */
  label: string;
  entry: string;
  exit: string;
  /** Normally formatted entry / exit fills; full precision belongs to the inspector. */
  prices: string;
  /** The recorded net return, formatted. */
  returnText: string;
  returnTone: DataTone;
  reason: string;
}

interface BacktestTradeTableProps {
  rows: TradeRowView[];
  selectedId: string | null;
  onInspect: (id: string) => void;
  /** Receives each Inspect button so the caller can restore focus after clearing. */
  inspectRef?: (id: string, element: HTMLButtonElement | null) => void;
}

const HEADERS = ['Trade', 'Entry (UTC)', 'Exit (UTC)', 'Entry / exit price', 'Net return¹', 'Exit reason', 'On chart'];

export function BacktestTradeTable({ rows, selectedId, onInspect, inspectRef }: BacktestTradeTableProps) {
  return (
    <div className={styles.wrap}>
      <table className={styles.table} aria-label="Closed trades">
        <thead>
          <tr>{HEADERS.map(h => <th key={h} scope="col" className={styles.th}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr><td colSpan={HEADERS.length} className={styles.empty}><Text size={12} tone="secondary">No closed trades recorded for this run.</Text></td></tr>
          ) : rows.map(row => {
            const selected = row.id === selectedId;
            return (
              <tr key={row.id} className={selected ? `${styles.row} ${styles.selected}` : styles.row} aria-current={selected ? 'true' : undefined}>
                <td className={styles.td}><Data size={11}>{row.label}</Data></td>
                <td className={styles.td}><Data size={11}>{row.entry}</Data></td>
                <td className={styles.td}><Data size={11}>{row.exit}</Data></td>
                <td className={styles.td}><Data size={11}>{row.prices}</Data></td>
                <td className={styles.td}><Data size={11} tone={row.returnTone}>{row.returnText}</Data></td>
                <td className={`${styles.td} ${styles.wrapCell}`}><Data size={11}>{row.reason}</Data></td>
                <td className={styles.td}>
                  <button type="button" className={styles.inspect} aria-label={`Inspect trade ${row.id}`}
                    ref={inspectRef ? el => inspectRef(row.id, el) : undefined} onClick={() => onInspect(row.id)}>
                    Inspect ↗
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
