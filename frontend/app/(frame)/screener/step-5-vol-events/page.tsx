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

/** Why a row is not PASS. 'noIv' is deliberately NOT folded into 'iv': an absent
 *  volatility reading and a volatility reading that failed its threshold wear the
 *  same CAUTION badge but mean opposite things, and only one of them is a fact
 *  about the trade. */
type GateDriver = 'pass' | 'iv' | 'noIv' | 'event' | 'both';

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

  const thresholdSentences = basesPresent
    .map((b) => {
      const passMax = getIvPassMax(horizonKey, ivThresholds, b);
      if (passMax === null) return null;
      const cautionMax = getIvCautionMax(horizonKey, ivThresholds, b);
      const noun = b === 'rank' ? 'IV rank' : 'IV';
      return `${noun} ≤ ${passMax} → PASS; ≤ ${cautionMax ?? '—'} → CAUTION; above → REJECT.`;
    })
    .filter((x): x is string => x !== null)
    .join(' ');

  // Whether this horizon gates on IV at all is a property of the HORIZON, so it
  // has to be asked of the thresholds directly. Deriving it from an empty
  // `basesPresent` — as this line did when the sentence became row-derived in the
  // Phase A split — made the page announce "IV gate disabled for this horizon"
  // on Swing and Position whenever no candidate carried a reading, the empty
  // page included. The gate is not disabled there; it has nothing in front of
  // it yet, which is a different statement and the one the user needs.
  const gateDisabled =
    getIvPassMax(horizonKey, ivThresholds, 'absolute') === null &&
    getIvPassMax(horizonKey, ivThresholds, 'rank') === null;

  const gateSentence =
    gateDisabled                ? 'IV gate disabled for this horizon.'
    : candidates.length === 0   ? 'Run a scan to see the volatility and event gates.'
    : thresholdSentences !== '' ? thresholdSentences
    // Candidates are on screen but not one of them carries a volatility
    // reading. Stated as the plain fact only: what an absent reading then does
    // to the gate is decided per row below, and differs by horizon.
    :                             'No volatility reading for these candidates.';


  // Per-row gate, computed ONCE. It used to live inline in the render map, which
  // meant the header could not say anything about the verdicts underneath it --
  // the page stated the thresholds and then left the user to read a column of
  // badges and infer why. Kenneth asked the obvious question of a CAUTION badge
  // ("why? because of percentile?") and the page had no answer above the fold.
  // The per-row tooltip (eventVolGateTooltip) already explains ONE row on hover;
  // this memo is what lets the banner explain ALL of them at once, and both now
  // read the same `driver` vocabulary so they cannot disagree.
  const gatedRows = useMemo(() => watchlist.map((r) => {
    const c = candidateMap[r.symbol];
    // A percentile if one exists, otherwise the absolute IV — resolved
    // through lib/ivBasis.ts so this page and the backend agree on which
    // quantity is in hand (PHASE-A-NULL-IVRANK-2026-09-06). Note a rank
    // of 0 is a REAL reading (bottom of the 52-week range, i.e. very
    // cheap premium); only the absolute level treats 0 as missing.
    const iv = resolveIv(c?.contractDetails);
    const hasIv = iv.basis !== 'none';
    // Unknown IV must not be treated as better than a clean read — this page's
    // own copy states "Gate = worst of IV and event proximity," so an unknown
    // IV is downgraded to CAUTION (not NO_DATA) specifically so it always
    // participates correctly in worstStatus's PASS/CAUTION/REJECT comparison
    // instead of falling through to NO_DATA, which worstStatus ranks below PASS.
    // ROUND 6 finding 3. When there IS a reading, ivStatusFor already returns
    // PASS on a horizon with no IV gate. With no reading this short-circuited
    // straight to CAUTION and never asked the question, so on Intraday — where
    // the gate is disabled by design — this page cautioned about a check that
    // was never going to run while the Step 7 rail, fixed for exactly this in
    // round 4, said PASS. Two screens, one candidate, contradicting verdicts.
    // `gateDisabled` above is the page-level answer and is stricter than the
    // rail's (it requires BOTH bases to be ungated rather than substituting
    // one), so it is the right thing to consult here.
    const ivSt: Status = hasIv
      ? ivStatusFor(iv.value as number, iv.basis)
      : gateDisabled ? 'PASS' : 'CAUTION';
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
    // WHY this row is not PASS, in the banner's vocabulary. `hasIv === false` is
    // called out separately from a genuine IV verdict because they are different
    // facts with the same badge: one is "the market says this is expensive", the
    // other is "nobody answered". Conflating them is what makes a CAUTION column
    // unreadable -- and on this app the second is the common case, because a true
    // percentile only exists when IBKR or tastytrade answered
    // (PHASE-A-NULL-IVRANK-2026-09-06).
    const driver: GateDriver =
      gate === 'PASS'                        ? 'pass'
      : ivSt === gate && proxStatus === gate ? 'both'
      : ivSt === gate                        ? (hasIv ? 'iv' : 'noIv')
      :                                        'event';
    return { r, c, iv, hasIv, ivSt, proxStatus, gate, driver };
  }), [watchlist, candidateMap, horizonKey, ivThresholds, evReject, evCaution, gateDisabled]);


  // The banner's second sentence: what the badges below actually say, and why.
  // Counting rather than prose because the honest answer is usually a mix, and
  // because "3 of 12 have no volatility reading" is the sentence that stops a
  // user reading a data gap as a verdict on the trade.
  const gateSummary = useMemo(() => {
    if (gatedRows.length === 0) return '';
    const n = (d: GateDriver) => gatedRows.filter((g) => g.driver === d).length;
    const pass = gatedRows.filter((g) => g.gate === 'PASS').length;
    const caution = gatedRows.filter((g) => g.gate === 'CAUTION').length;
    const reject = gatedRows.filter((g) => g.gate === 'REJECT').length;
    const head = `${gatedRows.length} shown — ${pass} PASS, ${caution} CAUTION, ${reject} REJECT.`;
    if (pass === gatedRows.length) return head;
    // Ordered most- to least-common cause so the dominant reason reads first.
    const causes: string[] = [];
    const noIv = n('noIv'), iv = n('iv'), ev = n('event'), both = n('both');
    if (noIv) causes.push(`${noIv} with no volatility reading (counted as CAUTION, never as PASS — a missing reading is not a passing one)`);
    if (iv)   causes.push(`${iv} on ${IV_COLUMN_LABEL.toLowerCase()} above its threshold`);
    if (ev)   causes.push(`${ev} on an event inside this horizon's window`);
    if (both) causes.push(`${both} on both`);
    return causes.length === 0 ? head : `${head} Driven by: ${causes.join('; ')}.`;
  }, [gatedRows]);

  return (
    <div className={styles.main}>
      <div className={styles.stepHeader}>
        <Text size={11} tone="dim" weight={500}>STEP 5 OF 7</Text>
        <Title as="h1" size={24}>Volatility + Events</Title>
        <Text size={13} tone="secondary">
          {gateSentence}
          {' '}Earnings within {evCaution} days → CAUTION; within {evReject} days → REJECT.
          Gate = worst of IV and event proximity.
        </Text>
        {gateSummary !== '' && (
          <Text size={12} tone="secondary">{gateSummary}</Text>
        )}
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

        {gatedRows.map(({ r, c, iv, hasIv, ivSt, proxStatus, gate }) => {
          const pctl = c?.contractDetails?.ivPercentile;
          const shownIv = formatIv(iv, r.symbol);
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

              {/* `!= null` only. A percentile of 0 is a REAL reading — the bottom of
                  this name's own 52-week range, i.e. the cheapest premium it gets —
                  and only an ABSOLUTE IV treats 0 as a missing-data sentinel
                  (PHASE-A-NULL-IVRANK-2026-09-06; the asymmetry is stated in
                  lib/ivBasis.ts and pinned in its tests). The old `&& pctl > 0`
                  guard dated from when a pre-split ivPercentile DEFAULTED to the
                  literal 0 that meant "no rank source answered"; market.py now
                  writes null for that, so the guard had nothing left to catch and
                  only destroyed information. step-6-contracts already gets this
                  right, so the two pages disagreed about one field. */}
              <Data size={13} weight={500}>{pctl != null ? pctl : '—'}</Data>

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
