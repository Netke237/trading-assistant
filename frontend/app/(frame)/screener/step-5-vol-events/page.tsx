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
import { resolveIv, formatIv, IV_COLUMN_LABEL, type IvBasis } from '@/lib/ivBasis';
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

  // The volatility figure behind each row is EITHER a true percentile
  // (`ivRank`, present only when IBKR or tastytrade answered) OR an absolute
  // implied volatility (`iv`), and each is judged by its own threshold set
  // (PHASE-A-NULL-IVRANK-2026-09-06). Thresholds are therefore resolved
  // per row, by basis — not once for the page.
  function ivStatusFor(value: number, basis: IvBasis): Status {
    const passMax = getIvPassMax(horizonKey, ivThresholds, basis);
    if (passMax === null) return 'PASS';   // Intraday: no IV gate
    if (value <= passMax) return 'PASS';
    const cautionMax = getIvCautionMax(horizonKey, ivThresholds, basis);
    if (cautionMax !== null && value <= cautionMax) return 'CAUTION';
    return 'REJECT';
  }

  // The header sentence can only quote the thresholds that actually apply to
  // the rows on screen, so derive the bases present rather than assuming one.
  const basesPresent = useMemo(() => {
    const seen = new Set<IvBasis>();
    for (const r of watchlist) {
      const b = resolveIv(candidateMap[r.symbol]?.contractDetails).basis;
      if (b !== 'none') seen.add(b);
    }
    return [...seen];
  }, [watchlist, candidateMap]);

  const gateSentence = basesPresent
    .map((b) => {
      const passMax = getIvPassMax(horizonKey, ivThresholds, b);
      if (passMax === null) return null;
      const cautionMax = getIvCautionMax(horizonKey, ivThresholds, b);
      const noun = b === 'rank' ? 'IV rank' : 'IV';
      return `${noun} ≤ ${passMax} → PASS; ≤ ${cautionMax ?? '—'} → CAUTION; above → REJECT.`;
    })
    .filter((x): x is string => x !== null)
    .join(' ');

  return (
    <div className={styles.main}>
      <div className={styles.stepHeader}>
        <Text size={11} tone="dim" weight={500}>STEP 5 OF 7</Text>
        <Title as="h1" size={24}>Volatility + Events</Title>
        <Text size={13} tone="secondary">
          {gateSentence !== '' ? gateSentence : 'IV gate disabled for this horizon.'}
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
          <Text size={11} tone="dim">{IV_COLUMN_LABEL}</Text>
          <Text size={11} tone="dim">IV PCTL</Text>
          <Text size={11} tone="dim">NEXT EVENT</Text>
          <Text size={11} tone="dim">GATE</Text>
        </div>

        {watchlist.map((r) => {
          const c = candidateMap[r.symbol];
          const pctl = c?.contractDetails?.ivPercentile;
          // A percentile if one exists, otherwise the absolute IV — resolved
          // through lib/ivBasis.ts so this page and the backend agree on which
          // quantity is in hand (PHASE-A-NULL-IVRANK-2026-09-06). Note a rank
          // of 0 is a REAL reading (bottom of the 52-week range, i.e. very
          // cheap premium); only the absolute level treats 0 as missing.
          const iv = resolveIv(c?.contractDetails);
          const hasIv = iv.basis !== 'none';
          const shownIv = formatIv(iv, r.symbol);
          // Unknown IV must not be treated as better than a clean read — this page's
          // own copy states "Gate = worst of IV and event proximity," so an unknown
          // IV is downgraded to CAUTION (not NO_DATA) specifically so it always
          // participates correctly in worstStatus's PASS/CAUTION/REJECT comparison
          // instead of falling through to NO_DATA, which worstStatus ranks below PASS.
          const ivSt: Status = hasIv ? ivStatusFor(iv.value as number, iv.basis) : 'CAUTION';
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
              <div className={pageStyles.ivRankCell} title={shownIv.title}>
                <Data size={13} weight={500}>{shownIv.text}</Data>
                {shownIv.suffix !== '' && (
                  <Text size={10} tone="dim">{shownIv.suffix}</Text>
                )}
                {hasIv && (
                  <div className={pageStyles.ivTrack}>
                    <div
                      className={`${pageStyles.ivFill} ${pageStyles[`ivFill_${ivSt}`]}`}
                      style={{ width: `${Math.min(1, (iv.value as number) / 100) * 120}px` }}
                    />
                  </div>
                )}
              </div>

              <Data size={13} weight={500}>{pctl != null && pctl > 0 ? pctl : '—'}</Data>

              {r.nextEventDays != null
                ? <EventFlag days={r.nextEventDays} title={r.nextEventLabel ?? undefined} />
                : <Text size={11} tone="dim">—</Text>}

              <StatusBadge
                status={gate}
                tooltip={eventVolGateTooltip({
                  ivRank: iv.value,
                  ivBasis: iv.basis,
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
