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
import { cleanup, render, screen } from '@testing-library/react';
import Step5Page from '../page';
import {
  missingReadingClause, headSentence, causesSentence,
  eventWindowSentence,
  CAUSE_LABEL,
  type MissingReadingClaim, type GateCause, type GateCounts, type CauseKey, type IvBand,
} from '../gateSummary';
import { STATUS_LABEL } from '@/lib/status';
import { formatIv, type IvBasis } from '@/lib/ivBasis';
import { eventVolGateTooltip, gateDrivers } from '@/lib/statusTooltips';
import { worstStatus, type Status } from '@/lib/status';
import { useScanStore } from '@/lib/scanStore';
import { useIvThresholdsStore } from '@/lib/ivThresholdsStore';
import { useEventThresholdsStore } from '@/lib/eventThresholdsStore';
import { api } from '@/lib/api';
import { EVENT_SHIPPED, IV_SHIPPED, echoStoredThresholds } from '@/lib/testFixtures/thresholds';
import {
  banner, partsOf, expectPageCopy, gateCopy, PART_ORDER, PART_PINS, PROSE_ATTRS,
  nodeId, claimOf, sideVerdict, SIDES, gateOf,
} from '../testSupport/pageContract';

// The page fetches both stores on mount; each fetch answers with the record the
// test set, so it re-sets the test's values rather than clearing them.
jest.mock('@/lib/api', () => ({ api: { getIvThresholds: jest.fn(), getEventThresholds: jest.fn() } }));
beforeEach(() => echoStoredThresholds(api as unknown as Parameters<typeof echoStoredThresholds>[0]));
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
  // getIvPassMax fell straight through to the (since deleted, DOCC-3) module
  // fallback, which happened to hold the same 34/55 -- so these tests silently
  // asserted against production defaults and would have moved with them.
  // DOCC-3: the full shipped record (Swing is exactly the 34/55 above); a
  // partial one is now refused by the store's parser on the mount fetch.
  useIvThresholdsStore.setState({ thresholds: IV_SHIPPED, status: 'ready', error: null, overrides: {} });
  useEventThresholdsStore.setState({ thresholds: EVENT_SHIPPED, status: 'ready', error: null });
}

/** A candidate with no volatility reading at all — no ivRank and no absolute iv. */
function noIvCandidate(symbol: string, overrides: Partial<TradeCardData> = {}) {
  return makeCandidate(symbol, {
    contractDetails: { strike: 100, expiry: '2026-12-01', right: 'C', mid: 1, delta: 0.45, theta: -0.05, dte: 90 } as any,
    ...overrides,
  });
}

