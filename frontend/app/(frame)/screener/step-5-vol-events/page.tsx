'use client';

/*
 * Screener Step 5 — Volatility + Events gate.
 * Per-symbol table: IV rank (with mini bar), IV percentile, next event proximity.
 * CAUTION when earnings ≤ 7d; REJECT when ≤ 3d.
 * Gate = worst of (IV status, event proximity status).
 */

import { useEffect, useState } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { TableRow } from '@/components/molecules/TableRow';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { EventFlag } from '@/components/atoms/EventFlag';
import { WatchStar } from '@/components/atoms/WatchStar';
import { api } from '@/lib/api';
import type { WatchlistRow } from '@/types/domain';
import { eventProximity } from '@/lib/date';
import { worstStatus, type Status } from '@/lib/status';
import styles from '../screener.module.css';
import pageStyles from './page.module.css';

const COLUMNS = '32px 72px 1fr 120px 70px 110px 80px';

/** Deterministic IV rank (0–100) from symbol hash. */
function ivRankFor(symbol: string): number {
  let h = 0;
  for (let i = 0; i < symbol.length; i++) h = (h * 31 + symbol.charCodeAt(i)) >>> 0;
  return 20 + (h % 70);
}

/** Deterministic IV percentile — correlated with rank, not identical. */
function ivPctlFor(symbol: string): number {
  let h = 0;
  for (let i = 0; i < symbol.length; i++) h = (h * 17 + symbol.charCodeAt(i)) >>> 0;
  return Math.max(5, Math.min(95, ivRankFor(symbol) + ((h % 21) - 10)));
}

function ivStatus(rank: number): Status {
  if (rank >= 60) return 'PASS';
  if (rank >= 35) return 'CAUTION';
  return 'REJECT';
}

export default function Step5Page() {
  const [watchlist, setWatchlist] = useState<WatchlistRow[]>([]);
  useEffect(() => { api.getWatchlist().then(setWatchlist).catch(() => {}); }, []);

  return (
    <div className={styles.main}>
      <div className={styles.stepHeader}>
        <Text size={11} tone="dim" weight={500}>STEP 5 OF 7</Text>
        <Title as="h1" size={24}>Volatility + Events</Title>
        <Text size={13} tone="secondary">
          IV rank sweet-spot: 35–100 preferred. Earnings within 7 days → CAUTION; within 3 days → REJECT.
          Gate = worst of IV and event proximity.
        </Text>
      </div>

      <div className={`${styles.stepBody} ${styles.stepBody_noPad}`}>
        <div className={pageStyles.tableHeader} style={{ gridTemplateColumns: COLUMNS }}>
          <span aria-hidden />
          <Text size={11} tone="dim">SYMBOL</Text>
          <Text size={11} tone="dim">NAME</Text>
          <Text size={11} tone="dim">IV RANK</Text>
          <Text size={11} tone="dim">IV PCTL</Text>
          <Text size={11} tone="dim">NEXT EVENT</Text>
          <Text size={11} tone="dim">GATE</Text>
        </div>

        {watchlist.map((r) => {
          const rank = ivRankFor(r.symbol);
          const pctl = ivPctlFor(r.symbol);
          const ivSt = ivStatus(rank);
          const prox = r.nextEventDays !== undefined ? eventProximity(r.nextEventDays) : 'distant';
          const proxStatus: Status =
            prox === 'imminent' ? 'REJECT'
            : prox === 'near'   ? 'CAUTION'
            : 'PASS';
          const gate: Status = worstStatus(ivSt, proxStatus);

          return (
            <TableRow key={r.symbol} status={gate} columns={COLUMNS}>
              <WatchStar symbol={r.symbol} size="sm" />
              <Data size={13} weight={500}>{r.symbol}</Data>
              <Text size={12} tone="secondary">{r.company}</Text>

              {/* IV rank + inline mini bar */}
              <div className={pageStyles.ivRankCell}>
                <Data size={13} weight={500}>{rank}</Data>
                <div className={pageStyles.ivTrack}>
                  <div
                    className={`${pageStyles.ivFill} ${pageStyles[`ivFill_${ivSt}`]}`}
                    style={{ width: `${(rank / 100) * 120}px` }}
                  />
                </div>
              </div>

              <Data size={13} weight={500}>{pctl}</Data>

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
