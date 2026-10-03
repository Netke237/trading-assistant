'use client';

/*
 * Screener Step 5 — Volatility + Events gate.
 * Per-symbol table: IV rank (with mini bar), IV percentile, next event proximity.
 * Event proximity thresholds are horizon-specific, fetched from the backend
 * (/api/config/event-thresholds) via useEventThresholdsStore — see that store's
 * header comment for why this can't be a locally hardcoded constant.
 * Gate = worst of (IV status, event proximity status).
 *
 * NO THRESHOLDS, NO VERDICT (decision DOCC-3-THRESHOLD-STORES-REFUSE-2026-09-29).
 * Both threshold stores hold only validated backend values and are fetched on
 * mount. Until both records are in hand (`avail === 'ready'`) the page grades
 * nothing: every gate is PENDING while loading and NO_DATA when a fetch failed,
 * no counts line, no bands, and no sentence that quotes a number. The IV side
 * reads the EFFECTIVE record (effectiveIvThresholds: fetched + Settings'
 * session override), and the header labels an active override.
 */

import { useCallback, useEffect, useMemo } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { TableRow } from '@/components/molecules/TableRow';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { EventFlag } from '@/components/atoms/EventFlag';
import { WatchStar } from '@/components/atoms/WatchStar';
import { OpenChartButton } from '@/components/atoms/OpenChartButton';
import { useScanStore } from '@/lib/scanStore';
import {
  useIvThresholdsStore, getIvPassMax, getIvCautionMax, effectiveIvThresholds, ivOverrideFor,
} from '@/lib/ivThresholdsStore';
import { resolveIv, formatIv, ivColumnLabel, type IvBasis } from '@/lib/ivBasis';
import {
  useEventThresholdsStore, getEventWindow, type ThresholdHorizon,
} from '@/lib/eventThresholdsStore';
import type { WatchlistRow, TradeCardData } from '@/types/domain';
import {
  MISSING_READING_CLAIM, ivThresholdSentence, eventWindowSentence,
  headSentence, causesSentence, missingReadingClause,
  thresholdsUnavailableSentence, ivOverrideSentence, type ThresholdsAvail,
  type GateCounts, type GateCause, type IvBand, type GateSummary,
} from './gateSummary';
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
//
// The NAME track is also CAPPED (240px) rather than taking every spare pixel: a
// `1fr` NAME stretched the table to the full step width, leaving a wide empty
// band between a short name and the IV column and pushing GATE to the far right
// edge. Capped, the columns sit together on the left and the spare width falls
// after GATE.
const COLUMNS = '24px 32px 72px minmax(0, 240px) 120px 70px 110px 80px';

/** Module-level so the "no scan yet" case is a STABLE reference. `?? []` built a
 *  fresh array every render, so before a scan landed every memo below it
 *  (watchlist, candidateMap, gatedRows, gateSummary) recomputed on every single
 *  render and the "computed ONCE" claim held only after a scan. */
const NO_CANDIDATES: TradeCardData[] = [];