afterEach(() => {
  // Hygiene between tests IN THIS FILE, not a leak fix. An earlier comment here
  // claimed it stopped state escaping to other suites in the same worker; that
  // is false -- jest gives every test FILE its own module registry, so a
  // module-level Zustand store cannot cross files, and deleting this block
  // leaves the whole suite green. Kept because a test that forgets to call
  // setup() should not silently inherit the previous test's scan. DOCC-3: the
  // stores go back to their initial state -- nothing in hand, nothing fetched.
  useScanStore.setState({ scanResult: undefined, context: undefined } as any);
  useIvThresholdsStore.setState({ thresholds: null, status: 'idle', error: null, overrides: {} });
  useEventThresholdsStore.setState({ thresholds: null, status: 'idle', error: null });
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
    // gate combines are the claim's job now -- published as attributes and
    // checked against behaviour at the foot of this file -- so this stays a
    // presence check on the sentence and pins no phrasing.
    expect(partsOf()['missing-reading'].textContent).toMatch(/CAUTION/);
    expectGateCopy(1);
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
    const summary = banner();
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
    expect(banner().textContent).toMatch(/Driven by measured checks \(a row can have more than one\)/);
    expect(banner().textContent).toContain(
      "Driven by measured checks (a row can have more than one): 1 on IV rank above its threshold; 1 on an event inside this horizon's window.",
    );
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
    expect(t).toMatch(/Driven by measured checks \(a row can have more than one\)/);
    expect(t).toContain(
      "Driven by measured checks (a row can have more than one): 1 on IV rank above its threshold; 1 on an event inside this horizon's window.",
    );
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
  // Intraday's thresholds are all null in the fixture (IV_SHIPPED), and since
  // DOCC-3 a null is read as "no gate" straight from the record -- there is no
  // module fallback left for it to fall through to.
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
 *  (2) A STRUCTURAL CONTRACT on the rest of the line. NOT a wording contract:
 *      four rounds of mechanical rules over English failed, and round 4
 *      measured the last of them admitting false copy and rejecting true copy
 *      at once. The banner is now enumerated parts and the missing-reading
 *      part carries its claim as `data-claim-*` attributes, so these tests
 *      assert what the page CLAIMS and never parse what it SAYS. Each field of
 *      that claim is tied to rendered behaviour at the foot of this file.
 * ======================================================================== */

/** THE STRUCTURAL CONTRACT ON EVERYTHING THIS PAGE SAYS ABOUT THE GATE. No
 *  English is graded except fixed product copy, and that is anchored.
 *
 *  THE CONTRACT IT REPLACES, AND WHY IT HAD TO GO. Four rounds tried to prove
 *  the prose correct: literal lists, then four "positive" regex rules, then a
 *  data-driven clause compared with `toContain`, then that plus a three-token
 *  "no verdict word may appear outside the clause" rule. Round 4 measured the
 *  last one ADMITTING false copy -- "safe to trade as if they were clean" names
 *  no verdict word, so it passed while contradicting the clause one sentence
 *  later -- and REJECTING true copy, 11 red on a statement true of the page, AT
 *  THE SAME TIME. A rule that does both is not strict; it is the wrong shape.
 *
 *  ROUND 1 OF THE STRUCTURAL LOOP FOUND THREE MORE, ALL MEASURED GREEN, and
 *  each one is why a line below exists:
 *    - a contradicting sentence one line ABOVE the banner: 1724/1724 green,
 *      because the contract was scoped to one `data-testid`;
 *    - "; these rows are safe to trade as if they were clean." appended to the
 *      causes sentence: 51/51 green, because that part was held to a
 *      PUNCTUATION rule -- which rejected a TRUE sentence at the same site;
 *    - a `data-part="note"` gloss plus its name in a whitelist: 51/51 green,
 *      because membership is not truth.
 *
 *  What is pinned now:
 *    1. every part is one the page is allowed to say, in the declared order,
 *       and each has a PIN that derives its words from its own published data;
 *    2. each line says exactly the sum of its parts, and the header says
 *       exactly the sum of its lines -- so no sentence can be added anywhere in
 *       the header without becoming a part;
 *    3. the head's counts are checked against the ROWS on screen;
 *    4. the claim's row count is compared NUMERICALLY;
 *    5. no part smuggles a second voice through `title` or `aria-*`.
 *  What the claim's four fields MEAN is pinned separately, against behaviour
 *  and at production n, in "every field of the claim is answerable to the page"
 *  at the foot of this file. */
function expectGateCopy(rows: number) {
  // NOTHING UNDECLARED MAY SPEAK, anywhere under the page root. Everything
  // below this line is the extra structure the HEADER has on top of that.
  expectPageCopy();

  const header = gateCopy();
  const lines = [...header.querySelectorAll<HTMLElement>('[data-line]')];
  // NO `expect(lines.length).toBeGreaterThan(0)` and no `expect(parts.head)
  // .toBeDefined()`. Both were constant-true: the threshold line renders
  // unconditionally and the counts check below throws without the head. Round 1
  // removed two inert assertions on that ground and round 2 caught a third that
  // had survived; an assertion that cannot fail alone is noise.

  const ordered = [...header.querySelectorAll<HTMLElement>('[data-part]')];
  const names = ordered.map((el) => el.getAttribute('data-part') as string);

  /* EVERY PART IS DECLARED, IN ORDER. `filter` rather than a membership check,
   * so this one line pins the whitelist AND the order: an undeclared part is
   * dropped from the expectation and an out-of-order one is reordered, and
   * either way the comparison goes red. */
  expect(names).toEqual(PART_ORDER.filter((n) => names.includes(n)));

  /* ...AND DECLARING ONE MEANS PINNING IT. A name in a list was not enough:
   * round 1 shipped a lying `data-part="note"` at 51/51 green that way. */
  for (const el of ordered) {
    const pin = PART_PINS[el.getAttribute('data-part') as string];
    expect(typeof pin).toBe('function');
    pin(el);
  }

  /* EACH LINE IS THE SUM OF ITS PARTS, AND THE HEADER THE SUM OF ITS LINES.
   * Between them, stray text anywhere in the header fails: the single space is
   * the only separator the page renders inside a line, and the step label and
   * title are the only text outside the lines. */
  for (const line of lines) {
    const own = [...line.querySelectorAll<HTMLElement>('[data-part]')];
    expect(line.textContent).toBe(own.map((el) => el.textContent).join(' '));
  }
  // The header is the sum of its lines, and the step label and page title are
  // lines like any other now -- so neither is a literal in this assertion.
  expect(header.textContent).toBe(lines.map((l) => l.textContent).join(''));

  /* NO SECOND VOICE, ANYWHERE IN THE HEADER -- not just on the part element.
   * Round 2 moved a lying `title` and `aria-label` ONE ELEMENT UP, onto the
   * `[data-line]` wrapper, and shipped 67/67; and put an `aria-label` on a
   * child of the claim plus `aria-hidden` on the claim itself, deleting the
   * true sentence for screen-reader users while sighted ones still saw it.
   * Every element in the region, every prose attribute, nothing allowed. */
  for (const el of [header, ...header.querySelectorAll<HTMLElement>('*')]) {
    for (const attr of PROSE_ATTRS) {
      expect([nodeId(el), attr, el.getAttribute(attr)]).toEqual([nodeId(el), attr, null]);
    }
  }

  /* THE HEAD'S COUNTS ARE THE ROWS ON SCREEN. Without this the head is pinned
   * only to its own published data, which is the circularity this whole loop
   * exists to remove. Every rendered row publishes its gate verdict. */
  const counts = JSON.parse(
    partsOf().head.getAttribute('data-counts') as string,
  ) as GateCounts;
  const gates = [...document.querySelectorAll<HTMLElement>('[data-gate]')]
    .map((el) => el.getAttribute('data-gate'));
  expect({
    total:   gates.length,
    pass:    gates.filter((g) => g === 'PASS').length,
    caution: gates.filter((g) => g === 'CAUTION').length,
    reject:  gates.filter((g) => g === 'REJECT').length,
  }).toEqual(counts);

  const claimed = claimOf();

  if (rows === 0) {
    expect(claimed).toBeNull();
    expect(header.textContent).not.toContain('no volatility reading at all');
    return;
  }

  expect(claimed).not.toBeNull();
  /* NUMERIC, so there is no substring left to anchor. The previous pin was a
   * regex over the sentence and needed a `(?<!\d)` lookbehind, because
   * unanchored, "12 of them have ..." CONTAINS "2 of them have ..." -- and that
   * lookbehind lived in one parameterised loop rather than in this helper, so
   * every other caller was unprotected. `Number` has no such failure mode. */
  expect(claimed!.rows).toBe(rows);
}

/** Thresholds for ALL THREE horizons: a partial record would be refused by the
 *  store's parser on the mount fetch (DOCC-3). */
function setupHorizon(candidates: TradeCardData[], horizon: string) {
  useScanStore.setState({
    scanResult: { candidates, rejected: [], scan_id: 'x', timestamp: '' } as any,
    context: { direction: 'Bullish', horizon } as any,
  } as any);
  useIvThresholdsStore.setState({ thresholds: IV_SHIPPED, status: 'ready', error: null, overrides: {} });
  useEventThresholdsStore.setState({ thresholds: EVENT_SHIPPED, status: 'ready', error: null });
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
    /** The causes sentence's data, hand-computed: `[count, key]` in render
     *  order, or null where the page must print no causes sentence at all.
     *  ROUND 1 OF THE STRUCTURAL LOOP: the table declared the head and the
     *  unreadable count and said NOTHING about this sentence, so suppressing
     *  it whenever more than two rows were unreadable shipped 67/67 green --
     *  and a large unreadable count beside real drivers is the shape this app
     *  renders every scan. */
    causes: Array<[number, CauseKey]> | null;
  }> = [
    {
      name: 'every unreadable row REJECTed by an event — head shows 0 CAUTION',
      horizon: 'Swing (5-15d)',
      candidates: () => [noIvCandidate('AAA', { nextEventDays: 3 }), noIvCandidate('BBB', { nextEventDays: 3 })],
      // both: iv CAUTION, event REJECT (3 < 21) -> REJECT
      head: '2 shown — 0 PASS, 0 CAUTION, 2 REJECT.', noReadingRows: 2,
      causes: [[2, 'event']],
    },
    {
      name: 'a readable PASS row beside an unreadable REJECTed one — head shows 1 PASS',
      horizon: 'Swing (5-15d)',
      candidates: () => [rankCandidate('AAA', 10), noIvCandidate('BBB', { nextEventDays: 3 })],
      // rank 10 <= 34 -> PASS, no event -> PASS | iv CAUTION + event REJECT -> REJECT
      head: '2 shown — 1 PASS, 0 CAUTION, 1 REJECT.', noReadingRows: 1,
      causes: [[1, 'event']],
    },
    {
      name: 'a PASS row beside an unreadable CAUTION one — head shows both, and NO reject',
      horizon: 'Swing (5-15d)',
      candidates: () => [rankCandidate('AAA', 10), noIvCandidate('BBB')],
      // THE SHAPE WITH NO REJECT AT ALL: an earlier contract skipped its whole
      // reconciliation branch here, which is exactly where a PASS collision lives.
      head: '2 shown — 1 PASS, 1 CAUTION, 0 REJECT.', noReadingRows: 1,
      causes: null,
    },
    {
      name: 'a READABLE caution beside an unreadable one — same badge, opposite meanings',
      horizon: 'Swing (5-15d)',
      candidates: () => [rankCandidate('AAA', 45), noIvCandidate('BBB')],
      // rank 45: >34 and <=55 -> CAUTION | unreadable -> CAUTION
      head: '2 shown — 0 PASS, 2 CAUTION, 0 REJECT.', noReadingRows: 1,
      causes: [[1, 'ivRank']],
    },
    {
      name: 'an IV-REJECTed readable row beside an unreadable one',
      horizon: 'Swing (5-15d)',
      candidates: () => [rankCandidate('AAA', 95), noIvCandidate('BBB')],
      // rank 95 > 55 -> REJECT | unreadable -> CAUTION
      head: '2 shown — 0 PASS, 1 CAUTION, 1 REJECT.', noReadingRows: 1,
      causes: [[1, 'ivRank']],
    },
    {
      name: 'POSITION horizon, unreadable row inside the caution window only',
      horizon: 'Position (1-3m)',
      candidates: () => [noIvCandidate('AAA', { nextEventDays: 40 })],
      // iv CAUTION | event 40: not <30, but <60 -> CAUTION -> CAUTION
      head: '1 shown — 0 PASS, 1 CAUTION, 0 REJECT.', noReadingRows: 1,
      causes: [[1, 'event']],
    },
    {
      name: 'POSITION horizon, its own thresholds and not Swing’s',
      horizon: 'Position (1-3m)',
      candidates: () => [rankCandidate('AAA', 50), noIvCandidate('BBB', { nextEventDays: 25 })],
      // 25 DAYS, NOT 20, AND THE DIFFERENCE IS THE WHOLE POINT OF THIS CASE.
      // At 20d this case did not discriminate at all: Swing's reject_days is 21
      // and the comparison is strict `<`, so 20 REJECTs on Swing TOO, and rank
      // 50 is CAUTION under both bands (Swing <=55, Position <=65) -- the head
      // came out byte-identical under the wrong horizon. Proven at the time,
      // against the 21 tests this file then held (it has grown since).
      //   25d: Position -> 25 < 30 -> REJECT.  Swing -> not <21, but <45 -> CAUTION.
      // so reading Swing's window here yields '0 PASS, 2 CAUTION, 0 REJECT'.
      head: '2 shown — 0 PASS, 1 CAUTION, 1 REJECT.', noReadingRows: 1,
      causes: [[1, 'ivRank'], [1, 'event']],
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
      causes: null,
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
      causes: [[1, 'ivRank'], [1, 'event']],
    },
    {
      // ROUND 1 OF THE STRUCTURAL LOOP: no fixture anywhere combined a LARGE
      // missing-reading count with a non-empty causes list -- the n=4 and n=12
      // cases both happened to have zero causes. Measured: suppressing the
      // "Driven by" sentence whenever more than 2 rows were unreadable shipped
      // 51/51 green. This is the shape the app actually renders, because a true
      // percentile needs IBKR or tastytrade to answer while events are known for
      // everything.
      name: 'TWELVE unreadable rows AND five event-driven ones — both sentences at once',
      horizon: 'Swing (5-15d)',
      candidates: () => [
        ...Array.from({ length: 12 }, (_, i) => noIvCandidate(`U${i}`)),
        ...Array.from({ length: 5 }, (_, i) => rankCandidate(`E${i}`, 10, { nextEventDays: 3 })),
      ],
      // twelve unreadable -> CAUTION each; five readable rank 10 (PASS) with an
      // event 3 < 21 -> REJECT each.
      head: '17 shown — 0 PASS, 12 CAUTION, 5 REJECT.', noReadingRows: 12,
      causes: [[5, 'event']],
    },
    {
      // ROUND 4 FINDING: every case here counted 1 or 2 unreadable rows, and the
      // only pins above n=2 were exact-string tests of the BUILDER. n >= 4 is
      // this app's real case -- page.tsx's own comments describe "3 of 12" and
      // "11 unreadable rows" -- and it had never been rendered through the page.
      name: 'FOUR unreadable rows beside a readable PASS — the app\'s real shape',
      horizon: 'Swing (5-15d)',
      candidates: () => [
        rankCandidate('AAA', 10),
        noIvCandidate('B1'), noIvCandidate('B2'), noIvCandidate('B3'), noIvCandidate('B4'),
      ],
      // rank 10 <= 34 -> PASS, no event -> PASS | four unreadable -> CAUTION each
      head: '5 shown — 1 PASS, 4 CAUTION, 0 REJECT.', noReadingRows: 4,
      causes: null,
    },
    {
      // TWELVE, because "12 of them have ..." CONTAINS "2 of them have ..." and
      // the count assertion used to be a substring match. It is numeric now, and
      // this case is what proves the two-digit path is actually exercised.
      name: 'TWELVE unreadable rows — a two-digit count, which no case reached',
      horizon: 'Swing (5-15d)',
      candidates: () => Array.from({ length: 12 }, (_, i) => noIvCandidate(`U${i}`)),
      head: '12 shown — 0 PASS, 12 CAUTION, 0 REJECT.', noReadingRows: 12,
      causes: null,
    },
    {
      /* THE EVENT BOUNDARY, WHICH NOTHING IN THIS FILE PINNED -- the IV
       * boundary two cases up has had a table entry since round 3 and its
       * event twin had none. Every event fixture in this file uses an interior
       * day count (3, 25, 30, 40), so flipping page.tsx's `< evReject` to
       * `<=` left all three step-5 suites green, and the banner's own sentence
       * ("within 21 days -> REJECT") asserted the inclusive reading against a
       * gate, a tooltip and a backend rule that are all exclusive. */
      name: 'earnings exactly ON the Swing REJECT boundary — day 21 is CAUTION, not REJECT',
      horizon: 'Swing (5-15d)',
      candidates: () => [rankCandidate('AAA', 10, { nextEventDays: 21 }), rankCandidate('BBB', 10)],
      // rank 10 <= 34 -> PASS both. AAA: 21 is NOT < 21, but IS < 45 -> CAUTION.
      head: '2 shown — 1 PASS, 1 CAUTION, 0 REJECT.', noReadingRows: 0,
      causes: [[1, 'event']],
    },
    {
      name: 'earnings exactly ON the Swing CAUTION boundary — day 45 is PASS, not CAUTION',
      horizon: 'Swing (5-15d)',
      candidates: () => [rankCandidate('AAA', 10, { nextEventDays: 45 }), rankCandidate('BBB', 10)],
      // 45 is NOT < 45 -> PASS. The far edge of the window, where the sentence
      // stops making a claim at all.
      head: '2 shown — 2 PASS, 0 CAUTION, 0 REJECT.', noReadingRows: 0,
      causes: null,
    },
    {
      /* THE MASKED SUB-VERDICT. `gate` is worstStatus(iv, event), so on a row
       * whose IV is already REJECT the event side can be corrupted without the
       * gate, the head, the causes or the tooltip moving at all -- the tooltip
       * is rebuilt from the same published attribute that would carry the lie.
       * No fixture had that shape (every IV-REJECT row here has no event at
       * all), which left the event sub-verdict checkable only where it happened
       * to decide the gate. This row is where PART_PINS' event-window pin earns
       * its keep: flipping the gate's far-event branch from PASS to CAUTION
       * changes nothing on screen except an attribute that now disagrees with
       * the sentence above it. */
      name: 'an IV-REJECTed row with a far-out event — the event side still has to be right',
      horizon: 'Swing (5-15d)',
      candidates: () => [rankCandidate('AAA', 90, { nextEventDays: 60 }), rankCandidate('BBB', 10)],
      // rank 90 > 55 -> REJECT. 60 is not < 21 and not < 45 -> event PASS.
      // gate = worst(REJECT, PASS) = REJECT, and the event side is invisible in it.
      head: '2 shown — 1 PASS, 0 CAUTION, 1 REJECT.', noReadingRows: 0,
      causes: [[1, 'ivRank']],
    },
    {
      name: 'IV rank exactly ON the Swing CAUTION boundary — 55 is CAUTION, not REJECT',
      horizon: 'Swing (5-15d)',
      candidates: () => [rankCandidate('AAA', 55), noIvCandidate('BBB')],
      // rank 55: >34, and <=55 -> CAUTION (inclusive). 56 would REJECT.
      head: '2 shown — 0 PASS, 2 CAUTION, 0 REJECT.', noReadingRows: 1,
      causes: [[1, 'ivRank']],
    },
  ];

  for (const c of cases) {
    it(`stays coherent with its own head — ${c.name}`, () => {
      setupHorizon(c.candidates(), c.horizon);
      render(<Step5Page />);

      // Hand-computed above, asserted exactly, against the head's OWN element
      // rather than a split of the whole line on its first full stop.
      expect(partsOf().head.textContent).toBe(c.head);

      // AGAINST THE PUBLISHED DATA, not the sentence: PART_PINS already holds
      // the sentence to exactly this data, so pinning the data pins both.
      const causesEl = partsOf().causes;
      const published = causesEl === undefined ? null
        : (JSON.parse(causesEl.getAttribute('data-causes') as string) as GateCause[])
            .map((x) => [x.n, x.key]);
      expect(published).toEqual(c.causes);

      expectGateCopy(c.noReadingRows);
    });
  }

  it('suppresses the clause entirely where the horizon does not gate on volatility', () => {
    // Intraday has no IV gate, so an unreadable row costs nothing and the
    // trailing sentence must not appear at all -- there is no sub-verdict to
    // reconcile, and claiming one would be the same defect in reverse.
    setupHorizon([noIvCandidate('AAA')], 'Intraday (0-2d)');
    render(<Step5Page />);
    expect(partsOf().head.textContent).toBe('1 shown — 1 PASS, 0 CAUTION, 0 REJECT.');
    // ZERO, and this call is now meaningful rather than vacuous. Under the old
    // contract a clause-less banner hit `if (tail === '') return;` and asserted
    // nothing -- while a clause-less banner WITH a "Driven by:" tail failed R3
    // outright, because R3 demanded asserts === ['CAUTION'] unconditionally.
    // It also proves the ABSENCE structurally now: no missing-reading part at
    // all, not merely a phrase the banner happens not to contain.
    expectGateCopy(0);
  });
});


