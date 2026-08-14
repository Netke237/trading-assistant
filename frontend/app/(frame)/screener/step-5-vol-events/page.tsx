'use client';

/*
 * Screener Step 5 — Volatility + Events gate.
 * Per-symbol table: IV rank (with mini bar), IV percentile, next event proximity.
 * Event proximity thresholds are horizon-specific, fetched from the backend
 * (/api/config/event-thresholds) via useEventThresholdsStore — see that store's
 * header comment for why this can't be a locally hardcoded constant.
 * Gate = worst of (IV status, event proximity status).
 */

import { useMemo } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { TableRow } from '@/components/molecules/TableRow';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { EventFlag } from '@/components/atoms/EventFlag';
import { WatchStar } from '@/components/atoms/WatchStar';
import { OpenChartButton } from '@/components/atoms/OpenChartButton';
import { useScanStore } from '@/lib/scanStore';
import { useIvThresholdsStore, getIvPassMax, getIvCautionMax } from '@/lib/ivThresholdsStore';
import { useEventThresholdsStore, getEventWindow } from '@/lib/eventThresholdsStore';
import type { WatchlistRow, TradeCardData } from '@/types/domain';
import { worstStatus, type Status } from '@/lib/status';
import { eventVolGateTooltip } from '@/lib/statusTooltips';
import styles from '../screener.module.css';
import pageStyles from './page.module.css';

const COLUMNS = '24px 32px 72px 1fr 120px 70px 110px 80px';

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

export default function Step5Page() {
  const scanResultCandidates = useScanStore((s) => s.scanResult?.candidates);
  const context              = useScanStore((s) => s.context);
  const candidates           = scanResultCandidates ?? [];
  const ivThresholds = useIvThresholdsStore((s) => s.thresholds);
  const eventThresholds = useEventThresholdsStore((s) => s.thresholds);
  const watchlist = useMemo(() => candidates.map(cardToRow), [candidates]);
  const candidateMap = useMemo(
    () => Object.fromEntries(candidates.map((c) => [c.symbol, c])),
    [candidates],
  );

  const horizonKey = context?.horizon?.startsWith('Intraday') ? 'Intraday'
    : context?.horizon?.startsWith('Position') ? 'Position'
    : 'Swing';
  // Fetched from the backend (/api/config/event-thresholds), which reads the same
  // scoring_rules.yaml block score_stock()'s _rule_event uses — so this gate always
  // matches the reject/caution window that already shaped the candidate's score.
  const { reject_days: evReject, caution_days: evCaution } = getEventWindow(horizonKey, eventThresholds);

  const ivPassThreshold    = getIvPassMax(horizonKey, ivThresholds);
  const ivCautionThreshold = getIvCautionMax(horizonKey, ivThresholds);

  function ivStatus(rank: number): Status {
    if (ivPassThreshold === null)    return 'PASS';   // Intraday: no IV gate
    if (rank <= ivPassThreshold)    return 'PASS';
    if (ivCautionThreshold !== null && rank <= ivCautionThreshold) return 'CAUTION';
    return 'REJECT';
  }

  return (
    <div className={styles.main}>
      <div className={styles.stepHeader}>
        <Text size={11} tone="dim" weight={500}>STEP 5 OF 7</Text>
        <Title as="h1" size={24}>Volatility + Events</Title>
        <Text size={13} tone="secondary">
          {ivPassThreshold !== null
            ? `IV rank ≤ ${ivPassThreshold} → PASS; ≤ ${ivCautionThreshold ?? '—'} → CAUTION; above → REJECT.`
            : 'IV gate disabled for this horizon.'}
          {' '}Earnings within {evCaution} days → CAUTION; within {evReject} days → REJECT.
          Gate = worst of IV and event proximity.
        </Text>
      </div>

      <div className={`${styles.stepBody} ${styles.stepBody_noPad}`}>
        <div className={pageStyles.tableHeader} style={{ gridTemplateColumns: COLUMNS }}>
          <span aria-hidden />
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
          // Unknown IV must not be treated as better than a clean read — this page's
          // own copy states "Gate = worst of IV and event proximity," so an unknown
          // IV rank is downgraded to CAUTION (not NO_DATA) specifically so it always
          // participates correctly in worstStatus's PASS/CAUTION/REJECT comparison
          // instead of falling through to NO_DATA, which worstStatus ranks below PASS.
          const ivSt: Status = hasIv ? ivStatus(rank) : 'CAUTION';
          // Gate must use THIS scan's horizon-specific window (evCaution/evReject,
          // already fetched above via useEventThresholdsStore) — not a fixed cutoff. The
          // generic eventProximity() helper (frontend/lib/date.ts) is intentionally
          // NOT used here: it backs the EventFlag badge's fixed 3d/7d "how soon"
          // color and has no notion of scan horizon, which previously caused this
          // gate to silently ignore the Position/Swing/Intraday window shown in
          // this page's own header sentence above.
          // Strict `<` (not `<=`) matches backend stock_scorer.py's _rule_event exactly
          // (`worst_days < ec["reject_days"]` / `< ec["caution_days"]`) — an event landing
          // exactly on the boundary day scores CAUTION/PASS server-side, not REJECT/CAUTION.
          const proxStatus: Status =
            r.nextEventDays == null       ? 'PASS'
            : r.nextEventDays < evReject  ? 'REJECT'
            : r.nextEventDays < evCaution ? 'CAUTION'
            : 'PASS';
          const gate: Status = worstStatus(ivSt, proxStatus);

          return (
            <TableRow key={r.symbol} status={gate} columns={COLUMNS}>
              <OpenChartButton symbol={r.symbol} />
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

              <Data size={13} weight={500}>{pctl !== undefined && pctl > 0 ? pctl : '—'}</Data>

              {r.nextEventDays != null
                ? <EventFlag days={r.nextEventDays} title={r.nextEventLabel ?? undefined} />
                : <Text size={11} tone="dim">—</Text>}

              <StatusBadge
                status={gate}
                tooltip={eventVolGateTooltip({
                  ivRank: hasIv ? rank : null,
                  ivStatus: ivSt,
                  nextEventDays: r.nextEventDays ?? null,
                  proxStatus,
                  evReject,
                  evCaution,
                  gate,
                })}
              />
            </TableRow>
          );
        })}
      </div>
    </div>
  );
}