/** Every flag false: the drivers of a row that was never graded. */
const NO_DRIVERS: GateDrivers = Object.freeze({
  iv: false, event: false, ivMissing: false, hasIv: false, ivGated: false,
});

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
  // Two selectors, never one returning a fresh object (Zustand v5 re-renders
  // forever on that); the effective record is derived in a memo.
  const ivFetched   = useIvThresholdsStore((s) => s.thresholds);
  const ivOverrides = useIvThresholdsStore((s) => s.overrides);
  const ivStatus    = useIvThresholdsStore((s) => s.status);
  const ivError     = useIvThresholdsStore((s) => s.error);
  const eventThresholds = useEventThresholdsStore((s) => s.thresholds);
  const evStatus        = useEventThresholdsStore((s) => s.status);
  const evError         = useEventThresholdsStore((s) => s.error);
  const ivThresholds = useMemo(
    () => effectiveIvThresholds(ivFetched, ivOverrides),
    [ivFetched, ivOverrides],
  );

  // Fetched on every mount, so a scoring_rules.yaml edit reaches this page on
  // the next visit (subject to the backend's lru_cache on load_scoring_cfg).
  const refetchThresholds = useCallback(() => {
    void useIvThresholdsStore.getState().fetch();
    void useEventThresholdsStore.getState().fetch();
  }, []);
  useEffect(() => { refetchThresholds(); }, [refetchThresholds]);

  const avail: ThresholdsAvail =
    ivStatus === 'failed' || evStatus === 'failed' ? 'failed'
    : ivThresholds !== null && eventThresholds !== null ? 'ready'
    : 'loading';
  const availError = ivStatus === 'failed' ? ivError : evStatus === 'failed' ? evError : null;
  const watchlist = useMemo(() => candidates.map(cardToRow), [candidates]);
  const candidateMap = useMemo(
    () => Object.fromEntries(candidates.map((c) => [c.symbol, c])),
    [candidates],
  );

  const horizonKey: ThresholdHorizon = context?.horizon?.startsWith('Intraday') ? 'Intraday'
    : context?.horizon?.startsWith('Position') ? 'Position'
    : 'Swing';
  // The horizon's YAML window from /api/config/event-thresholds, applied only to
  // results persisted before scans echoed `event_window` (below).
  // null while `avail !== 'ready'`: nothing below may quote a window it does not
  // have. That holds even when the result echoes a window: the page grades
  // nothing until BOTH stores are in hand (decision DOCC-3-THRESHOLD-STORES-REFUSE).
  const baseWindow = avail === 'ready' && eventThresholds !== null
    ? getEventWindow(horizonKey, eventThresholds) : null;
  // A Step-3 override of the window (typed by hand, or restored by a search
  // profile such as SemiAnnual_* at 7/30) replaces the YAML window inside
  // score_stock()'s _rule_event. Gating here on the YAML window alone
  // re-rejected stocks the scan had just accepted (earnings in 15 days passed a
  // 7-day reject server-side, then showed REJECT here against 30). The window
  // comes from the RESULT, which echoes what the scan applied -- not from live
  // scanOverrides, which are not persisted (a reload reverted the fix) and can
  // be edited after the scan (grading rows against a window they were never
  // scored on). Results from before the echo existed fall back to the YAML window.
  const scanEventWindow = useScanStore((s) => s.scanResult?.event_window);
  const eventWindow = baseWindow === null ? null
    : scanEventWindow ? { ...baseWindow, ...scanEventWindow } : baseWindow;
  const evReject  = eventWindow?.reject_days ?? null;
  const evCaution = eventWindow?.caution_days ?? null;
  const ivOverride = avail === 'ready' ? ivOverrideFor(horizonKey, ivFetched, ivOverrides) : null;

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
    if (ivThresholds === null) return 'NO_DATA';   // never reached: gatedRows checks avail first
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
  // Computed ONLY when `ready`: "IV gate disabled" must never be said about a
  // config nobody has read.
  const gateDisabled =
    avail === 'ready' && ivThresholds !== null &&
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
    // No thresholds in hand: no verdict on either side, and none combined.
    if (avail !== 'ready' || evReject === null || evCaution === null) {
      const none: Status = avail === 'failed' ? 'NO_DATA' : 'PENDING';
      return { r, c, iv, hasIv, ivSt: none, proxStatus: none, gate: none, drivers: NO_DRIVERS };
    }
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
    // Gate must use THIS scan's window (evCaution/evReject: the result's echoed
    // event_window, else the horizon's YAML window) — not a fixed cutoff. The
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
  }), [watchlist, candidateMap, ivStatusFor, evReject, evCaution, gateDisabled, avail]);


  // DERIVED FROM gatedRows rather than looping the watchlist and calling
  // resolveIv all over again. Two memos computing the same quantity is exactly
  // what this file's module header warns about: "two editors each computing the
  // same quantity their own way is how this codebase has repeatedly regressed."
  const basesPresent = useMemo(() => {
    const seen = new Set<IvBasis>();
    for (const g of gatedRows) if (g.iv.basis !== 'none') seen.add(g.iv.basis);
    return [...seen];
  }, [gatedRows]);

  const ivBands: IvBand[] = avail !== 'ready' || ivThresholds === null ? [] : basesPresent
    .map((b) => {
      const passMax = getIvPassMax(horizonKey, ivThresholds, b);
      if (passMax === null) return null;
      return { basis: b, passMax, cautionMax: getIvCautionMax(horizonKey, ivThresholds, b) };
    })
    .filter((x): x is IvBand => x !== null);
  const thresholdSentences = ivThresholdSentence(ivBands);

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
    if (total === 0 || avail !== 'ready') return null;
    const pass = gatedRows.filter((g) => g.gate === 'PASS').length;
    const caution = gatedRows.filter((g) => g.gate === 'CAUTION').length;
    const reject = gatedRows.filter((g) => g.gate === 'REJECT').length;
    const counts: GateCounts = { total, pass, caution, reject };

    // TWO DIFFERENT QUESTIONS, and an adversarial round showed why they must not
    // share one list. "What decided the verdict" is the driver; "what could not
    // be read" is data quality. While they were one list, a scan where every row
    // was REJECTED by an event said NOTHING about the rows that also had no
    // volatility reading -- because `drivers.iv` is only true when the IV side is
    // AT the gate, and a missing reading is CAUTION, which is not REJECT. The
    // banner's whole reason for existing vanished in the case it was built for.
    const count = (f: (g: (typeof gatedRows)[number]) => boolean) => gatedRows.filter(f).length;
    // KEYS, not phrases. The words live in CAUSE_LABEL (gateSummary.ts), which one test pins by
    // equality -- see THE BANNER'S CLOSED VOCABULARY above for the measurement
    // that forced this.
    const causes: GateCause[] = ([
      { n: count((g) => g.drivers.iv && !g.drivers.ivMissing && g.iv.basis === 'rank'), key: 'ivRank' },
      { n: count((g) => g.drivers.iv && !g.drivers.ivMissing && g.iv.basis === 'absolute'), key: 'ivAbs' },
      { n: count((g) => g.drivers.event), key: 'event' },
    ] as GateCause[]).filter((c) => c.n > 0).sort((a, b) => b.n - a.n);

    // Counted whether or not it drove the verdict, and deliberately NOT part of
    // the sorted list -- it trails as its own sentence so the sort can never
    // demote the one fact this banner exists to surface. Excluded where the
    // horizon does not gate on volatility at all, because there a missing
    // reading costs the candidate nothing.
    const noReading = gateDisabled ? 0 : count((g) => !g.hasIv);

    let causesPart: { list: GateCause[]; overlap: boolean } | null = null;
    if (causes.length > 0) {
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
      causesPart = { list: causes, overlap: sum > driven };
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
    const missing = noReading === 0 ? null : { rows: noReading, claim: MISSING_READING_CLAIM };

    return { counts, causes: causesPart, missing };
  }, [gatedRows, gateDisabled, avail]);

  return (
    /* THE WHOLE COMPONENT IS THE CONTRACT'S REGION, not one div inside it.
       Round 2 measured the cost of a region: widening it from the summary line
       to the header simply moved the edge, and a contradicting sentence one
       line BELOW the header shipped 1740/1740 green. The tests now enumerate
       every node under this root that puts text on screen or carries prose in
       an attribute, and every one of them must be declared with a pin. The
       gate config is published here because three sentences quote it and
       nothing compared them with the numbers actually applied. */
    <div
      className={styles.main}
      data-testid="step-5"
      data-avail={avail}
      data-ev-reject={evReject ?? ''}
      data-ev-caution={evCaution ?? ''}
      data-iv-gated={avail === 'ready' ? String(!gateDisabled) : 'unknown'}
      data-candidates={candidates.length}
      data-horizon={horizonKey}
    >
      {/* EVERYTHING THIS PAGE SAYS ABOUT THE GATE, IN ONE TESTABLE REGION.
          Round 1 of the structural loop measured the cost of scoping the
          contract to the summary line alone: appending "Rows with no volatility
          reading are graded PASS on the volatility side and may be traded as
          clean." to the sentence one line ABOVE it shipped the FULL 1724-test
          suite green, directly contradicting the clause below it. The header is
          now `data-line` rows of `data-part` sentences, and the tests pin the
          header's whole text as the sum of its lines -- so a gloss cannot be
          added anywhere in here without becoming a part that must be pinned. */}
      <div className={styles.stepHeader} data-testid="step-5-header">
        <span data-line="label"><span data-part="step-label">
          <Text size={11} tone="dim" weight={500}>STEP 5 OF 7</Text>
        </span></span>
        <span data-line="title"><span data-part="page-title">
          <Title as="h1" size={24}>Volatility + Events</Title>
        </span></span>
        <span data-line="thresholds">
          <Text size={13} tone="secondary">
            {avail !== 'ready' ? (
              /* NO THRESHOLDS: this part REPLACES the three below, and quotes no
                 number. Retry re-fetches both stores. */
              <>
                <span data-part="thresholds-unavailable" data-avail={avail} data-error={availError ?? ''}>
                  {thresholdsUnavailableSentence(avail, availError)}
                </span>
                {avail === 'failed' && (
                  <>
                    {' '}
                    <button type="button" data-part="thresholds-retry" onClick={refetchThresholds}>Retry</button>
                  </>
                )}
              </>
            ) : (<>
            {/* WHICH BRANCH, published. Round 2: reordering this ternary so a
                GATED horizon printed "IV gate disabled for this horizon."
                shipped 67/67 green -- the pin was an alternation over the four
                sayable sentences and graded which are sayable, never which is
                correct for the state. */}
            <span
              data-part="iv-thresholds"
              data-iv-bands={JSON.stringify(ivBands)}
              data-branch={
                gateDisabled              ? 'disabled'
                : candidates.length === 0 ? 'no-scan'
                : thresholdSentences !== '' ? 'thresholds'
                :                             'no-reading'
              }
            >{gateSentence}</span>
            {ivOverride !== null && (
              <>
                {' '}
                <span data-part="iv-override" data-override={ivOverride.value} data-yaml={ivOverride.yaml}>
                  {ivOverrideSentence(ivOverride.value, ivOverride.yaml)}
                </span>
              </>
            )}
            {' '}
            <span data-part="event-window">{eventWindow !== null && eventWindowSentence(eventWindow)}</span>
            {' '}
            <span data-part="gate-rule">Gate = worst of IV and event proximity.</span>
            </>)}
          </Text>
        </span>
        {gateSummary !== null && (
          <span data-line="summary">
            {/* ONE ELEMENT PER SENTENCE, EACH CARRYING THE DATA IT WAS RENDERED
                FROM, and the single spaces are the only text these lines hold
                directly -- so a test can enumerate `[data-part]`, pin each
                part's words against its own published data, and require the
                line to say exactly the sum of them. */}
            <Text size={12} tone="secondary">
              <span data-part="head" data-counts={JSON.stringify(gateSummary.counts)}>
                {headSentence(gateSummary.counts)}
              </span>
              {gateSummary.causes !== null && (
                <>
                  {' '}
                  <span
                    data-part="causes"
                    data-causes={JSON.stringify(gateSummary.causes.list)}
                    data-overlap={String(gateSummary.causes.overlap)}
                  >
                    {causesSentence(gateSummary.causes.list, gateSummary.causes.overlap)}
                  </span>
                </>
              )}
              {gateSummary.missing !== null && (
                <>
                  {' '}
                  {/* THE CLAIM ITSELF, in the DOM. The sentence beside it is
                      this same claim rendered; the tests read these attributes
                      and check each one against what the page does, not against
                      a constant retyped in the test file. */}
                  <span
                    data-part="missing-reading"
                    data-claim-rows={gateSummary.missing.rows}
                    data-claim-side={gateSummary.missing.claim.side}
                    data-claim-asserted={gateSummary.missing.claim.asserted}
                    data-claim-denied={gateSummary.missing.claim.denied}
                    data-claim-combination={gateSummary.missing.claim.combination}
                  >
                    {missingReadingClause(gateSummary.missing.rows, gateSummary.missing.claim)}
                  </span>
                </>
              )}
            </Text>
          </span>
        )}
      </div>

      <div className={`${styles.stepBody} ${styles.stepBody_noPad} ${pageStyles.tableBody}`}>
        <div
          className={pageStyles.tableHeader}
          style={{ gridTemplateColumns: COLUMNS }}
          data-colheaders={JSON.stringify(
            ['SYMBOL', 'NAME', ivColumnLabel(basesPresent), 'IV PCTL', 'NEXT EVENT', 'GATE'],
          )}
        >
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
            /* EVERY CELL DECLARES WHAT IT IS AND PUBLISHES WHAT IT RENDERS.
               Round 2 put a lying `title` on the IV cell and on the event cell,
               a lying `aria-label` one element above the claim, and a lying
               tooltip on every row -- all 67/67 green, because the contract
               looked only at `[data-part]` inside the header. Each cell below
               is now a declared node whose text and attributes are pinned
               against its own published data, and anything undeclared under
               the page root is red. */
            <TableRow key={r.symbol} status={gate} columns={COLUMNS}>
              <span data-cell="chart" data-symbol={r.symbol}>
                <OpenChartButton symbol={r.symbol} />
              </span>
              <span data-cell="watch" data-symbol={r.symbol}>
                <WatchStar symbol={r.symbol} size="sm" />
              </span>
              <span data-cell="symbol" data-value={r.symbol}>
                <Data size={13} weight={500}>{r.symbol}</Data>
              </span>
              <div className={pageStyles.nameCell} data-cell="company" data-value={r.company}>
                <Text size={12} tone="secondary">{r.company}</Text>
              </div>

              {/* IV rank + inline mini bar */}
              <div
                className={pageStyles.ivRankCell}
                title={shownIv.title}
                data-cell="iv"
                data-iv-basis={iv.basis}
                data-iv-value={iv.value === null ? '' : String(iv.value)}
              >
                <Data size={13} weight={500}>{shownIv.text}</Data>
                {shownIv.suffix !== '' && (
                  <Text size={10} tone="dim">{shownIv.suffix}</Text>
                )}
                {hasIv && avail === 'ready' && (
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
              <span data-cell="pctl" data-value={pctl != null ? String(pctl) : ''}>
                <Data size={13} weight={500}>{pctl != null ? pctl : '—'}</Data>
              </span>

              <span
                data-cell="event"
                data-days={r.nextEventDays != null ? String(r.nextEventDays) : ''}
                data-label={r.nextEventLabel ?? ''}
              >
                {r.nextEventDays != null
                  ? <EventFlag days={r.nextEventDays} title={r.nextEventLabel ?? undefined} />
                  : <Text size={11} tone="dim">—</Text>}
                {/* Audit round 1, F9. This gate grades the NEARER of earnings
                  * and dividend; only earnings veto a send (D3), so a row
                  * rejected by a dividend alone says so -- Step 7 will let it
                  * send. No note when earnings are inside the window too. */}
                {proxStatus === 'REJECT' && r.nextEventLabel === 'Dividend'
                  && !(c?.earningsDays != null && evReject != null && c.earningsDays < evReject) && (
                  <Text size={10} tone="dim">Dividend — score penalty, not a send veto</Text>
                )}
              </span>

              {/* THESE ARE PRODUCT DATA, NOT TEST HOOKS, and the distinction
                  matters because the tests treat them as observations of the
                  page. What they publish is the gate's own reasoning -- the two
                  sub-verdicts behind the badge -- which the tooltip beside them
                  already states in prose. `data-gate` and the badge's `status`
                  read the SAME variable in the same JSX, and both pinning
                  `data-gate` and pinning the badge go red on mutation, so the
                  coupling is not merely asserted here.

                  NOT VERIFIED IN JEST: `display: contents`. jest maps
                  `*.module.css` to an empty object, so `pageStyles.gateCell` is
                  `undefined` under test and the class never lands. The layout
                  reasoning was checked by hand against TableRow.module.css
                  (no `> *` or `:last-child` rules, so promoting the badge back
                  to grid item is safe), but a dropped or misspelt class name
                  would not be caught by anything. e2e is where that belongs.

                  THE TWO SIDES OF THE GATE, PUBLISHED SEPARATELY AND KEYED BY
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
                data-cell="gate"
                data-row={r.symbol}
                data-side-volatility={ivSt}
                data-side-event={proxStatus}
                data-gate={gate}
              >
              <StatusBadge
                status={gate}
                // Right-anchored: the panel opens leftward from the badge. Centred
                // on it, the panel reached past the table's right edge, where it
                // was cut off and summoned a horizontal scrollbar.
                tooltipAlign="right"
                tooltip={avail !== 'ready' || evReject === null || evCaution === null
                  ? thresholdsUnavailableSentence(avail === 'ready' ? 'loading' : avail, availError)
                  : eventVolGateTooltip({
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