describe('the event window sentence states the boundary it is actually graded on', () => {
  /* WITHOUT THESE THE PIN IN PART_PINS IS A LITERAL PIN WEARING A HAT, and it
   * was measured as one: the pin builds its expectation with the SAME builder
   * the page renders with, so swapping the two numbers inside
   * `eventWindowSentence` -- the page then saying "< 45d -> REJECT; < 21d ->
   * CAUTION" over a gate that does the opposite -- shipped 54/54 GREEN, and so
   * did replacing both with hardcoded `21d`/`45d`, which is wrong on every
   * horizon but Swing. Expectation and actual moved together. Same trap, and
   * same answer, as the clause builder below: pin the skeleton literally once,
   * then prove the numbers come from the argument. */

  it('renders the agreed skeleton, word for word', () => {
    expect(eventWindowSentence({ reject_days: 21, caution_days: 45 }))
      .toBe('Earnings < 21d \u2192 REJECT; < 45d \u2192 CAUTION; else \u2192 PASS.');
  });

  it('takes BOTH numbers from its argument \u2014 neither is baked in', () => {
    // Position's real window. A builder hardcoding Swing's 21/45 passes the
    // test above and fails this one, which is the whole point of having two.
    expect(eventWindowSentence({ reject_days: 30, caution_days: 60 }))
      .toBe('Earnings < 30d \u2192 REJECT; < 60d \u2192 CAUTION; else \u2192 PASS.');
  });

  it('says what the gate does at the edge \u2014 the day named is NOT in the band', () => {
    /* The sentence's `<` is a claim about day 21 specifically, and it is the
     * claim the old "within 21 days" wording got backwards. Asserted here
     * against the gate's own arithmetic so the wording and the grading cannot
     * be changed apart: page.tsx grades `days < reject_days`, backend
     * stock_scorer.py's _rule_event grades `worst_days < ec["reject_days"]`,
     * and the row tooltip words it `reject <21d`. */
    const w = { reject_days: 21, caution_days: 45 };
    expect(eventWindowSentence(w)).toContain(`< ${w.reject_days}d`);
    expect(eventWindowSentence(w)).not.toContain(`within ${w.reject_days}`);
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

  it('changes NOTHING but the count and its verb as n grows', () => {
    /* ROUND 3 FOUND THE WALL AND ROUND 4 FOUND THE PATCH FOR IT WAS ALSO A
     * WALL. Originally n=1 was pinned with the production claim and n=2 with an
     * absurd one, so nothing pinned the production instantiation for n >= 2 and
     * a conditional swapping asserted/denied at n >= 3 shipped 43/43 green. The
     * patch was a second exact-string pin at n=3 -- which merely moved the wall
     * to n >= 4, and n >= 4 is this app's REAL case: page.tsx's own comments
     * describe "3 of 12" and "11 unreadable rows".
     *
     * A PROPERTY, NOT ANOTHER SAMPLE, so there is no n left to hide behind: the
     * output at every n must be the n=1 output with only the leading count and
     * its verb substituted. Run over two unrelated claims, so it pins the
     * builder's SHAPE and not any particular claim's words. */
    const stripCount = (x: string) => x.replace(/^\d+ of them (has|have) /, '');

    for (const claim of [
      { side: 'volatility', asserted: 'CAUTION', denied: 'PASS',    combination: 'worse'  },
      { side: 'event',      asserted: 'REJECT',  denied: 'CAUTION', combination: 'better' },
    ] as MissingReadingClaim[]) {
      const reference = stripCount(missingReadingClause(1, claim));
      // The strip really fired; otherwise every comparison below is vacuous.
      expect(reference).not.toBe(missingReadingClause(1, claim));

      for (const n of [1, 2, 3, 4, 5, 11, 12, 99]) {
        const rendered = missingReadingClause(n, claim);
        expect(rendered.startsWith(`${n} of them ${n === 1 ? 'has' : 'have'} `)).toBe(true);
        expect(stripCount(rendered)).toBe(reference);
      }
    }
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
  it('uses the INJECTED thresholds, not the shipped values', () => {
    // ROUND 2 FINDING: setupHorizon's values were byte-identical to the store's
    // then-hardcoded fallback (deleted by DOCC-3), so a reader that ignored the
    // store could not be told apart. Proven at the time: making getIvPassMax /
    // getIvCautionMax read the constant left all 38 step-5 tests green. These
    // thresholds are deliberately NOT the shipped values.
    setupHorizon([rankCandidate('AAA', 25)], 'Swing (5-15d)');
    useIvThresholdsStore.setState({
      thresholds: {
        Intraday: { rank_pass_max: null, rank_caution_max: null, abs_pass_max: null, abs_caution_max: null },
        Swing:    { rank_pass_max: 20, rank_caution_max: 30, abs_pass_max: 20, abs_caution_max: 30 },
        Position: { rank_pass_max: 44, rank_caution_max: 65, abs_pass_max: 44, abs_caution_max: 65 },
      },
      status: 'ready',
    });
    render(<Step5Page />);
    // rank 25 is PASS under the shipped values (<=34) and CAUTION under the injected
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


describe('every field of the claim is answerable to the page, not to a constant', () => {
  /* WHY THIS DESCRIBE EXISTS, AND IT IS MEASURED. Until the claim became
   * structure, this file held EXPECTED_CLAIM -- a second hand-written copy of
   * page.tsx's call site, documented "Derived, not copied" and copied. Round 3
   * measured what that bought for `asserted`/`denied`: swapping them in BOTH
   * places, the "just fix the constant to match" move, shipped 43/43 green and
   * rendered "graded PASS on the volatility side alone, never CAUTION there" --
   * verbatim the first entry in page.tsx's own list of measured past failures.
   * Round 4 measured the same for `side` and for `combination`, 45/45 green
   * each, after a head cross-check had been added for the first two.
   *
   * THERE IS NO COPY HERE ANY MORE. Each test reads the claim OFF THE DOM and
   * checks one field against something the page renders under a fixture built
   * to discriminate that field. The hand-written literals below are fixture
   * inputs and expected PAGE behaviour, never the claim.
   *
   * AND EVERY ONE RUNS AT PRODUCTION n. Round 1 of the structural loop found
   * these ties all used a single unreadable row while the n-wall was pinned
   * only on the BUILDER -- so a claim that told the truth at n<3 and lied above
   * it shipped 51/51 GREEN, rendering, at n=12:
   *   "12 shown - 0 PASS, 12 CAUTION, 0 REJECT. 12 of them have no volatility
   *    reading at all - graded PASS on the event side alone, never CAUTION
   *    there. The gate verdict above is the better of that and the event
   *    window, so it can be higher still."
   * which is THREE of the four failures page.tsx's header lists as already
   * shipped, in one sentence, under a head that says 0 PASS. n=25 is in the set
   * because the same round measured the clause being dropped entirely above 20
   * rows -- also 51/51 green -- and >20 unreadable is this app's ordinary
   * shape, not its edge case. */
  const PRODUCTION_N = [1, 4, 12, 25];

  /** n rows with no volatility reading and no event at all, on a horizon that
   *  DOES gate on volatility -- so the event side cannot be what graded them.
   *  Returns the claim the page made, having checked it is about these n rows. */
  function unreadableRowsNoEvent(n: number): MissingReadingClaim {
    setupHorizon(Array.from({ length: n }, (_, i) => noIvCandidate(`U${i}`)), 'Swing (5-15d)');
    render(<Step5Page />);
    const claimed = claimOf();
    expect(claimed).not.toBeNull();
    expect(claimed!.rows).toBe(n);
    return claimed!.claim;
  }

  describe.each(PRODUCTION_N)('at n = %i unreadable rows', (n) => {
    it('names the SIDE that actually graded the rows, and only that side', () => {
      const claim = unreadableRowsNoEvent(n);
      // The fixture discriminates: the two sides really do disagree here, so
      // `graded` below cannot come out holding both of them.
      expect(sideVerdict('U0', 'volatility')).not.toBe(sideVerdict('U0', 'event'));
      // ENUMERATED over both sides rather than asserted on the named one, so
      // naming the wrong side fails instead of merely going unchecked.
      const graded = SIDES.filter((side) => sideVerdict('U0', side) === claim.asserted);
      expect(graded).toEqual([claim.side]);
    });

    it('ASSERTS the verdict that side gives, and the head counts every row under it', () => {
      const claim = unreadableRowsNoEvent(n);
      // EVERY row, not just the first -- a claim true of one row and false of
      // the other n-1 would otherwise pass.
      for (let i = 0; i < n; i += 1) {
        expect(sideVerdict(`U${i}`, claim.side)).toBe(claim.asserted);
      }
      /* AND THE HEAD AGREES. The event side is PASS here, so each gate verdict
       * IS that row's volatility sub-verdict and the head must count all n
       * under the claim's asserted verdict -- which ties the field to numbers
       * the user can see, not only to attributes beside them. */
      const head = partsOf().head.textContent ?? '';
      const countOf = (verdict: string) =>
        Number(new RegExp(`(\\d+) ${verdict}\\b`).exec(head)?.[1] ?? NaN);
      expect(countOf(claim.asserted)).toBe(n);
      expect(countOf(claim.denied)).toBe(0);
    });

    it('DENIES the verdict the same rows get where volatility does not gate', () => {
      /* THE ROUND-4 HOLE, CLOSED. The head cross-check above pins `denied` only
       * to "a verdict these rows did not get", and there are two of those -- so
       * changing denied PASS -> REJECT shipped green.
       *
       * `denied` is not "some other verdict". It is the OTHER ARM of the single
       * ternary that grades an unreadable row, `gateDisabled ? 'PASS' :
       * 'CAUTION'`. So render the SAME candidates on Intraday, where the
       * horizon does not gate on volatility, and read that arm off the page
       * instead of off a constant. */
      const claim = unreadableRowsNoEvent(n);
      cleanup();   // or both renders are in the document and rowOf takes the first

      setupHorizon(
        Array.from({ length: n }, (_, i) => noIvCandidate(`U${i}`)),
        'Intraday (0-2d)',
      );
      render(<Step5Page />);
      for (let i = 0; i < n; i += 1) {
        expect(sideVerdict(`U${i}`, claim.side)).toBe(claim.denied);
      }
      // ...and the clause is suppressed there, so the page never asserts, on
      // the horizon where it is true, the verdict it denies where it renders.
      expect(claimOf()).toBeNull();
    });

    it('COMBINES the two sides the way the rendered gate actually combines them', () => {
      /* Round 4: swapping `combination` in page.tsx and in the test's copy of
       * the claim shipped 45/45 green, because nothing ever compared the field
       * to a gate. It does now, on the only kind of fixture where `worse` and
       * `better` predict DIFFERENT gates -- one where the two sides disagree.
       * Unreadable (volatility CAUTION) plus an event 3 days out, inside
       * Swing's reject window of 21 (event REJECT):
       *   worse -> REJECT,  better -> CAUTION. */
      setupHorizon(
        Array.from({ length: n }, (_, i) => noIvCandidate(`U${i}`, { nextEventDays: 3 })),
        'Swing (5-15d)',
      );
      render(<Step5Page />);
      const claimed = claimOf();
      expect(claimed).not.toBeNull();
      expect(claimed!.rows).toBe(n);

      const vol = sideVerdict('U0', 'volatility');
      const ev  = sideVerdict('U0', 'event');
      expect(vol).not.toBe(ev);                     // the fixture discriminates

      const worse  = worstStatus(vol, ev);
      const better = worse === vol ? ev : vol;      // defined because the two differ
      // No `expect(worse).not.toBe(better)` -- it FOLLOWS from `vol !== ev` two
      // lines above and so could never fail on its own. That line is the real
      // guard that the two predictions differ; this one was a tautology.
      expect(gateOf('U0')).toBe(claimed!.claim.combination === 'worse' ? worse : better);
    });
  });

  it('makes the SAME claim about every scan, whatever the rows look like', () => {
    /* The ties above each use a purpose-built fixture. Nothing in them stops
     * the page emitting a claim that happens to fit each fixture and differs
     * between them -- which would be a per-scan opinion, not the fixed
     * statement about how this gate works that the sentence presents itself as.
     * Byte-identical across six unrelated shapes, spanning n from 1 to 25, with
     * and without a causes sentence beside it. */
    const shapes: Array<[string, () => TradeCardData[], string]> = [
      ['one unreadable row, nothing else',
        () => [noIvCandidate('AAA')], 'Swing (5-15d)'],
      ['unreadable rows REJECTed by events',
        () => [noIvCandidate('AAA', { nextEventDays: 3 }), noIvCandidate('BBB', { nextEventDays: 3 })],
        'Swing (5-15d)'],
      ['unreadable beside readable, Position',
        () => [rankCandidate('AAA', 50), noIvCandidate('BBB', { nextEventDays: 25 })],
        'Position (1-3m)'],
      ['four unreadable',
        () => Array.from({ length: 4 }, (_, i) => noIvCandidate(`U${i}`)), 'Swing (5-15d)'],
      ['twelve unreadable beside five event-driven',
        () => [
          ...Array.from({ length: 12 }, (_, i) => noIvCandidate(`U${i}`)),
          ...Array.from({ length: 5 }, (_, i) => rankCandidate(`E${i}`, 10, { nextEventDays: 3 })),
        ], 'Swing (5-15d)'],
      ['twenty-five unreadable, past every fixture this file used to hold',
        () => Array.from({ length: 25 }, (_, i) => noIvCandidate(`U${i}`)), 'Swing (5-15d)'],
    ];

    const seen: Array<[string, MissingReadingClaim]> = [];
    for (const [name, candidates, horizon] of shapes) {
      cleanup();
      setupHorizon(candidates(), horizon);
      render(<Step5Page />);
      const claimed = claimOf();
      // PRESENT AT ALL, at every one of these sizes. Round 1 measured the
      // clause being dropped above 20 rows at 51/51 green, because 12 was the
      // largest fixture in the file.
      expect([name, claimed !== null]).toEqual([name, true]);
      seen.push([name, claimed!.claim]);
    }

    // Named in the comparison so a failure says WHICH shape drifted.
    for (const [name, claim] of seen.slice(1)) {
      expect([name, claim]).toEqual([name, seen[0][1]]);
    }
  });
});

describe('the banner speaks a closed vocabulary, pinned whole', () => {
  /* The per-part pins in PART_PINS compare each sentence with its own builder
   * run over its own published data, which means a gloss appended INSIDE a
   * builder would move expectation and actual together. These are the literal
   * pins that stop that -- the same role the clause skeleton's exact-string
   * test plays, for the two sentences that gained builders in this round. */

  it('pins every cause phrase the banner can say', () => {
    // A new phrase has to be a new entry, and free text appended to an existing
    // one fails here. Round 1 measured the alternative: with the causes
    // sentence held to a punctuation rule, "; these rows are safe to trade as
    // if they were clean." shipped 51/51 green.
    expect(CAUSE_LABEL).toEqual({
      ivRank: 'on IV rank above its threshold',
      ivAbs:  'on IV above its threshold',
      event:  "on an event inside this horizon's window",
    });
  });

  it('renders the head sentence, word for word', () => {
    expect(headSentence({ total: 12, pass: 3, caution: 4, reject: 5 }))
      .toBe('12 shown \u2014 3 PASS, 4 CAUTION, 5 REJECT.');
  });

  it('renders the causes sentence, word for word, with and without the overlap cue', () => {
    expect(causesSentence([{ n: 3, key: 'ivRank' }, { n: 1, key: 'event' }], false))
      .toBe("Driven by measured checks: 3 on IV rank above its threshold; 1 on an event inside this horizon's window.");
    expect(causesSentence([{ n: 2, key: 'ivAbs' }], true))
      .toBe('Driven by measured checks (a row can have more than one): 2 on IV above its threshold.');
  });
});

const MISSING_READING_SENTENCE =
  '1 of them has no volatility reading at all — graded CAUTION on the volatility side alone, '
  + 'never PASS there. The gate verdict above is the worse of that and the event window, '
  + 'so it can be lower still.';

function rowTooltip(symbol: string): string {
  const text = document.querySelector(`[data-row="${symbol}"] [role="tooltip"]`)?.textContent;
  if (text == null) throw new Error(`no tooltip for ${symbol}`);
  return text;
}

describe('measured checks are not a missing volatility reading', () => {
  it('CAUTION, no IV, event inside the caution window names only the event', () => {
    setup([noIvCandidate('PROV', { nextEventDays: 30 })]);
    render(<Step5Page />);
    const causes = banner().querySelector('[data-part="causes"]');
    expect(causes?.getAttribute('data-causes')).toBe(JSON.stringify([{ n: 1, key: 'event' }]));
    expect(causes?.textContent).toBe(
      "Driven by measured checks: 1 on an event inside this horizon's window.",
    );
    expect(banner().textContent).toContain(MISSING_READING_SENTENCE);
    const tip = rowTooltip('PROV');
    expect(tip).toContain(
      'Driven by: measured checks: event proximity. Missing volatility reading is not a measured driver.',
    );
    expect(tip).not.toContain('Driven by: no volatility reading and event proximity');
  });

  it('REJECT on the event, no IV, names event proximity and discloses the gap', () => {
    setup([noIvCandidate('EVREJ', { nextEventDays: 3 })]);
    render(<Step5Page />);
    const causes = banner().querySelector('[data-part="causes"]');
    expect(causes?.getAttribute('data-causes')).toBe(JSON.stringify([{ n: 1, key: 'event' }]));
    expect(causes?.textContent).toBe(
      "Driven by measured checks: 1 on an event inside this horizon's window.",
    );
    expect(banner().textContent).toContain(MISSING_READING_SENTENCE);
    const tip = rowTooltip('EVREJ');
    expect(tip).toContain(
      'Driven by: measured checks: event proximity. Missing volatility reading is not a measured driver.',
    );
    expect(tip).not.toContain('no volatility reading and event proximity');
    expect(tip).not.toContain('measured checks: no volatility reading');
  });

  it('CAUTION from a missing reading only has no measured-cause sentence', () => {
    setup([noIvCandidate('ONLY')]);
    render(<Step5Page />);
    expect(banner().querySelector('[data-part="causes"]')).toBeNull();
    expect(banner().textContent ?? '').not.toContain('Driven by');
    expect(banner().textContent).toContain(MISSING_READING_SENTENCE);
    expect(rowTooltip('ONLY')).toContain(
      'Driven by: no measured check. Missing volatility reading is not a measured driver.',
    );
  });
});
