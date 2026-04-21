'use client';

/*
 * Watchlist — Phase 5.
 * Sortable table of ranked candidates + inline candlestick chart for the
 * selected symbol (Framer Motion slide-in). Drift log Screen 4.
 */

import { useMemo, useState } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { TableRow } from '@/components/molecules/TableRow';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { RankDelta } from '@/components/atoms/RankDelta';
import { EventFlag } from '@/components/atoms/EventFlag';
import { InlineChartPanel } from '@/components/organisms/InlineChartPanel';
import { WatchStar } from '@/components/atoms/WatchStar';
import { MOCK_WATCHLIST } from '@/mocks/watchlist';
import type { WatchlistRow } from '@/types/domain';
import styles from './page.module.css';

type SortKey = 'score' | 'symbol' | 'price' | 'rank';
type SortDir = 'asc' | 'desc';

const COLUMNS = '32px 72px 1.4fr 90px 80px 80px 90px 80px 90px';

export default function WatchlistPage() {
  const [sortKey, setSortKey] = useState<SortKey>('score');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [selected, setSelected] = useState<string | null>(null);

  const sorted = useMemo<WatchlistRow[]>(() => {
    const rows = [...MOCK_WATCHLIST];
    rows.sort((a, b) => {
      const mul = sortDir === 'asc' ? 1 : -1;
      switch (sortKey) {
        case 'symbol': return a.symbol.localeCompare(b.symbol) * mul;
        case 'price':  return (a.price - b.price) * mul;
        case 'rank':   return (a.rankDelta - b.rankDelta) * mul;
        case 'score':
        default:       return (a.score - b.score) * mul;
      }
    });
    return rows;
  }, [sortKey, sortDir]);

  const toggleSort = (k: SortKey) => {
    if (k === sortKey) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else { setSortKey(k); setSortDir(k === 'symbol' ? 'asc' : 'desc'); }
  };

  const onSelect = (symbol: string) => {
    setSelected((cur) => (cur === symbol ? null : symbol));
  };

  return (
    <div className={styles.main}>
      <div className={styles.heading}>
        <Title as="h1" size={24}>Watchlist</Title>
        <Text size={13} tone="secondary">
          {MOCK_WATCHLIST.length} candidates · sorted by {sortKey} {sortDir === 'asc' ? '↑' : '↓'}
        </Text>
      </div>

      <div className={styles.tableWrap}>
        <div className={styles.tableHeader} style={{ gridTemplateColumns: COLUMNS }}>
          <span aria-hidden />
          <SortBtn label="SYMBOL" active={sortKey === 'symbol'} dir={sortDir} onClick={() => toggleSort('symbol')} />
          <Text size={11} tone="dim">NAME</Text>
          <SortBtn label="PRICE" active={sortKey === 'price'} dir={sortDir} onClick={() => toggleSort('price')} align="right" />
          <Text size={11} tone="dim">DIR</Text>
          <Text size={11} tone="dim">HORIZON</Text>
          <SortBtn label="SCORE" active={sortKey === 'score'} dir={sortDir} onClick={() => toggleSort('score')} align="right" />
          <SortBtn label="RANK Δ" active={sortKey === 'rank'} dir={sortDir} onClick={() => toggleSort('rank')} />
          <Text size={11} tone="dim">NEXT EVENT</Text>
        </div>

        <div className={styles.tableBody}>
          {sorted.map((row) => (
            <TableRow
              key={row.symbol}
              status={row.status}
              columns={COLUMNS}
              selected={selected === row.symbol}
              onClick={() => onSelect(row.symbol)}
            >
              <WatchStar symbol={row.symbol} size="sm" />
              <Data size={13} weight={500}>{row.symbol}</Data>
              <Text size={12} tone="secondary">{row.company}</Text>
              <Data size={12} weight={500} className={styles.right}>${row.price.toFixed(2)}</Data>
              <span className={row.direction === 'Bullish' ? styles.dirBull : styles.dirBear}>
                {row.direction === 'Bullish' ? 'Bull' : 'Bear'}
              </span>
              <Text size={11} tone="secondary">{row.horizon}</Text>
              <div className={styles.scoreCell}>
                <Data size={13} weight={500}>{row.score}</Data>
                <StatusBadge status={row.status} />
              </div>
              <RankDelta value={row.rankDelta} />
              {row.nextEventDays !== undefined
                ? <EventFlag days={row.nextEventDays} title={row.nextEventLabel} />
                : <Text size={11} tone="dim">—</Text>}
            </TableRow>
          ))}
        </div>
      </div>

      <InlineChartPanel
        open={selected !== null}
        symbol={selected ?? ''}
        onClose={() => setSelected(null)}
      />
    </div>
  );
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
