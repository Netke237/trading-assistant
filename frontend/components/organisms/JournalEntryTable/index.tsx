'use client';

/*
 * JournalEntryTable — sortable list table for journal entries.
 *
 * Sorting is CLIENT-SIDE over the `entries` array it's given — the backend
 * has no sort_by/sort_dir query param, only a fixed `entry_date desc`
 * server-side default, which this table's initial sortKey/sortDir mirror.
 * Any frequently-null column (net_pnl, execution_grade, or a trade-only
 * column on a 'note' row) sorts nulls last in BOTH directions, so notes/
 * open trades don't scatter unpredictably through a numeric/string sort.
 *
 * Row click opens the edit form (not an inline expand) — see the plan's Page
 * section.
 */

import { useMemo, useState } from 'react';
import { Text, Data } from '@/components/primitives';
import { RMultipleBadge } from '@/components/atoms/RMultipleBadge';
import type { JournalEntry } from '@/types/journal';
import styles from './JournalEntryTable.module.css';

type SortKey = 'entry_date' | 'symbol' | 'strategy_tag' | 'status' | 'net_pnl' | 'execution_grade';
type SortDir = 'asc' | 'desc';

const COLUMNS = '104px 56px 84px 1fr 76px 140px 56px 28px';

interface JournalEntryTableProps {
  entries: JournalEntry[];
  onRowClick: (entry: JournalEntry) => void;
  onDeleteClick: (entry: JournalEntry) => void;
}

function compareNullable<T>(
  a: T | null | undefined,
  b: T | null | undefined,
  cmp: (a: T, b: T) => number,
  dir: SortDir,
): number {
  const aNull = a == null;
  const bNull = b == null;
  if (aNull && bNull) return 0;
  if (aNull) return 1; // nulls last, regardless of direction
  if (bNull) return -1;
  return cmp(a as T, b as T) * (dir === 'asc' ? 1 : -1);
}

const numCmp = (a: number, b: number) => a - b;
const strCmp = (a: string, b: string) => a.localeCompare(b);

export function JournalEntryTable({ entries, onRowClick, onDeleteClick }: JournalEntryTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>('entry_date');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir(key === 'symbol' || key === 'strategy_tag' || key === 'status' ? 'asc' : 'desc');
    }
  };

  const sorted = useMemo(() => {
    const rows = [...entries];
    rows.sort((a, b) => {
      switch (sortKey) {
        case 'symbol':          return compareNullable(a.symbol, b.symbol, strCmp, sortDir);
        case 'strategy_tag':    return compareNullable(a.strategy_tag, b.strategy_tag, strCmp, sortDir);
        case 'status':          return compareNullable(a.status, b.status, strCmp, sortDir);
        case 'net_pnl':         return compareNullable(a.net_pnl, b.net_pnl, numCmp, sortDir);
        case 'execution_grade': return compareNullable(a.execution_grade, b.execution_grade, numCmp, sortDir);
        case 'entry_date':
        default:                return compareNullable(a.entry_date, b.entry_date, strCmp, sortDir);
      }
    });
    return rows;
  }, [entries, sortKey, sortDir]);

  if (entries.length === 0) {
    return (
      <div className={styles.empty}>
        <Text size={14} tone="secondary">No journal entries yet.</Text>
        <Text size={12} tone="dim">Log a trade or a daily note with &ldquo;New entry&rdquo; above.</Text>
      </div>
    );
  }

  return (
    <div className={styles.tableWrap}>
      <div className={styles.tableHeader} style={{ gridTemplateColumns: COLUMNS }}>
        <SortBtn label="DATE"       active={sortKey === 'entry_date'}      dir={sortDir} onClick={() => toggleSort('entry_date')} />
        <Text size={11} tone="dim">TYPE</Text>
        <SortBtn label="SYMBOL"     active={sortKey === 'symbol'}          dir={sortDir} onClick={() => toggleSort('symbol')} />
        <SortBtn label="STRATEGY"   active={sortKey === 'strategy_tag'}    dir={sortDir} onClick={() => toggleSort('strategy_tag')} />
        <SortBtn label="STATUS"     active={sortKey === 'status'}          dir={sortDir} onClick={() => toggleSort('status')} />
        <SortBtn label="NET P&L / R" active={sortKey === 'net_pnl'}        dir={sortDir} onClick={() => toggleSort('net_pnl')} align="right" />
        <SortBtn label="GRADE"      active={sortKey === 'execution_grade'} dir={sortDir} onClick={() => toggleSort('execution_grade')} align="right" />
        <span aria-hidden />
      </div>

      <div className={styles.tableBody}>
        {sorted.map((entry) => (
          <div
            key={entry.id}
            role="button"
            tabIndex={0}
            className={styles.row}
            style={{ gridTemplateColumns: COLUMNS }}
            onClick={() => onRowClick(entry)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onRowClick(entry);
              }
            }}
          >
            <Data size={12}>{formatDate(entry.entry_date)}</Data>
            <span className={entry.entry_type === 'trade' ? styles.typeTrade : styles.typeNote}>
              {entry.entry_type === 'trade' ? 'Trade' : 'Note'}
            </span>
            <Data size={12} weight={500}>{entry.symbol ?? '—'}</Data>
            <Text size={12} tone="secondary" className={styles.ellipsis}>{entry.strategy_tag ?? '—'}</Text>
            {entry.status
              ? <span className={entry.status === 'open' ? styles.statusOpen : styles.statusClosed}>{entry.status}</span>
              : <Text size={11} tone="dim">—</Text>}
            <div className={styles.right}>
              <RMultipleBadge netPnl={entry.net_pnl} rMultiple={entry.r_multiple} />
            </div>
            <Data size={12} className={styles.right}>{entry.execution_grade ?? '—'}</Data>
            <button
              type="button"
              className={styles.deleteBtn}
              title="Delete entry"
              aria-label="Delete entry"
              onClick={(e) => { e.stopPropagation(); onDeleteClick(entry); }}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleDateString(undefined, { year: 'numeric', month: '2-digit', day: '2-digit' });
}

function SortBtn({
  label,
  active,
  dir,
  onClick,
  align,
}: {
  label: string;
  active: boolean;
  dir: SortDir;
  onClick: () => void;
  align?: 'left' | 'right';
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`${styles.sortBtn} ${align === 'right' ? styles.sortRight : ''} ${active ? styles.sortActive : ''}`}
    >
      {label} {active ? (dir === 'asc' ? '↑' : '↓') : ''}
    </button>
  );
}
