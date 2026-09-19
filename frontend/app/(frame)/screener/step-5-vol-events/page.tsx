'use client';

/*
 * Screener Step 5 — Volatility + Events gate.
 * Per-symbol table: IV rank (with mini bar), IV percentile, next event proximity.
 * Event proximity thresholds are horizon-specific, fetched from the backend
 * (/api/config/event-thresholds) via useEventThresholdsStore — see that store's
 * header comment for why this can't be a locally hardcoded constant.
 * Gate = worst of (IV status, event proximity status).
 */

import { useCallback, useMemo } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { TableRow } from '@/components/molecules/TableRow';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { EventFlag } from '@/components/atoms/EventFlag';
import { WatchStar } from '@/components/atoms/WatchStar';
import { OpenChartButton } from '@/components/atoms/OpenChartButton';
import { useScanStore } from '@/lib/scanStore';
import { useIvThresholdsStore, getIvPassMax, getIvCautionMax } from '@/lib/ivThresholdsStore';
import { resolveIv, formatIv, ivColumnLabel, type IvBasis } from '@/lib/ivBasis';
import { useEventThresholdsStore, getEventWindow } from '@/lib/eventThresholdsStore';
import type { WatchlistRow, TradeCardData } from '@/types/domain';

/* ── THE MISSING-READING CLAIM ──────────────────────────────────
 * THE MEANING IS RENDERED AS DATA. The four fields below go into the DOM as
 * `data-claim-*` attributes on the element that carries the sentence, and the
 * sentence is that same claim run through `missingReadingClause`. The tests
 * read the attributes; the English is a rendering of them, not the carrier.
 *
 * WHY, AND THE EVIDENCE IS TEN ROUNDS DEEP. Four consecutive adversarial
 * rounds tried to prove the PROSE correct and each closed one hole while
 * opening another: regex whitelists, then "positive" regex rules, then a
 * data-driven clause compared with `toContain`, then that plus a three-token
 * "no verdict word outside the clause" rule. Round 4 measured that last rule
 * ADMITTING false copy ("safe to trade as if they were clean", green) and
 * REJECTING true copy (11 red on a statement true of the page) at the same
 * time. Each of these shipped a full green suite:
 *   "graded PASS ... never CAUTION"      the semantic INVERSE of the gate
 *   "on the event side"                  the wrong side entirely
 *   "so it can be easier still"          a worst-of that gets easier
 *   "In the worst case, open the column" the reconciliation sentence deleted,
 *                                        with one list word left behind
 * The rules were not the defect; grading English with regexes was.
 *
 * WHAT REPLACES THEM. Every field below is answerable to something the page
 * RENDERS, not to a constant a human retyped in the test file:
 *   side        → each row publishes `data-side-volatility` and
 *                 `data-side-event`; exactly one of them equals `asserted` on
 *                 the row the clause describes, and it must be the one named.
 *   asserted    → that same attribute, plus the head's count for the verdict.
 *   denied      → the OTHER branch of the same ternary, observed by rendering
 *                 the same row on a horizon where volatility does not gate.
 *   combination → a row whose two sides genuinely disagree: `worse` and
 *                 `better` predict different gates, and only one is rendered.
 * A reworded clause can therefore say the same thing differently, but it
 * cannot say something different -- to do that you must change the claim, and
 * every field of the claim is pinned to behaviour. The skeleton itself is
 * pinned by one exact-string test, which is the only place a literal belongs.
 */
export type MissingReadingClaim = {
  /** Which side of the gate graded the row. */
  side: 'volatility' | 'event';
  /** The sub-verdict that side gives an unreadable row. */
  asserted: Status;
  /** The sub-verdict it explicitly does NOT give. */
  denied: Status;
  /** How the two sides combine. `worstStatus` is 'worse'. */
  combination: 'worse' | 'better';
};

const SIDE_LABEL = {
  volatility: 'the volatility side',
  event:      'the event side',
} as const;

