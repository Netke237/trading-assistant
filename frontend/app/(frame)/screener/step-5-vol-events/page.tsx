'use client';

/*
 * Screener Step 5 — Volatility + Events gate. Phase 5 / Round 1.
 * Per-symbol table: IV rank, IV percentile, next event proximity.
 * CAUTION row when earnings ≤ 7d; REJECT when ≤ 3d.
 * Row-level star toggles watchlist membership (useWatchlistStore).
 */

import { Title, Text, Data } from '@/components/primitives';
import { TableRow } from '@/components/molecules/TableRow';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { EventFlag } from '@/components/atoms/EventFlag';
import { MOCK_WATCHLIST } from '@/mocks/watchlist';
import { eventProximity } from '@/lib/date';
import { WatchStar } from '@/components/atoms/WatchStar';
import type { Status } from '@/lib/status';
import styles from '../screener.module.css';

const COLUMNS = '32px 80px 1.4fr 90px 90px 110px 90px';

// Deterministic mock: spread IV rank by score rank.
function ivRankFor(symbol: string): number {
  let h = 0;
  for (let i = 0; i < symbol.length; i++) h = (h * 31 + symbol.charCodeAt(i)) >>> 0;
  return 20 + (h % 70);
}

function ivStatus(rank: number): Status {
  if (rank >= 60) return 'PASS';
  if (rank >= 35) return 'CAUTION';
  return 'REJECT';
}

export default function Step5Page() {
  return (
    <div className={styles.main}>
      <div className={styles.stepHeader}>
        <Text size={11} tone="dim" weight={500}>STEP 5 OF 7</Text>
        <Title as="h1" size={24}>Volatility + Events</Title>
        <Text size={13} tone="secondary">
          IV rank and near-term event proximity. Earnings within 7 days flags CAUTION; 3 days flags REJECT.
          Click the star to add a symbol to your watchlist.
        </Text>
      </div>

      <div className={styles.stepBody} style={{ padding: 0 }}>
        <div style={{ display: 'grid', gridTemplateColumns: COLUMNS, gap: 12, padding: '12px 16px', borderBottom: '1px solid var(--border-subtle)' }}>
          <span aria-hidden />
          <Text size={11} tone="dim">SYMBOL</Text>
          <Text size={11} tone="dim">NAME</Text>
          <Text size={11} tone="dim">IV RANK</Text>
          <Text size={11} tone="dim">IV STATUS</Text>
          <Text size={11} tone="dim">NEXT EVENT</Text>
          <Text size={11} tone="dim">GATE</Text>
        </div>
        {MOCK_WATCHLIST.map((r) => {
          const rank = ivRankFor(r.symbol);
          const ivSt = ivStatus(rank);
          const prox = r.nextEventDays !== undefined ? eventProximity(r.nextEventDays) : 'distant';
          const gate: Status = prox === 'imminent' ? 'REJECT'
            : prox === 'near'     ? 'CAUTION'
            : ivSt;

          return (
            <TableRow key={r.symbol} status={gate} columns={COLUMNS}>
              <WatchStar symbol={r.symbol} />
              <Data size={13} weight={500}>{r.symbol}</Data>
              <Text size={12} tone="secondary">{r.company}</Text>
              <Data size={13} weight={500}>{rank}</Data>
              <StatusBadge status={ivSt} />
              {r.nextEventDays !== undefined
                ? <EventFlag days={r.nextEventDays} title={r.nextEventLabel} />
                : <Text size={11} tone="dim">—</Text>}
              <StatusBadge status={gate} />
            </TableRow>
          );
        })}
      </div>
    </div>
  );
}
