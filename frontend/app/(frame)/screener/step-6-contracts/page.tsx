'use client';

/*
 * Screener Step 6 — Contracts. Phase 5.
 * Scored option contracts for the currently-selected symbol, enriched with
 * PRICE, IV RANK, IV PCTL, Θ/DAY and VOLUME. Clickable column headers sort
 * the table. Each row has a star that writes to useWatchedContractsStore,
 * and the selection radio at the right marks the contract feeding Step 7.
 */

import { useMemo, useState } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { TableRow } from '@/components/molecules/TableRow';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { DTEProgressBar } from '@/components/molecules/DTEProgressBar';
import { ContractStar } from '@/components/atoms/ContractStar';
import { statusForScore } from '@/lib/status';
import { MOCK_CONTRACTS, contractLabel, type OptionContract } from '@/mocks/contracts';
import styles from '../screener.module.css';
import tbl from './contracts.module.css';

const COLUMNS = '28px minmax(120px, 1fr) 90px 56px 60px 60px 60px 64px 56px 60px 96px 44px';

type SortKey =
  | 'contract' | 'dte' | 'delta' | 'price'
  | 'ivRank' | 'ivPercentile' | 'theta'
  | 'spread' | 'volume' | 'score';

type SortDir = 'asc' | 'desc';

export default function Step6Page() {
  const [pick, setPick] = useState<string>(MOCK_CONTRACTS[0]!.id);
  const [sortKey, setSortKey] = useState<SortKey>('score');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  const sorted = useMemo<OptionContract[]>(() => {
    const rows = [...MOCK_CONTRACTS];
    const mul = sortDir === 'asc' ? 1 : -1;
    rows.sort((a, b) => {
      switch (sortKey) {
        case 'contract':
          return contractLabel(a).localeCompare(contractLabel(b)) * mul;
        default:
          return ((a[sortKey] as number) - (b[sortKey] as number)) * mul;
      }
    });
    return rows;
  }, [sortKey, sortDir]);

  const toggleSort = (k: SortKey) => {
    if (k === sortKey) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else {
      setSortKey(k);
      setSortDir(k === 'contract' ? 'asc' : 'desc');
    }
  };

  return (
    <div className={styles.main}>
      <div className={styles.stepHeader}>
        <Text size={11} tone="dim" weight={500}>STEP 6 OF 7</Text>
        <Title as="h1" size={24}>Contracts — AAPL</Title>
        <Text size={13} tone="secondary">
          Scored by DTE fit, delta, IV attractiveness, liquidity and spread. Click a column to sort,
          star a contract to track it in the Watchlist.
        </Text>
      </div>

      <div className={tbl.headerRow} style={{ gridTemplateColumns: COLUMNS }}>
        <span aria-hidden />
        <SortBtn label="CONTRACT" k="contract" sortKey={sortKey} dir={sortDir} onClick={toggleSort} />
        <SortBtn label="DTE"      k="dte"      sortKey={sortKey} dir={sortDir} onClick={toggleSort} />
        <SortBtn label="DELTA"    k="delta"    sortKey={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
        <SortBtn label="PRICE"    k="price"    sortKey={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
        <SortBtn label="IV RANK"  k="ivRank"   sortKey={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
        <SortBtn label="IV PCTL"  k="ivPercentile" sortKey={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
        <SortBtn label="Θ/DAY"    k="theta"    sortKey={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
        <SortBtn label="SPREAD"   k="spread"   sortKey={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
        <SortBtn label="VOL"      k="volume"   sortKey={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
        <SortBtn label="SCORE"    k="score"    sortKey={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
        <Text size={11} tone="dim">PICK</Text>
      </div>

      {sorted.map((c) => {
        const status = statusForScore(c.score);
        return (
          <TableRow
            key={c.id}
            status={status}
            columns={COLUMNS}
            selected={c.id === pick}
            onClick={() => setPick(c.id)}
          >
            <ContractStar contractId={c.id} size="sm" />
            <Data size={13} weight={500}>{contractLabel(c)}</Data>
            <DTEProgressBar daysRemaining={c.dte} totalDays={c.dteTotal} />
            <Data size={12} className={tbl.right}>{c.delta.toFixed(2)}</Data>
            <Data size={12} className={tbl.right}>${c.price.toFixed(2)}</Data>
            <Data size={12} className={tbl.right}>{c.ivRank}</Data>
            <Data size={12} className={tbl.right}>{c.ivPercentile}</Data>
            <Data size={12} className={tbl.right}>{c.theta.toFixed(2)}</Data>
            <Data size={12} className={tbl.right}>${c.spread.toFixed(2)}</Data>
            <Data size={12} className={tbl.right}>{c.volume.toLocaleString()}</Data>
            <div className={tbl.scoreCell}>
              <Data size={13} weight={500}>{c.score}</Data>
              <StatusBadge status={status} />
            </div>
            <span
              aria-label={c.id === pick ? 'Selected' : 'Select'}
              className={tbl.pickDot}
              data-selected={c.id === pick ? 'true' : 'false'}
            />
          </TableRow>
        );
      })}
    </div>
  );
}

function SortBtn({
  label,
  k,
  sortKey,
  dir,
  onClick,
  align,
}: {
  label:   string;
  k:       SortKey;
  sortKey: SortKey;
  dir:     SortDir;
  onClick: (k: SortKey) => void;
  align?:  'left' | 'right';
}) {
  const active = sortKey === k;
  return (
    <button
      type="button"
      onClick={() => onClick(k)}
      className={`${tbl.sortBtn} ${align === 'right' ? tbl.sortRight : ''} ${active ? tbl.sortActive : ''}`}
    >
      {label} {active ? (dir === 'asc' ? '↑' : '↓') : ''}
    </button>
  );
}