const COMBINATION_LABEL = {
  worse:  { of: 'worse',  travel: 'lower'  },
  better: { of: 'better', travel: 'higher' },
} as const;

/** The banner's second line, before it is words. `causes` and `missing` are
 *  independently optional: a scan can be entirely readable (causes, no claim),
 *  entirely unreadable with nothing else driving it (claim, no causes), or
 *  both. Each becomes its own `data-part` element. */
type GateSummary = {
  head: string;
  causes: string | null;
  missing: { rows: number; claim: MissingReadingClaim } | null;
};

export function missingReadingClause(n: number, claim: MissingReadingClaim): string {
  const { of, travel } = COMBINATION_LABEL[claim.combination];
  return (
    `${n} of them ${n === 1 ? 'has' : 'have'} no volatility reading at all — ` +
    `graded ${claim.asserted} on ${SIDE_LABEL[claim.side]} alone, never ${claim.denied} there. ` +
    `The gate verdict above is the ${of} of that and the event window, ` +
    `so it can be ${travel} still.`
  );
}
import { worstStatus, type Status } from '@/lib/status';
import { eventVolGateTooltip, gateDrivers, type GateDrivers } from '@/lib/statusTooltips';
import styles from '../screener.module.css';
import pageStyles from './page.module.css';

// NAME is `minmax(0, 1fr)`, never a bare `1fr`. Step 4 had this exact defect,
// and this file was edited by the very commit that fixed it there and left it
// here. `1fr` is `minmax(auto, 1fr)`: with no free space the track falls back to
// MIN-CONTENT, and the header's min-content is the word "NAME" while each row's
// is the longest word of a company name -- and this page's NAME cell had no
// clipping wrapper at all, so its min-content was LARGER than step 4's ever was.
// Measured at the app's own MinWidthGate floor, which is 1280px (MIN_WIDTH in
// components/MinWidthGate/index.tsx -- NOT the 1200 this comment first said, and
// not the 1200 CLAUDE.md said until it was corrected alongside this): header 94px vs row
// track 114.8px on "T-Mobile US Telecommunications", putting IV, IV PCTL, NEXT
// EVENT and GATE 21px off their own data; 173px off on a long single-word name.
const COLUMNS = '24px 32px 72px minmax(0, 1fr) 120px 70px 110px 80px';

/** Module-level so the "no scan yet" case is a STABLE reference. `?? []` built a
 *  fresh array every render, so before a scan landed every memo below it
 *  (watchlist, candidateMap, gatedRows, gateSummary) recomputed on every single
 *  render and the "computed ONCE" claim held only after a scan. */
const NO_CANDIDATES: TradeCardData[] = [];

