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
import Step5Page from '../page';
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
  useIvThresholdsStore.setState({
    thresholds: { swing: { iv_rank_pass_max: 34, iv_rank_caution_max: 55 } },
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
  // setup() writes three global Zustand stores; without this the file leaks its
  // state into whatever else runs in the same jest worker.
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
    expect(banner().textContent).toMatch(/with no volatility reading/);
    expect(banner().textContent).toMatch(/a missing reading is not a passing one/);
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
    expect(summary.textContent).toMatch(/1 with no volatility reading/);
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
    expect(t).toMatch(/2 with no volatility reading/);
    expect(t).toMatch(/2 on an event inside this horizon's window/);
    expect(t).not.toMatch(/on both/);
  });

  it('leads with the most common cause, not the first one in the source', () => {
    // The old code pushed causes in a fixed order under a comment claiming it
    // sorted them, so one missing reading led a list of thirty event rejects.
    const rows = [noIvCandidate('AAA')];
    for (let i = 0; i < 4; i++) {
      rows.push(makeCandidate(`EV${i}`, { nextEventDays: 30 }));  // event-driven only
    }
    setup(rows);
    render(<Step5Page />);
    const t = banner().textContent ?? '';
    const evAt = t.indexOf('on an event');
    const noIvAt = t.indexOf('with no volatility reading');
    expect(evAt).toBeGreaterThanOrEqual(0);
    expect(noIvAt).toBeGreaterThanOrEqual(0);
    expect(evAt).toBeLessThan(noIvAt);   // 4 events outrank 1 missing reading
  });

  it('distinguishes a rank failure from an absolute-IV failure', () => {
    // Guards the split at its own wording: the previous assertion was
    // /above its threshold/, which matches both branches identically, so
    // swapping the two counts would not have failed a test.
    setup([
      makeCandidate('RNK', {
        contractDetails: { strike: 100, expiry: '2026-12-01', right: 'C', mid: 1, delta: 0.45, theta: -0.05, ivRank: 45, ivPercentile: 45, dte: 90 } as any,
      }),
      makeCandidate('ABS', {
        contractDetails: { strike: 100, expiry: '2026-12-01', right: 'C', mid: 1, delta: 0.45, theta: -0.05, iv: 48, dte: 90 } as any,
      }),
    ]);
    render(<Step5Page />);
    const t = banner().textContent ?? '';
    expect(t).toMatch(/1 on IV rank above its threshold/);
    expect(t).toMatch(/1 on IV above its threshold/);
  });
});
