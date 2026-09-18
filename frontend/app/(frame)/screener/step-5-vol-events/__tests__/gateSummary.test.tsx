/*
 * The banner's second sentence — why the badges below say what they say.
 *
 * Kenneth looked at a CAUTION gate and asked "why? because of percentile?".
 * The page could not answer above the fold: it stated its thresholds and then
 * left a column of badges to be read one hover at a time. These tests pin the
 * distinction that makes the sentence worth having — a MISSING volatility
 * reading and a reading that FAILED its threshold wear the same CAUTION badge
 * and mean opposite things, and on this app the missing one is the common case
 * (a true percentile exists only when IBKR or tastytrade answered).
 */
import { render, screen } from '@testing-library/react';
import Step5Page, { missingReadingClause, type MissingReadingClaim } from '../page';
import { useScanStore } from '@/lib/scanStore';
import { useIvThresholdsStore } from '@/lib/ivThresholdsStore';
import { useEventThresholdsStore, FALLBACK as EVENT_FALLBACK } from '@/lib/eventThresholdsStore';
import type { TradeCardData } from '@/types/domain';

function makeCandidate(symbol: string, overrides: Partial<TradeCardData> = {}): TradeCardData {
  return {
    symbol,
    company: `${symbol} Co`,
    price: 100,
    direction: 'Bullish',
    status: 'PASS',
    stockScore: 70,
    stockConfidence: 'PASS',
    stockBreakdown: {} as any,
    nextEventDays: null,
    nextEventLabel: null,
    contract: `${symbol}|100|2026-12-01|C`,
    contractScore: 70,
    contractConfidence: 'PASS',
    contractBreakdown: {} as any,
    contractDetails: { strike: 100, expiry: '2026-12-01', right: 'C', mid: 1, delta: 0.45, theta: -0.05, ivRank: 10, ivPercentile: 10, dte: 90 },
    entry: {} as any,
    exit: {} as any,
    ...overrides,
  } as TradeCardData;
}

function setup(candidates: TradeCardData[], horizon = 'Swing (5-15d)') {
  useScanStore.setState({
    scanResult: { candidates, rejected: [], scan_id: 'x', timestamp: '' } as any,
    context: { direction: 'Bullish', horizon } as any,
  } as any);
  // Swing: rank <= 34 PASS, <= 55 CAUTION, above REJECT.
  // KEY CASE AND FIELD NAMES MATTER. This fixture was written as
  // `{ swing: { iv_rank_pass_max } }`, which matches nothing: the store is keyed
  // `Swing` with `rank_pass_max` / `rank_caution_max` (lib/ivThresholdsStore.ts).
  // getIvPassMax fell straight through to the module FALLBACK, which happens to
  // hold the same 34/55 -- so these tests silently asserted against production
  // defaults and would have moved with them.
  useIvThresholdsStore.setState({
    thresholds: {
      Swing: { rank_pass_max: 34, rank_caution_max: 55, abs_pass_max: 34, abs_caution_max: 55 },
    },
    loaded: true,
  } as any);
  useEventThresholdsStore.setState({ thresholds: EVENT_FALLBACK, loaded: true } as any);
}

/** A candidate with no volatility reading at all — no ivRank and no absolute iv. */
function noIvCandidate(symbol: string, overrides: Partial<TradeCardData> = {}) {
  return makeCandidate(symbol, {
    contractDetails: { strike: 100, expiry: '2026-12-01', right: 'C', mid: 1, delta: 0.45, theta: -0.05, dte: 90 } as any,
    ...overrides,
  });
}

/** The banner element itself. Needed because the per-row tooltip deliberately
 *  shares the banner's wording now, so a bare getByText matches both. */
function banner(): HTMLElement {
  return screen.getByText(/shown —/);
}

afterEach(() => {
  // Hygiene between tests IN THIS FILE, not a leak fix. An earlier comment here
  // claimed it stopped state escaping to other suites in the same worker; that
  // is false -- jest gives every test FILE its own module registry, so a
  // module-level Zustand store cannot cross files, and deleting this block
  // leaves the whole suite green. Kept because a test that forgets to call
  // setup() should not silently inherit the previous test's scan, and restoring
  // the real FALLBACK rather than {} so the restored state is a valid one.
  useScanStore.setState({ scanResult: undefined, context: undefined } as any);
  useIvThresholdsStore.setState({ thresholds: {}, loaded: false } as any);
  useEventThresholdsStore.setState({ thresholds: EVENT_FALLBACK, loaded: false } as any);
});