/* Why a row is not PASS is decided by `gateDrivers` (lib/statusTooltips.ts),
 * which the per-row tooltip calls too. It was a local enum here and a separate
 * expression there, and an adversarial round caught the two disagreeing on
 * screen about the same row. */

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
  const candidates           = scanResultCandidates ?? NO_CANDIDATES;
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
  // useCallback so the gate memo can DECLARE this rather than close over it.
  // The memo's deps were hand-maintained to match this function's real inputs
  // and held only by coincidence -- `next lint` flagged the missing dependency,
  // and any future edit reading a fourth value here would have produced a stale
  // gate with no warning at the call site.
  const ivStatusFor = useCallback((value: number, basis: IvBasis): Status => {
    const passMax = getIvPassMax(horizonKey, ivThresholds, basis);
    if (passMax === null) return 'PASS';   // Intraday: no IV gate
    if (value <= passMax) return 'PASS';
    const cautionMax = getIvCautionMax(horizonKey, ivThresholds, basis);
    if (cautionMax !== null && value <= cautionMax) return 'CAUTION';
    return 'REJECT';
  }, [horizonKey, ivThresholds]);

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

  // Per-row gate, computed ONCE. It used to live inline in the render map, which
  // meant the header could not say anything about the verdicts underneath it --
  // the page stated the thresholds and then left the user to read a column of
  // badges and infer why. Kenneth asked the obvious question of a CAUTION badge
  // ("why? because of percentile?") and the page had no answer above the fold.
  // The per-row tooltip (eventVolGateTooltip) already explains ONE row on hover;
  // this memo is what lets the banner explain ALL of them at once. Both call the
  // SAME classifier (gateDrivers) -- a shared call site, not a comment promising
  // they agree, which is what the previous version of this line was and was
  // wrong.
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
    // FLAGS, not an exclusive enum. The enum tested "both drive" BEFORE splitting
    // a missing reading from a failed one, so a row that was CAUTION on a missing
    // IV *and* on event proximity collapsed to 'both' -- printing "2 on both"
    // with no antecedent anywhere in the sentence, and suppressing the single
    // distinction this feature exists to make. Flags let one row be counted under
    // every cause that genuinely applies to it.
    // `ivGated` is the HORIZON's fact and `hasIv` is the ROW's, and round 3
    // proved they are not interchangeable: the tooltip chose its PASS sentence
    // on the row's and so told an Intraday row at IV rank 95 it was "clear on
    // both", under a banner saying the IV gate is disabled here. Both now
    // travel WITH the verdict instead of being re-derived at the far end.
    const drivers: GateDrivers = gateDrivers({
      ivStatus: ivSt, proxStatus, gate, hasIv, ivGated: !gateDisabled,
    });
    return { r, c, iv, hasIv, ivSt, proxStatus, gate, drivers };
  }), [watchlist, candidateMap, ivStatusFor, evReject, evCaution, gateDisabled]);


  // DERIVED FROM gatedRows rather than looping the watchlist and calling
  // resolveIv all over again. Two memos computing the same quantity is exactly
  // what this file's module header warns about: "two editors each computing the
  // same quantity their own way is how this codebase has repeatedly regressed."
  const basesPresent = useMemo(() => {
    const seen = new Set<IvBasis>();
    for (const g of gatedRows) if (g.iv.basis !== 'none') seen.add(g.iv.basis);
    return [...seen];
  }, [gatedRows]);

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

  const gateSentence =
    gateDisabled                ? 'IV gate disabled for this horizon.'
    : candidates.length === 0   ? 'Run a scan to see the volatility and event gates.'
    : thresholdSentences !== '' ? thresholdSentences
    // Candidates are on screen but not one of them carries a volatility
    // reading. Stated as the plain fact only: what an absent reading then does
    // to the gate is decided per row below, and differs by horizon.
    :                             'No volatility reading for these candidates.';


  // The banner's second line: what the badges below actually say, and why.
  // Counting rather than prose because the honest answer is usually a mix, and
  // because "3 of 12 have no volatility reading" is the sentence that stops a
  // user reading a data gap as a verdict on the trade.
  //
  // A STRUCTURE, NOT A JOINED STRING. Each sentence is rendered as its own
  // `data-part` element and the missing-reading one carries its claim as
  // `data-claim-*` attributes, so a test can assert what the banner CLAIMS
  // without parsing what it SAYS -- and so an extra sentence cannot be
  // appended without adding a part the composition check enumerates. Round 3
  // measured the alternative: appending "In practice these rows are safe to
  // treat as a PASS." to a `parts.push` list shipped 43/43 green.
  const gateSummary = useMemo<GateSummary | null>(() => {
    const total = gatedRows.length;
    if (total === 0) return null;
    const pass = gatedRows.filter((g) => g.gate === 'PASS').length;
    const caution = gatedRows.filter((g) => g.gate === 'CAUTION').length;
    const reject = gatedRows.filter((g) => g.gate === 'REJECT').length;
    const head = `${total} shown — ${pass} PASS, ${caution} CAUTION, ${reject} REJECT.`;

    // TWO DIFFERENT QUESTIONS, and an adversarial round showed why they must not
    // share one list. "What decided the verdict" is the driver; "what could not
    // be read" is data quality. While they were one list, a scan where every row
    // was REJECTED by an event said NOTHING about the rows that also had no
    // volatility reading -- because `drivers.iv` is only true when the IV side is
    // AT the gate, and a missing reading is CAUTION, which is not REJECT. The
    // banner's whole reason for existing vanished in the case it was built for.
    const count = (f: (g: (typeof gatedRows)[number]) => boolean) => gatedRows.filter(f).length;
    const causes = [
      { n: count((g) => g.drivers.iv && !g.drivers.ivMissing && g.iv.basis === 'rank'),
        text: 'on IV rank above its threshold' },
      { n: count((g) => g.drivers.iv && !g.drivers.ivMissing && g.iv.basis === 'absolute'),
        text: 'on IV above its threshold' },
      { n: count((g) => g.drivers.event),
        text: "on an event inside this horizon's window" },
    ].filter((c) => c.n > 0).sort((a, b) => b.n - a.n);

    // Counted whether or not it drove the verdict, and deliberately NOT part of
    // the sorted list -- it trails as its own sentence so the sort can never
    // demote the one fact this banner exists to surface. Excluded where the
    // horizon does not gate on volatility at all, because there a missing
    // reading costs the candidate nothing.
    const noReading = gateDisabled ? 0 : count((g) => !g.hasIv);

    let causesSentence: string | null = null;
    if (causes.length > 0) {
      // A row can be driven by its volatility AND an event, so these need not
      // sum to the non-PASS count. Said out loud, because on screen there was no
      // cue at all and "17 causes for 12 rows" reads as a bug.
      const sum = causes.reduce((a, c) => a + c.n, 0);
      // AGAINST THE ROWS THESE CLAUSES ACTUALLY DESCRIBE, not against every
      // non-PASS row. Round 3: the missing-reading count moved out of `causes`
      // into its own trailing sentence one round earlier, but this comparison
      // kept the old denominator -- and a row whose ONLY driver is a missing
      // reading adds 0 to `sum` while still adding 1 to `caution + reject`. So
      // each such row cancelled out a genuine double-count and DELETED the
      // disclaimer. Measured: 10 rows driven by both IV rank and an event plus
      // 11 unreadable rows printed "10 ...; 10 ..." with no cue -- 31
      // attributions over 21 rows -- while the same 10 overlapping rows with 9
      // unreadable ones printed the cue. The overlap was byte-identical; two
      // unrelated rows removed the warning. On this app that is the COMMON
      // case, because a true percentile needs IBKR or tastytrade to answer.
      const driven = count((g) => (g.drivers.iv && !g.drivers.ivMissing) || g.drivers.event);
      const overlap = sum > driven ? ' (a row can have more than one)' : '';
      causesSentence = `Driven by${overlap}: ${causes.map((c) => `${c.n} ${c.text}`).join('; ')}.`;
    }
    // The claim the head sentence sits above. Every meaning-bearing word of the
    // rendered clause is carried by this object, and the object itself reaches
    // the DOM; see THE MISSING-READING CLAIM above for why.
    //   side:     the unreadable row's verdict is set on the IV branch below
    //             (`hasIv ? ... : gateDisabled ? 'PASS' : 'CAUTION'`), and the
    //             event branch never sees `hasIv` at all.
    //   asserted/denied: those are the two arms of that one ternary. This
    //             clause renders only where the horizon DOES gate on volatility
    //             (noReading is forced to 0 otherwise), so the live arm is
    //             CAUTION and PASS is the arm this row cannot reach.
    //   combination: the gate is worstStatus(iv, event) -- worse, never better.
    const missing = noReading === 0 ? null : {
      rows: noReading,
      claim: {
        side:        'volatility',
        asserted:    'CAUTION',
        denied:      'PASS',
        combination: 'worse',
      } as MissingReadingClaim,
    };

    return { head, causes: causesSentence, missing };
  }, [gatedRows, gateDisabled]);

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
        {/* ONE ELEMENT PER SENTENCE, and the separators are the only text this
            container holds directly -- so the test can enumerate `[data-part]`
            and assert the container says exactly the sum of its parts. The
            joined-string version could not: `parts.push('...safe to treat as a
            PASS.')` shipped 43/43 green. The single spaces below keep the
            rendered line byte-identical to that version. */}
        {gateSummary !== null && (
          <div data-testid="gate-summary">
            <span data-part="head">
              <Text size={12} tone="secondary">{gateSummary.head}</Text>
            </span>
            {gateSummary.causes !== null && (
              <>
                {' '}
                <span data-part="causes">
                  <Text size={12} tone="secondary">{gateSummary.causes}</Text>
                </span>
              </>
            )}
            {gateSummary.missing !== null && (
              <>
                {' '}
                {/* THE CLAIM ITSELF, in the DOM. The sentence beside it is this
                    same claim rendered; the tests read these attributes and
                    check each one against what the page does, not against a
                    constant retyped in the test file. */}
                <span
                  data-part="missing-reading"
                  data-claim-rows={gateSummary.missing.rows}
                  data-claim-side={gateSummary.missing.claim.side}
                  data-claim-asserted={gateSummary.missing.claim.asserted}
                  data-claim-denied={gateSummary.missing.claim.denied}
                  data-claim-combination={gateSummary.missing.claim.combination}
                >
                  <Text size={12} tone="secondary">
                    {missingReadingClause(gateSummary.missing.rows, gateSummary.missing.claim)}
                  </Text>
                </span>
              </>
            )}
          </div>
        )}
      </div>

      <div className={`${styles.stepBody} ${styles.stepBody_noPad}`}>
        <div className={pageStyles.tableHeader} style={{ gridTemplateColumns: COLUMNS }}>
          <span aria-hidden />
          <span aria-hidden />
          <Text size={11} tone="dim">SYMBOL</Text>
          <Text size={11} tone="dim">NAME</Text>
          <Text size={11} tone="dim">{ivColumnLabel(basesPresent)}</Text>
          <Text size={11} tone="dim">IV PCTL</Text>
          <Text size={11} tone="dim">NEXT EVENT</Text>
          <Text size={11} tone="dim">GATE</Text>
        </div>

        {gatedRows.map(({ r, c, iv, hasIv, ivSt, proxStatus, gate, drivers }) => {
          const pctl = c?.contractDetails?.ivPercentile;
          const shownIv = formatIv(iv, r.symbol);
          return (
            <TableRow key={r.symbol} status={gate} columns={COLUMNS}>
              <OpenChartButton symbol={r.symbol} />
              <WatchStar symbol={r.symbol} size="sm" />
              <Data size={13} weight={500}>{r.symbol}</Data>
              <div className={pageStyles.nameCell}>
                <Text size={12} tone="secondary">{r.company}</Text>
              </div>

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

              {/* THE TWO SIDES OF THE GATE, PUBLISHED SEPARATELY AND KEYED BY
                  THE CLAIM'S OWN SIDE NAMES. `data-side-${side}` is how a test
                  turns the claim's `side` field into an observation: exactly
                  one side may carry the asserted verdict, and it must be the
                  one the claim names. Before this, `side` and `combination`
                  were circular -- swapping either in page.tsx AND in the test's
                  copy of the claim shipped 45/45 green, rendering "graded PASS
                  on the volatility side alone, never CAUTION there", verbatim
                  the first entry in this file's own list of past failures.
                  `display: contents` so the badge stays the grid item. */}
              <span
                className={pageStyles.gateCell}
                data-row={r.symbol}
                data-side-volatility={ivSt}
                data-side-event={proxStatus}
                data-gate={gate}
              >
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
                  // The SAME object the banner counted. Passing raw fields and
                  // letting the tooltip re-derive them is how the two came to
                  // disagree about one row in the first place.
                  drivers,
                })}
              />
              </span>
            </TableRow>
          );
        })}
      </div>
    </div>
  );
}
