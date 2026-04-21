'use client';

/*
 * Screener Step 6 — Contracts. Phase 5.
 * Scored option contracts for the currently-selected symbol. Clicking a row
 * "selects" that contract (no store wiring yet — Phase 6 persists choice and
 * pre-fills Step 7 TradeCard).
 */

import { useState } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { TableRow } from '@/components/molecules/TableRow';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { DTEProgressBar } from '@/components/molecules/DTEProgressBar';
import { statusForScore } from '@/lib/status';
import styles from '../screener.module.css';

const COLUMNS = 'minmax(200px, 1fr) 140px 80px 72px 90px 120px 56px';

interface ContractRow {
  contract: string;
  dte: number;
  dteTotal: number;
  delta: number;
  iv:    number;
  spread: number;   // $
  score: number;
}

const MOCK_CONTRACTS: ContractRow[] = [
  { contract: 'AAPL 190C 05/16', dte: 28, dteTotal: 38, delta: 0.45, iv: 26, spread: 0.05, score: 82 },
  { contract: 'AAPL 195C 05/16', dte: 28, dteTotal: 38, delta: 0.38, iv: 27, spread: 0.06, score: 78 },
  { contract: 'AAPL 190C 06/20', dte: 63, dteTotal: 71, delta: 0.48, iv: 24, spread: 0.08, score: 73 },
  { contract: 'AAPL 200C 05/16', dte: 28, dteTotal: 38, delta: 0.32, iv: 28, spread: 0.07, score: 67 },
  { contract: 'AAPL 185C 04/25', dte:  7, dteTotal: 17, delta: 0.58, iv: 32, spread: 0.04, score: 54 },
  { contract: 'AAPL 210C 05/16', dte: 28, dteTotal: 38, delta: 0.22, iv: 30, spread: 0.12, score: 42 },
];

export default function Step6Page() {
  const [pick, setPick] = useState(MOCK_CONTRACTS[0]!.contract);

  return (
    <div className={styles.main}>
      <div className={styles.stepHeader}>
        <Text size={11} tone="dim" weight={500}>STEP 6 OF 7</Text>
        <Title as="h1" size={24}>Contracts — AAPL</Title>
        <Text size={13} tone="secondary">
          Scored by DTE fit, delta, IV attractiveness, liquidity and spread. Click a row to select.
        </Text>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: COLUMNS, gap: 12, padding: '0 4px' }}>
        <Text size={11} tone="dim">CONTRACT</Text>
        <Text size={11} tone="dim">DTE</Text>
        <Text size={11} tone="dim">DELTA</Text>
        <Text size={11} tone="dim">IV%</Text>
        <Text size={11} tone="dim">SPREAD</Text>
        <Text size={11} tone="dim">SCORE</Text>
        <Text size={11} tone="dim">PICK</Text>
      </div>

      {MOCK_CONTRACTS.map((c) => {
        const status = statusForScore(c.score);
        return (
          <TableRow
            key={c.contract}
            status={status}
            columns={COLUMNS}
            selected={c.contract === pick}
            onClick={() => setPick(c.contract)}
          >
            <Data size={13} weight={500}>{c.contract}</Data>
            <DTEProgressBar daysRemaining={c.dte} totalDays={c.dteTotal} />
            <Data size={12}>{c.delta.toFixed(2)}</Data>
            <Data size={12}>{c.iv}</Data>
            <Data size={12}>${c.spread.toFixed(2)}</Data>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Data size={13} weight={500}>{c.score}</Data>
              <StatusBadge status={status} />
            </div>
            <span
              aria-label={c.contract === pick ? 'Selected' : 'Select'}
              style={{
                display: 'inline-block',
                width: 14,
                height: 14,
                borderRadius: '50%',
                border: '2px solid var(--border-strong)',
                background: c.contract === pick ? 'var(--accent)' : 'transparent',
              }}
            />
          </TableRow>
        );
      })}
    </div>
  );
}