describe('Step 5 banner — the gate summary says WHY, not just what', () => {
  it('counts the verdicts on screen', () => {
    setup([makeCandidate('AAA'), makeCandidate('BBB')]);
    render(<Step5Page />);
    expect(screen.getByText(/2 shown — 2 PASS, 0 CAUTION, 0 REJECT/)).toBeInTheDocument();
  });

  it('names a MISSING volatility reading as the driver, and says it is not a pass', () => {
    // This is the exact case behind the question. The badge says CAUTION; the
    // cause is that nobody answered, not that the option is expensive.
    setup([noIvCandidate('AAA')]);
    render(<Step5Page />);
    // Scoped to the BANNER on purpose: the per-row tooltip now says
    // "no volatility reading" too, because both read gateDrivers. An unscoped
    // getByText finds two nodes and throws -- which is the invariant passing,
    // not failing.
    expect(banner().textContent).toMatch(/1 of them has no volatility reading at all/);
    // The clause must ANSWER the question ("why CAUTION?"), so the sub-verdict
    // has to be NAMED. Which word, on which side, and in which direction the
    // gate combines are all the claim's job now, asserted exactly on the line
    // below -- so this stays a presence check and pins no phrasing.
    expect(tailOf(banner().textContent ?? '')).toMatch(/CAUTION/);
    expectMissingReadingClause(banner().textContent ?? '', 1);
  });

  it('does NOT blame a missing reading when the reading exists and failed its threshold', () => {
    // ivRank 45 is a real reading, above Swing's PASS max of 34 -> CAUTION on IV.
    setup([makeCandidate('AAA', {
      contractDetails: { strike: 100, expiry: '2026-12-01', right: 'C', mid: 1, delta: 0.45, theta: -0.05, ivRank: 45, ivPercentile: 45, dte: 90 } as any,
    })]);
    render(<Step5Page />);
    expect(banner().textContent).toMatch(/above its threshold/);
    expect(banner().textContent).not.toMatch(/no volatility reading/);
  });

  it('separates an event-driven row from an IV-driven one in the same scan', () => {
    setup([
      noIvCandidate('AAA'),                                   // CAUTION, no reading
      makeCandidate('BBB', { nextEventDays: 3 }),             // REJECT, event inside 21d
    ]);
    render(<Step5Page />);
    const summary = screen.getByText(/2 shown —/);
    expect(summary.textContent).toMatch(/1 of them has no volatility reading at all/);
    expect(summary.textContent).toMatch(/1 on an event inside this horizon's window/);
  });

  it('stays silent when there is nothing to summarise', () => {
    setup([]);
    render(<Step5Page />);
    expect(screen.queryByText(/shown —/)).not.toBeInTheDocument();
  });
});

describe('a row can be driven by more than one thing', () => {
  it('counts a row under BOTH causes instead of a "both" bucket that names neither', () => {
    // The regression this replaces: the old exclusive enum tested "both drive"
    // BEFORE splitting a missing reading from a failed one, so this row printed
    // "2 on both" -- two of what, the sentence never said -- and the
    // missing-reading distinction, the entire point of the banner, vanished.
    setup([
      noIvCandidate('AAA', { nextEventDays: 30 }),   // no reading AND event in the 45d caution window
      noIvCandidate('BBB', { nextEventDays: 30 }),
    ]);
    render(<Step5Page />);
    const t = banner().textContent ?? '';
    expect(t).toMatch(/2 of them have no volatility reading at all/);
    expect(t).toMatch(/2 on an event inside this horizon's window/);
    expect(t).not.toMatch(/on both/);
  });

  it('leads with the most common cause, not the first one in the source', () => {
    // The old code pushed causes in a fixed order under a comment claiming it
    // sorted them. Uses two DRIVER causes, because the missing-reading clause is
    // deliberately no longer in the sorted list (it trails as its own sentence
    // so the sort can never demote it).
    const rows = [
      makeCandidate('RNK', {
        contractDetails: { strike: 100, expiry: '2026-12-01', right: 'C', mid: 1, delta: 0.45, theta: -0.05, ivRank: 45, ivPercentile: 45, dte: 90 } as any,
      }),
    ];
    for (let i = 0; i < 4; i++) rows.push(makeCandidate(`EV${i}`, { nextEventDays: 30 }));
    setup(rows);
    render(<Step5Page />);
    const t = banner().textContent ?? '';
    const evAt = t.indexOf('on an event');
    const rankAt = t.indexOf('on IV rank above');
    expect(evAt).toBeGreaterThanOrEqual(0);
    expect(rankAt).toBeGreaterThanOrEqual(0);
    expect(evAt).toBeLessThan(rankAt);   // 4 events outrank 1 rank failure
  });

  it('reports a missing reading even when something ELSE decided the verdict', () => {
    // Round 2's sharpest finding. `drivers.iv` is only true when the IV side is
    // AT the gate, so on a scan where every row is REJECTED by an event, rows
    // that ALSO had no volatility reading were CAUTION-on-IV, never REJECT, and
    // the banner said nothing at all about them -- in exactly the scenario the
    // banner was built for.
    setup([
      noIvCandidate('AAA', { nextEventDays: 3 }),   // no reading AND inside the 21d reject window
      noIvCandidate('BBB', { nextEventDays: 3 }),
    ]);
    render(<Step5Page />);
    const t = banner().textContent ?? '';
    expect(t).toMatch(/2 shown — 0 PASS, 0 CAUTION, 2 REJECT/);
    expect(t).toMatch(/2 on an event inside this horizon's window/);
    expect(t).toMatch(/2 of them have no volatility reading at all/);
  });

  it('flags that the causes can overlap, so they need not sum to the rows', () => {
    // "17 causes for 12 rows" with no cue on screen reads as a bug.
    setup([
      makeCandidate('BOTH', {
        nextEventDays: 3,
        contractDetails: { strike: 100, expiry: '2026-12-01', right: 'C', mid: 1, delta: 0.45, theta: -0.05, ivRank: 90, ivPercentile: 90, dte: 90 } as any,
      }),
    ]);
    render(<Step5Page />);
    expect(banner().textContent).toMatch(/Driven by \(a row can have more than one\)/);
  });

  it('distinguishes a rank failure from an absolute-IV failure', () => {
    // UNEQUAL COUNTS ON PURPOSE. The first version of this test used one row of
    // each, so both clauses read "1 ..." and swapping the two labels in the
    // source still passed -- the very defect the test was added to catch, and
    // its own comment claimed otherwise. Verified by mutation: with 2 vs 1, a
    // swap fails here.
    setup([
      makeCandidate('RNK1', {
        contractDetails: { strike: 100, expiry: '2026-12-01', right: 'C', mid: 1, delta: 0.45, theta: -0.05, ivRank: 45, ivPercentile: 45, dte: 90 } as any,
      }),
      makeCandidate('RNK2', {
        contractDetails: { strike: 100, expiry: '2026-12-01', right: 'C', mid: 1, delta: 0.45, theta: -0.05, ivRank: 47, ivPercentile: 47, dte: 90 } as any,
      }),
      makeCandidate('ABS', {
        contractDetails: { strike: 100, expiry: '2026-12-01', right: 'C', mid: 1, delta: 0.45, theta: -0.05, iv: 48, dte: 90 } as any,
      }),
    ]);
    render(<Step5Page />);
    const t = banner().textContent ?? '';
    expect(t).toMatch(/2 on IV rank above its threshold/);
    expect(t).toMatch(/1 on IV above its threshold/);
  });

  it('ROUND 3: an unreadable row cannot delete the overlap warning from rows it has nothing to do with', () => {
    // THE FINDING. Round 2 moved the missing-reading count OUT of the driver
    // list into its own trailing sentence, but left this guard comparing the
    // driver total against every non-PASS row. A row whose only driver is a
    // missing reading adds 0 to the drivers and 1 to that denominator, so each
    // one cancels a genuine double-count and SUPPRESSES the disclaimer.
    //
    // BOTH doubles-driven rows here are identical between this test and the one
    // above; only the two unreadable rows differ. Without the fix this prints
    // "1 on IV rank above its threshold; 1 on an event inside this horizon's
    // window" -- 4 attributions over 3 rows -- with no cue that they overlap.
    setup([
      makeCandidate('BOTH', {
        nextEventDays: 3,
        contractDetails: { strike: 100, expiry: '2026-12-01', right: 'C', mid: 1, delta: 0.45, theta: -0.05, ivRank: 90, ivPercentile: 90, dte: 90 } as any,
      }),
      noIvCandidate('NOIV1'),
      noIvCandidate('NOIV2'),
    ]);
    render(<Step5Page />);
    const t = banner().textContent ?? '';
    expect(t).toMatch(/Driven by \(a row can have more than one\)/);
    // And the counts it qualifies are still the real ones.
    expect(t).toMatch(/3 shown — 0 PASS, 2 CAUTION, 1 REJECT/);
    expect(t).toMatch(/2 of them have no volatility reading at all/);
  });

  it('ROUND 3: does NOT cry overlap when the causes really are disjoint', () => {
    // The guard is one-directional by construction (a row can never be counted
    // under both rank and absolute), and this pins that the fix did not simply
    // turn the cue on permanently -- which would make it noise and tell the
    // reader nothing.
    setup([
      makeCandidate('RNK', {
        contractDetails: { strike: 100, expiry: '2026-12-01', right: 'C', mid: 1, delta: 0.45, theta: -0.05, ivRank: 90, ivPercentile: 90, dte: 90 } as any,
      }),
      makeCandidate('EV', { nextEventDays: 3 }),
      noIvCandidate('NOIV'),
    ]);
    render(<Step5Page />);
    expect(banner().textContent).not.toMatch(/a row can have more than one/);
  });
});

describe('ROUND 3: a horizon that does not gate on volatility never claims it cleared one', () => {
  // END-TO-END THROUGH THE REAL PAGE ON PURPOSE. The round-3 mutation showed
  // the production wiring was unpinned: deleting the tooltip's third argument
  // entirely -- reverting round 2's fix where it actually ships -- left all
  // 1695 tests green, because the only test for that branch called
  // gateDriverPhrase directly. These go through Step5Page, so the argument the
  // page hands the classifier is part of what is pinned.
  //
  // Intraday's thresholds are all null and getIvPassMax falls through to the
  // module FALLBACK for any null it is given, so this case rests on FALLBACK
  // rather than on the fixture. Said out loud because round 2's headline
  // bookkeeping finding was a fixture that silently did nothing.
  it('does not tell an Intraday row at IV rank 95 that it is "clear on both"', () => {
    setup([
      makeCandidate('RICH', {
        contractDetails: { strike: 100, expiry: '2026-12-01', right: 'C', mid: 1, delta: 0.45, theta: -0.05, ivRank: 95, ivPercentile: 95, dte: 90 } as any,
      }),
    ], 'Intraday (0-2d)');
    render(<Step5Page />);
    // The banner says the gate is off...
    expect(screen.getByText(/IV gate disabled for this horizon/)).toBeInTheDocument();
    // ...so nothing one line below it may say the volatility side was cleared.
    const tip = screen.getByText(/Gate shows the worse of/);
    expect(tip.textContent).toMatch(/IV rank 95 \(PASS\)/);          // the figure still shows
    expect(tip.textContent).toMatch(/does not gate on volatility/);
    expect(tip.textContent).not.toMatch(/clear on both/);
  });
});

/* ===========================================================================
 * THE HEAD/TAIL PROBLEM, AND WHAT THESE TESTS CAN AND CANNOT PROVE.
 *
 * The banner is ONE string: a head sentence counting GATE verdicts, then
 * trailing clauses about something else (the IV SUB-verdict, data quality).
 * Every defect in this area has been the tail contradicting the head, and
 * SIX adversarial rounds have now walked past one, because each round checked
 * a fragment of the sentence rather than the sentence against the head.
 *
 * Three wordings have failed here, all of them green under the tests of their
 * day:
 *   "counted as CAUTION, never as PASS"        -- collided with a "0 CAUTION" head
 *   "can never earn a PASS, so it can only     -- collided with a "1 PASS" head,
 *    hold a candidate back"                       and its causal claim was FALSE
 *   "...so no row shown here can ever be       -- quantified over ALL shown rows
 *    a PASS"                                      under a "1 PASS" head
 *
 * TWO LAYERS, because neither alone is honest:
 *
 *  (1) GROUND TRUTH, hand-computed. Every case below declares its expected
 *      counts, derived BY HAND from the threshold tables, never from the
 *      page's own helpers. This matters: a previous round justified itself
 *      with a 406-case sweep that compared the rendered string against truth
 *      DERIVED FROM THE SAME CONSTRUCTION -- so it could only ever confirm the
 *      string was built as designed, never that it was COHERENT with the head
 *      beside it. It passed 406/406 over a self-contradicting banner.
 *
 *  (2) A WORDING CONTRACT on the tail. Called that, not "the invariant",
 *      because it is a set of mechanical rules over English and cannot prove
 *      the copy is true -- it can only kill the shapes that have actually gone
 *      wrong. Where it is a literal, it says so.
 * ======================================================================== */

/** Split the banner at its head sentence (the one carrying the gate counts). */
function splitBanner(text: string): { head: string; tail: string } {
  const end = text.indexOf('.');
  return end < 0
    ? { head: text, tail: '' }
    : { head: text.slice(0, end + 1), tail: text.slice(end + 1).trim() };
}
const tailOf = (text: string) => splitBanner(text).tail;

/* ── THE CONTRACT, ROUND 2: STOP GRADING ENGLISH ─────────────────────────
 * ROUND 2 DELETED THE REGEX RULES ENTIRELY. Round 1 replaced three literal
 * lists with four "positive" rules and the very next round broke four of them
 * with a full green suite: "on the event side" (wrong side), "so it can be
 * easier still" (a worst-of getting easier), "In the worst case, open the
 * column" (the reconciliation sentence deleted, one list word left behind to
 * satisfy the rule), and "not never PASS" (double negation read as an
 * assertion). It also REJECTED correct copy -- "rows with no reading count
 * CAUTION on the IV side, never PASS there" -- because the three-word negation
 * window cannot tell a negator that negates the verdict from one that merely
 * sits near it, and in this sentence family the subject IS "no reading".
 *
 * Four consecutive rounds faulted that one class. The rules were not the
 * defect; grading prose with regexes was. So the meaning moved INTO DATA
 * (page.tsx's MissingReadingClaim) and the clause is now generated from it.
 * This file no longer inspects English at all: it computes the claim the page
 * OUGHT to be making, renders the clause from that claim with the page's own
 * builder, and demands the banner contain exactly that.
 *
 * WHY THAT IS NOT JUST A LITERAL PIN BY ANOTHER NAME: the builder is shared,
 * so an edit to the SKELETON moves expectation and actual together. The
 * skeleton is therefore pinned separately, by one exact-string test, and a
 * second test proves no verdict word is hardcoded inside the builder. Between
 * them: reword freely, and you cannot change what it says.
 */

/** What page.tsx must claim for an unreadable row. Derived, not copied: the
 *  clause renders only when the horizon gates on volatility (page.tsx forces
 *  the count to 0 otherwise), and there an unreadable row is graded
 *  `gateDisabled ? 'PASS' : 'CAUTION'` -- so CAUTION, never PASS -- while the
 *  gate itself is worstStatus(iv, event), which can only go worse. */
const EXPECTED_CLAIM: MissingReadingClaim = {
  side:        'volatility',
  asserted:    'CAUTION',
  denied:      'PASS',
  combination: 'worse',
};

/** The banner must carry EXACTLY the clause the expected claim generates, or
 *  none at all when nothing is unreadable. No English is graded here. */
function expectMissingReadingClause(text: string, noReadingRows: number) {
  const { head } = splitBanner(text);
  expect(head).toMatch(/shown —/);
  if (noReadingRows === 0) {
    expect(text).not.toContain('no volatility reading at all');
    return;
  }
  expect(text).toContain(missingReadingClause(noReadingRows, EXPECTED_CLAIM));
}

/** Thresholds for ALL THREE horizons, so nothing silently falls through to the
 *  module FALLBACK -- the trap this file's own `setup` comment documents. */
function setupHorizon(candidates: TradeCardData[], horizon: string) {
  useScanStore.setState({
    scanResult: { candidates, rejected: [], scan_id: 'x', timestamp: '' } as any,
    context: { direction: 'Bullish', horizon } as any,
  } as any);
  useIvThresholdsStore.setState({
    thresholds: {
      Intraday: { abs_pass_max: null, abs_caution_max: null, rank_pass_max: null, rank_caution_max: null },
      Swing:    { abs_pass_max: 34, abs_caution_max: 55, rank_pass_max: 34, rank_caution_max: 55 },
      Position: { abs_pass_max: 44, abs_caution_max: 65, rank_pass_max: 44, rank_caution_max: 65 },
    },
    loaded: true,
  } as any);
  useEventThresholdsStore.setState({ thresholds: EVENT_FALLBACK, loaded: true } as any);
}

/** A candidate carrying a real IV RANK reading. */
function rankCandidate(symbol: string, ivRank: number, overrides: Partial<TradeCardData> = {}) {
  return makeCandidate(symbol, {
    contractDetails: { strike: 100, expiry: '2026-12-01', right: 'C', mid: 1, delta: 0.45,
                       theta: -0.05, ivRank, ivPercentile: ivRank, dte: 90 } as any,
    ...overrides,
  });
}

describe('the banner never counts two different things in one breath', () => {
  /* Windows, for the hand-computation in each row below:
   *   Swing    IV rank PASS <=34, CAUTION <=55 | event REJECT <21d, CAUTION <45d
   *   Position IV rank PASS <=44, CAUTION <=65 | event REJECT <30d, CAUTION <60d
   *   Intraday no IV gate at all               | event REJECT  <1d, CAUTION  <3d
   * gate = worstStatus(ivStatus, eventStatus); a row with no reading is
   * CAUTION on the IV side unless the horizon does not gate on volatility,
   * where it is PASS and the trailing clause is suppressed entirely. */
  const cases: Array<{
    name: string; horizon: string; candidates: () => TradeCardData[];
    head: string; noReadingRows: number;
  }> = [
    {
      name: 'every unreadable row REJECTed by an event — head shows 0 CAUTION',
      horizon: 'Swing (5-15d)',
      candidates: () => [noIvCandidate('AAA', { nextEventDays: 3 }), noIvCandidate('BBB', { nextEventDays: 3 })],
      // both: iv CAUTION, event REJECT (3 < 21) -> REJECT
      head: '2 shown — 0 PASS, 0 CAUTION, 2 REJECT.', noReadingRows: 2,
    },
    {
      name: 'a readable PASS row beside an unreadable REJECTed one — head shows 1 PASS',
      horizon: 'Swing (5-15d)',
      candidates: () => [rankCandidate('AAA', 10), noIvCandidate('BBB', { nextEventDays: 3 })],
      // rank 10 <= 34 -> PASS, no event -> PASS | iv CAUTION + event REJECT -> REJECT
      head: '2 shown — 1 PASS, 0 CAUTION, 1 REJECT.', noReadingRows: 1,
    },
    {
      name: 'a PASS row beside an unreadable CAUTION one — head shows both, and NO reject',
      horizon: 'Swing (5-15d)',
      candidates: () => [rankCandidate('AAA', 10), noIvCandidate('BBB')],
      // THE SHAPE WITH NO REJECT AT ALL: an earlier contract skipped its whole
      // reconciliation branch here, which is exactly where a PASS collision lives.
      head: '2 shown — 1 PASS, 1 CAUTION, 0 REJECT.', noReadingRows: 1,
    },
    {
      name: 'a READABLE caution beside an unreadable one — same badge, opposite meanings',
      horizon: 'Swing (5-15d)',
      candidates: () => [rankCandidate('AAA', 45), noIvCandidate('BBB')],
      // rank 45: >34 and <=55 -> CAUTION | unreadable -> CAUTION
      head: '2 shown — 0 PASS, 2 CAUTION, 0 REJECT.', noReadingRows: 1,
    },
    {
      name: 'an IV-REJECTed readable row beside an unreadable one',
      horizon: 'Swing (5-15d)',
      candidates: () => [rankCandidate('AAA', 95), noIvCandidate('BBB')],
      // rank 95 > 55 -> REJECT | unreadable -> CAUTION
      head: '2 shown — 0 PASS, 1 CAUTION, 1 REJECT.', noReadingRows: 1,
    },
    {
      name: 'POSITION horizon, unreadable row inside the caution window only',
      horizon: 'Position (1-3m)',
      candidates: () => [noIvCandidate('AAA', { nextEventDays: 40 })],
      // iv CAUTION | event 40: not <30, but <60 -> CAUTION -> CAUTION
      head: '1 shown — 0 PASS, 1 CAUTION, 0 REJECT.', noReadingRows: 1,
    },
    {
      name: 'POSITION horizon, its own thresholds and not Swing’s',
      horizon: 'Position (1-3m)',
      candidates: () => [rankCandidate('AAA', 50), noIvCandidate('BBB', { nextEventDays: 25 })],
      // 25 DAYS, NOT 20, AND THE DIFFERENCE IS THE WHOLE POINT OF THIS CASE.
      // At 20d this case did not discriminate at all: Swing's reject_days is 21
      // and the comparison is strict `<`, so 20 REJECTs on Swing TOO, and rank
      // 50 is CAUTION under both bands (Swing <=55, Position <=65) -- the head
      // came out byte-identical under the wrong horizon. Proven: forcing
      // horizonKey to 'Swing' left all 21 tests in this file green.
      //   25d: Position -> 25 < 30 -> REJECT.  Swing -> not <21, but <45 -> CAUTION.
      // so reading Swing's window here yields '0 PASS, 2 CAUTION, 0 REJECT'.
      head: '2 shown — 0 PASS, 1 CAUTION, 1 REJECT.', noReadingRows: 1,
    },
    {
      // THE BOUNDARY, WHICH NOTHING IN THIS FILE PINNED. Flipping BOTH of
      // page.tsx's `value <= max` comparisons to `<` left all three step-5
      // suites green -- a row sitting exactly on its threshold could flip
      // PASS->CAUTION with no test going red. Every other case here uses an
      // interior rank (10, 45, 47, 50, 90, 95).
      name: 'IV rank exactly ON the Swing PASS boundary — 34 is PASS, not CAUTION',
      horizon: 'Swing (5-15d)',
      candidates: () => [rankCandidate('AAA', 34), noIvCandidate('BBB')],
      // rank 34 <= 34 -> PASS (inclusive). BBB unreadable -> CAUTION, no event -> PASS.
      head: '2 shown — 1 PASS, 1 CAUTION, 0 REJECT.', noReadingRows: 1,
    },
    {
      // ROUND 2 FINDING F4, AND IT WAS A BUG IN THE CONTRACT ITSELF, not a
      // coverage gap: no case had noReadingRows 0 with a non-empty tail, and
      // the old R3 demanded asserts === ['CAUTION'] unconditionally -- so this
      // perfectly correct banner, whose tail is only the "Driven by:" sentence,
      // FAILED it. The `else` branch was unreachable dead code written for a
      // case the contract would have rejected. It is a real rendered shape and
      // it is now covered.
      name: 'every row readable — a tail with causes and NO missing-reading clause',
      horizon: 'Swing (5-15d)',
      candidates: () => [rankCandidate('AAA', 45), rankCandidate('BBB', 10, { nextEventDays: 3 })],
      // rank 45: >34, <=55 -> CAUTION, no event -> PASS -> CAUTION
      // rank 10: <=34 -> PASS, event 3 < 21 -> REJECT -> REJECT
      head: '2 shown — 0 PASS, 1 CAUTION, 1 REJECT.', noReadingRows: 0,
    },
    {
      name: 'IV rank exactly ON the Swing CAUTION boundary — 55 is CAUTION, not REJECT',
      horizon: 'Swing (5-15d)',
      candidates: () => [rankCandidate('AAA', 55), noIvCandidate('BBB')],
      // rank 55: >34, and <=55 -> CAUTION (inclusive). 56 would REJECT.
      head: '2 shown — 0 PASS, 2 CAUTION, 0 REJECT.', noReadingRows: 1,
    },
  ];

  for (const c of cases) {
    it(`stays coherent with its own head — ${c.name}`, () => {
      setupHorizon(c.candidates(), c.horizon);
      render(<Step5Page />);
      const text = banner().textContent ?? '';
      const { head, tail } = splitBanner(text);

      // Hand-computed above, asserted exactly.
      expect(head).toBe(c.head);
      // DIGIT-ANCHORED. Unanchored, "12 of them have ..." CONTAINS
      // "2 of them have ...", so a banner counting 12 unreadable rows satisfied
      // an expectation of 2 -- on the one assertion carrying this whole
      // feature's headline claim. NOT anchored at ^: the tail legitimately
      // opens with the "Driven by: ..." causes sentence, so the count clause is
      // not always first.
      if (c.noReadingRows > 0) {
        expect(tail).toMatch(
          new RegExp(`(?<!\\d)${c.noReadingRows} of them ha(s|ve) no volatility reading at all\\b`),
        );
      } else {
        expect(tail).not.toMatch(/no volatility reading at all/);
      }
      expectMissingReadingClause(text, c.noReadingRows);
    });
  }

  it('suppresses the clause entirely where the horizon does not gate on volatility', () => {
    // Intraday has no IV gate, so an unreadable row costs nothing and the
    // trailing sentence must not appear at all -- there is no sub-verdict to
    // reconcile, and claiming one would be the same defect in reverse.
    setupHorizon([noIvCandidate('AAA')], 'Intraday (0-2d)');
    render(<Step5Page />);
    const text = banner().textContent ?? '';
    expect(splitBanner(text).head).toBe('1 shown — 1 PASS, 0 CAUTION, 0 REJECT.');
    expect(text).not.toMatch(/no volatility reading at all/);
    // ZERO, and this call is now meaningful rather than vacuous. Under the old
    // contract a clause-less banner hit `if (tail === '') return;` and asserted
    // nothing -- while a clause-less banner WITH a "Driven by:" tail failed R3
    // outright, because R3 demanded asserts === ['CAUTION'] unconditionally.
    expectMissingReadingClause(text, 0);
  });
});


describe('the clause builder carries the meaning, so the prose cannot drift from it', () => {
  /* These two are the whole reason the derived comparison above is not merely a
   * literal pin wearing a hat. The comparison shares the builder with the page,
   * so an edit to the SKELETON moves expectation and actual together and stays
   * green. The first test pins the skeleton exactly -- the one place in this
   * file where a literal string belongs. The second proves no verdict word or
   * direction word is hardcoded INSIDE the builder, so the claim really is what
   * decides what the banner says. */

  it('renders the agreed skeleton, word for word', () => {
    expect(missingReadingClause(1, {
      side: 'volatility', asserted: 'CAUTION', denied: 'PASS', combination: 'worse',
    })).toBe(
      '1 of them has no volatility reading at all — graded CAUTION on the volatility ' +
      'side alone, never PASS there. The gate verdict above is the worse of that and ' +
      'the event window, so it can be lower still.',
    );
  });

  it('interpolates every meaning-bearing word from the claim, hardcoding none', () => {
    // Deliberately absurd values: if ANY of these four words is a literal in the
    // builder rather than a field, this fails.
    const s = missingReadingClause(2, {
      side: 'event', asserted: 'REJECT', denied: 'CAUTION', combination: 'better',
    });
    expect(s).toContain('2 of them have no volatility reading at all');
    expect(s).toContain('graded REJECT on the event side alone, never CAUTION there');
    expect(s).toContain('the better of that and the event window, so it can be higher still');
  });
});

describe('the fixture is actually read, and Position has its own IV band', () => {
  it('uses the INJECTED thresholds, not the module FALLBACK', () => {
    // ROUND 2 FINDING: setupHorizon's values were byte-identical to
    // ivThresholdsStore's FALLBACK, so `thresholds[k] ?? FALLBACK[k]` could not
    // tell which side answered. Proven: making getIvPassMax/getIvCautionMax
    // ignore the store entirely and read FALLBACK left all 38 step-5 tests
    // green. These thresholds are deliberately NOT the fallback's.
    setupHorizon([rankCandidate('AAA', 25)], 'Swing (5-15d)');
    useIvThresholdsStore.setState({
      thresholds: {
        Intraday: { rank_pass_max: null, rank_caution_max: null, abs_pass_max: null, abs_caution_max: null },
        Swing:    { rank_pass_max: 20, rank_caution_max: 30, abs_pass_max: 20, abs_caution_max: 30 },
        Position: { rank_pass_max: 44, rank_caution_max: 65, abs_pass_max: 44, abs_caution_max: 65 },
      },
      loaded: true,
    } as any);
    render(<Step5Page />);
    // rank 25 is PASS under the FALLBACK (<=34) and CAUTION under the injected
    // band (>20, <=30). If the store is bypassed this reads "1 PASS".
    expect(banner().textContent).toContain('1 shown — 0 PASS, 1 CAUTION, 0 REJECT.');
  });

  it('grades a Position row on POSITION\'s IV band, not Swing\'s', () => {
    // ROUND 2 FINDING: the case named "its own thresholds and not Swing's"
    // discriminated on the EVENT window only -- its rank 50 is CAUTION under
    // both bands, so Position's 44/65 was pinned by nothing. Rank 40 is PASS on
    // Position (<=44) and CAUTION on Swing (>34), so routing Position's IV
    // lookup to Swing now fails here.
    setupHorizon([rankCandidate('AAA', 40)], 'Position (1-3m)');
    render(<Step5Page />);
    expect(banner().textContent).toContain('1 shown — 1 PASS, 0 CAUTION, 0 REJECT.');
  });
});
