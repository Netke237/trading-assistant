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
    expect(screen.getByText(/no volatility reading/)).toBeInTheDocument();
    expect(screen.getByText(/a missing reading is not a passing one/)).toBeInTheDocument();
  });

  it('does NOT blame a missing reading when the reading exists and failed its threshold', () => {
    // ivRank 45 is a real reading, above Swing's PASS max of 34 -> CAUTION on IV.
    setup([makeCandidate('AAA', {
      contractDetails: { strike: 100, expiry: '2026-12-01', right: 'C', mid: 1, delta: 0.45, theta: -0.05, ivRank: 45, ivPercentile: 45, dte: 90 } as any,
    })]);
    render(<Step5Page />);
    expect(screen.getByText(/above its threshold/)).toBeInTheDocument();
    expect(screen.queryByText(/no volatility reading/)).not.toBeInTheDocument();
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
