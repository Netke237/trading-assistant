import { render, screen } from '@testing-library/react';
import Step5Page from '../page';
import { useScanStore } from '@/lib/scanStore';
import { useIvThresholdsStore } from '@/lib/ivThresholdsStore';
import { useEventThresholdsStore } from '@/lib/eventThresholdsStore';
import type { TradeCardData } from '@/types/domain';
import { api } from '@/lib/api';
import { EVENT_SHIPPED, IV_SHIPPED, echoStoredThresholds } from '@/lib/testFixtures/thresholds';

// DOCC-3: the page fetches both stores on mount; each fetch answers with the
// record the test set, so it re-sets the test's values rather than clearing them.
jest.mock('@/lib/api', () => ({ api: { getIvThresholds: jest.fn(), getEventThresholds: jest.fn() } }));
beforeEach(() => echoStoredThresholds(api as unknown as Parameters<typeof echoStoredThresholds>[0]));

/**
 * Round 2 finding 4. The IV PCTL cell guarded on `pctl != null && pctl > 0`,
 * so a genuine percentile of 0 printed as "—".
 *
 * The asymmetry Phase A is built on (stated in lib/ivBasis.ts, pinned in its
 * tests, and matched by augment.py and scan.py) is that a PERCENTILE of 0 is a
 * REAL reading — the bottom of this name's own 52-week range, the cheapest its
 * premium gets — while only an ABSOLUTE IV treats 0 as a missing-data sentinel.
 * `ivPercentile` is a percentile in every case, so it never gets the sentinel
 * treatment. The `> 0` guard dated from when a pre-split ivPercentile defaulted
 * to the literal 0 meaning "no rank source answered"; market.py writes null for
 * that now.
 */

function candidateWithPercentile(ivPercentile: number | null): TradeCardData {
  return {
    symbol: 'TST', company: 'Test Co', price: 100, direction: 'Bullish',
    status: 'PASS', stockScore: 70, stockConfidence: 'PASS', stockBreakdown: {} as any,
    // An event far outside both windows, so the NEXT EVENT cell renders a day
    // count rather than its own dash — leaving the IV PCTL cell as the only
    // place a dash can come from.
    nextEventDays: 60, nextEventLabel: 'Earnings',
    contract: 'TST|100|2026-12-01|C', contractScore: 70, contractConfidence: 'PASS',
    contractBreakdown: {} as any,
    contractDetails: {
      strike: 100, expiry: '2026-12-01', right: 'C', mid: 1, delta: 0.45,
      // A rank source answered (this is the only way a percentile exists at
      // all), and it is NOT 0 — so the "0" these tests look for can only be the
      // percentile cell, never the IV cell.
      theta: -0.05, ivRank: 5, ivPercentile, dte: 90,
    },
    entry: {} as any, exit: {} as any,
  } as TradeCardData;
}

function render5(ivPercentile: number | null) {
  useScanStore.setState({
    scanResult: { candidates: [candidateWithPercentile(ivPercentile)], rejected: [], scan_id: 'x', timestamp: '' } as any,
    context: { direction: 'Bullish', horizon: 'Swing (21-45d)' } as any,
  } as any);
  useIvThresholdsStore.setState({ thresholds: IV_SHIPPED, status: 'ready', error: null, overrides: {} });
  useEventThresholdsStore.setState({ thresholds: EVENT_SHIPPED, status: 'ready', error: null });
  render(<Step5Page />);
}

describe('Step 5 — an IV percentile of 0 is a reading, not missing data', () => {
  it('prints 0 rather than the no-data dash', () => {
    render5(0);
    expect(screen.getByText('0')).toBeInTheDocument();
    // The dash would mean "no rank source answered", which is a different and
    // materially worse claim: it hides the cheapest premium this name offers.
    expect(screen.queryByText('—')).not.toBeInTheDocument();
  });

  it('still prints the dash when the percentile is genuinely absent', () => {
    render5(null);
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('does not confuse the two cells: the IV figure keeps its own value', () => {
    // step-6-contracts already guarded on null alone, so the two pages now
    // agree about this field. Guards against a "fix" that simply printed the
    // IV figure in both columns.
    render5(0);
    expect(screen.getByText('5')).toBeInTheDocument();   // IV rank cell
    expect(screen.getByText('0')).toBeInTheDocument();   // IV PCTL cell
  });
});
