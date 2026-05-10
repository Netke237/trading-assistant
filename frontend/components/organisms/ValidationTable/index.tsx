'use client';

import { useState, useMemo } from 'react';
import { Text, Data } from '@/components/primitives';
import { TableRow } from '@/components/molecules/TableRow';
import { Pagination } from '@/components/molecules/Pagination';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { statusForScore } from '@/lib/status';
import type { TradeCardData } from '@/types/domain';
import styles from './ValidationTable.module.css';

const PAGE_SIZE = 10;

const COLUMNS = '1fr 56px 48px 48px 48px 48px 48px 48px 64px';

interface ValidationTableProps {
  candidates: TradeCardData[];
}

export function ValidationTable({ candidates }: ValidationTableProps) {
  const [currentPage, setCurrentPage] = useState(1);

  const paginated = useMemo(() => {
    const start = (currentPage - 1) * PAGE_SIZE;
    return candidates.slice(start, start + PAGE_SIZE);
  }, [candidates, currentPage]);

  if (candidates.length === 0) {
    return (
      <div className={styles.wrap}>
        <Text size={13} tone="dim">No scan data. Run a scan to see validation results.</Text>
      </div>
    );
  }

  return (
    <div className={styles.wrap}>
      <header className={styles.panelHeader}>
        <Text size={13} weight={600}>Validation Table</Text>
        <Text size={11} tone="secondary">{candidates.length} candidates</Text>
      </header>

      <div className={styles.tableHeader} style={{ gridTemplateColumns: COLUMNS }}>
        <Text size={11} tone="dim">SYMBOL</Text>
        <Text size={11} tone="dim">DIR</Text>
        <Text size={11} tone="dim">TREND</Text>
        <Text size={11} tone="dim">PULLBACK</Text>
        <Text size={11} tone="dim">TRIGGER</Text>
        <Text size={11} tone="dim">EVENT</Text>
        <Text size={11} tone="dim">VOL</Text>
        <Text size={11} tone="dim">SCORE</Text>
        <Text size={11} tone="dim">STATUS</Text>
      </div>

      <div className={styles.tableBody}>
        {paginated.map((c) => {
          const trendStatus = statusForScore(c.stockBreakdown.trend, 100);
          const pullbackStatus = statusForScore(c.stockBreakdown.pullback, 100);
          const triggerStatus = statusForScore(c.stockBreakdown.trigger, 100);
          const eventStatus = statusForScore(c.stockBreakdown.event, 100);
          const volStatus = statusForScore(c.stockBreakdown.volatility, 100);

          return (
            <TableRow key={c.symbol} status={c.finalStatus} columns={COLUMNS}>
              <div className={styles.symCell}>
                <Data size={12} weight={500}>{c.symbol}</Data>
                <Text size={11} tone="secondary">{c.company}</Text>
              </div>
              <Data size={11} weight={500}>{c.direction === 'Bullish' ? '↑' : '↓'}</Data>
              <Data size={12} weight={500} tone={trendStatus === 'PASS' ? 'pass' : trendStatus === 'CAUTION' ? 'caution' : 'reject'}>
                {c.stockBreakdown.trend}
              </Data>
              <Data size={12} weight={500} tone={pullbackStatus === 'PASS' ? 'pass' : pullbackStatus === 'CAUTION' ? 'caution' : 'reject'}>
                {c.stockBreakdown.pullback}
              </Data>
              <Data size={12} weight={500} tone={triggerStatus === 'PASS' ? 'pass' : triggerStatus === 'CAUTION' ? 'caution' : 'reject'}>
                {c.stockBreakdown.trigger}
              </Data>
              <Data size={12} weight={500} tone={eventStatus === 'PASS' ? 'pass' : eventStatus === 'CAUTION' ? 'caution' : 'reject'}>
                {c.stockBreakdown.event}
              </Data>
              <Data size={12} weight={500} tone={volStatus === 'PASS' ? 'pass' : volStatus === 'CAUTION' ? 'caution' : 'reject'}>
                {c.stockBreakdown.volatility}
              </Data>
              <Data size={13} weight={500}>{c.stockScore}</Data>
              <StatusBadge status={c.finalStatus} />
            </TableRow>
          );
        })}
      </div>

      <Pagination
        totalItems={candidates.length}
        pageSize={PAGE_SIZE}
        currentPage={currentPage}
        onPageChange={setCurrentPage}
      />
    </div>
  );
}
