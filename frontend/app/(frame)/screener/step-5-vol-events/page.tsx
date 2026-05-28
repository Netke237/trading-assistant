'use client';

/*
 * Screener Step 5 — Volatility + Events gate.
 * Per-symbol table: IV rank (with mini bar), IV percentile, next event proximity.
 * CAUTION when earnings ≤ 7d; REJECT when ≤ 3d.
 * Gate = worst of (IV status, event proximity status).
 */

import { useMemo } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { TableRow } from '@/components/molecules/TableRow';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { EventFlag } from '@/components/atoms/EventFlag';
import { WatchStar } from '@/components/atoms/WatchStar';
import { useScanStore } from '@/lib/scanStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { IV_PASS_MAX, IV_CAUTION_MAX } from '@/lib/ivThresholds';
import type { WatchlistRow, TradeCardData } from '@/types/domain';
import { eventProximity } from '@/lib/date';
import { worstStatus, type Status } from '@/lib/status';
import styles from '../screener.module.css';
import pageStyles from './page.module.css';

const COLUMNS = '32px 72px 1fr 120px 70px 110px 80px';

function cardToRow(c: TradeCardData): WatchlistRow {
  return {
    symbol: c.symbol,
    company: c.company,
    price: c.price,
    direction: c.direction,
    horizon: 'Swing',
    score: c.stockScore,
    rankDelta: 0,
    scoreDelta: 0,
    status: c.status,
    breakdown: c.stockBreakdown,
    nextEventDays: c.nextEventDays,
    nextEventLabel: c.nextEventLabel,
  };
}

const EVENT_WINDOWS: Record<string, { caution: number; reject: number }> = {
  Intraday: { caution: 3,  reject: 1  },
  Swing:    { caution: 21, reject: 7  },
  Position: { caution: 60, reject: 30 },
};

export default function Step5Page() {
  const scanResultCandidates = useScanStore((s) => s.scanResult?.candidates);
  const context              = useScanStore((s) => s.context);
  const candidates           = scanResultCandidates ?? [];
  const ivPassFallback    = useSettingsStore((s) => s.ivPassThreshold);
  const ivCautionFallback = useSettingsStore((s) => s.ivCautionThreshold);
  const watchlist = useMemo(() => candidates.map(cardToRow), [candidates]);
  const candidateMap = useMemo(
    () => Object.fromEntries(candidates.map((c) => [c.symbol, c])),
    [candidates],
  );

  const horizonKey = context?.horizon?.startsWith('Intraday') ? 'Intraday'
    : context?.horizon?.startsWith('Position') ? 'Position'
    : 'Swing';
  const { caution: evCaution, reject: evReject } = EVENT_WINDOWS[horizonKey];

  // Use per-horizon YAML defaults; fall back to settingsStore when no scan context yet.
  const ivPassThreshold    = IV_PASS_MAX[horizonKey]    ?? ivPassFallback;
  const ivCautionThreshold = IV_CAUTION_MAX[horizonKey] ?? ivCautionFallback;

  function ivStatus(rank: number): Status {
    if (rank <= ivPassThreshold)    return 'PASS';
    if (rank <= ivCautionThreshold) return 'CAUTION';
    return 'REJECT';
  }

  return (
    <div className={styles.main}>
      <div className={styles.stepHeader}>
        <Text size={11} tone="dim" weight={500}>STEP 5 OF 7</Text>
        <Title as="h1" size={24}>Volatility + Events</Title>
        <Text size={13} tone="secondary">
          IV rank ≤ {ivPassThreshold} → PASS; ≤ {ivCautionThreshold} → CAUTION; above → REJECT.
          Earnings within {evCaution} days → CAUTION; within {evReject} days → REJECT.
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
          const c = candidateMap[r.symbol];
          const rank = c?.contractDetails?.ivRank;
          const pctl = c?.contractDetails?.ivPercentile;
          const hasIv = rank != null && rank > 0;
          const ivSt = hasIv ? ivStatus(rank) : 'NO_DATA';
          const prox = r.nextEventDays != null ? eventProximity(r.nextEventDays) : 'distant';
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
                <Data size={13} weight={500}>{hasIv ? rank : '—'}</Data>
                {hasIv && (
                  <div className={pageStyles.ivTrack}>
                    <div
                      className={`${pageStyles.ivFill} ${pageStyles[`ivFill_${ivSt}`]}`}
                      style={{ width: `${(rank / 100) * 120}px` }}
                    />
                  </div>
                )}
              </div>

              <Data size={13} weight={500}>{pctl !== undefined ? pctl : '—'}</Data>

              {r.nextEventDays != null
                ? <EventFlag days={r.nextEventDays} title={r.nextEventLabel ?? undefined} />
                : <Text size={11} tone="dim">—</Text>}

              <StatusBadge status={gate} />
            </TableRow>
          );
        })}
      </div>
    </div>
  );
}
