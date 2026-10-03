import { render, screen } from '@testing-library/react';
import Step5Page from '../page';
import { useScanStore } from '@/lib/scanStore';
import { useIvThresholdsStore } from '@/lib/ivThresholdsStore';
import {
  useEventThresholdsStore, type HorizonEventThresholds, type ThresholdHorizon,
} from '@/lib/eventThresholdsStore';
import type { TradeCardData } from '@/types/domain';
import { api } from '@/lib/api';
import { EVENT_SHIPPED, IV_SHIPPED, echoStoredThresholds } from '@/lib/testFixtures/thresholds';
import { expectPageCopy } from '../testSupport/pageContract';

// DOCC-3: the page fetches both stores on mount; each fetch answers with the
// record the test set, so it re-sets the test's values rather than clearing them.
jest.mock('@/lib/api', () => ({ api: { getIvThresholds: jest.fn(), getEventThresholds: jest.fn() } }));
beforeEach(() => echoStoredThresholds(api as unknown as Parameters<typeof echoStoredThresholds>[0]));

function makeCandidate(overrides: Partial<TradeCardData> = {}): TradeCardData {
  return {
    symbol: 'TST',
    company: 'Test Co',
    price: 100,
    direction: 'Bullish',
    status: 'PASS',
    stockScore: 70,
    stockConfidence: 'PASS',
    stockBreakdown: {} as any,
    nextEventDays: null,
    nextEventLabel: null,
    contract: 'TST|100|2026-12-01|C',
    contractScore: 70,
    contractConfidence: 'PASS',
    contractBreakdown: {} as any,
    contractDetails: { strike: 100, expiry: '2026-12-01', right: 'C', mid: 1, delta: 0.45, theta: -0.05, ivRank: 10, ivPercentile: 10, dte: 90 },
    entry: {} as any,
    exit: {} as any,
    ...overrides,
  } as TradeCardData;
}

function setup(
  nextEventDays: number,
  horizon: string,
  // Horizons not given keep the shipped window: a partial record would be
  // refused by the store's parser on the mount fetch (DOCC-3).
  thresholds: Partial<Record<ThresholdHorizon, HorizonEventThresholds>> = EVENT_SHIPPED,
  eventWindow?: { reject_days: number; caution_days: number },
  scanOverrides: Record<string, unknown> = {},
) {
  useScanStore.setState({
    scanResult: {
      candidates: [makeCandidate({ nextEventDays })], rejected: [], scan_id: 'x', timestamp: '',
      ...(eventWindow ? { event_window: eventWindow } : {}),
    } as any,
    context: { direction: 'Bullish', horizon } as any,
    // Always set, so state from one test cannot leak into the next.
    scanOverrides,
  } as any);
  useIvThresholdsStore.setState({ thresholds: IV_SHIPPED, status: 'ready', error: null, overrides: {} });
  useEventThresholdsStore.setState({
    thresholds: { ...EVENT_SHIPPED, ...thresholds }, status: 'ready', error: null,
  });
}

describe('Step 5 Volatility+Events — event proximity gate follows the scan horizon', () => {
  // The scan echoes the window its scorer applied (a Step-3 override such as the
  // SemiAnnual_* profiles' 7/30 replaces the YAML window), and the gate must use
  // THAT: otherwise earnings 15 days out passes the scan and is re-REJECTED here.
  it('uses the window the scan applied: 7/30 makes an event 15 days out CAUTION, not REJECT', () => {
    setup(15, 'Position (90-105d)', EVENT_SHIPPED, { reject_days: 7, caution_days: 30 });
    render(<Step5Page />);
    expect(screen.getByText('CAUTION')).toBeInTheDocument();
    expect(screen.queryByText('REJECT')).not.toBeInTheDocument();
    // ...and the header's event-window sentence quotes that same echoed window.
    expectPageCopy();
  });

  it('uses the window the scan applied: 7/30 still REJECTS an event 5 days out', () => {
    setup(5, 'Position (90-105d)', EVENT_SHIPPED, { reject_days: 7, caution_days: 30 });
    render(<Step5Page />);
    expect(screen.getByText('REJECT')).toBeInTheDocument();
  });

  it('ignores live Step-3 overrides edited after the scan (the result was scored at 30/60)', () => {
    setup(10, 'Position (90-105d)', EVENT_SHIPPED, { reject_days: 30, caution_days: 60 },
          { event_reject_days: 7, event_caution_days: 30 });
    render(<Step5Page />);
    expect(screen.getByText('REJECT')).toBeInTheDocument();
  });

  it('needs no live Step-3 overrides: the window comes from the result alone', () => {
    setup(15, 'Position (90-105d)', EVENT_SHIPPED, { reject_days: 7, caution_days: 30 }, {});
    render(<Step5Page />);
    expect(screen.getByText('CAUTION')).toBeInTheDocument();
  });

  it('Position horizon: an event 8 days out is well inside the 30-day REJECT window, not a PASS', () => {
    setup(8, 'Position (90-105d)');
    render(<Step5Page />);
    expect(screen.getByText('REJECT')).toBeInTheDocument();
  });

  it('Position horizon: an event 45 days out is inside the 60-day CAUTION window but outside the 30-day REJECT window', () => {
    setup(45, 'Position (90-105d)');
    render(<Step5Page />);
    expect(screen.getByText('CAUTION')).toBeInTheDocument();
  });

  it('Position horizon: an event 78 days out is outside both windows -> PASS', () => {
    setup(78, 'Position (90-105d)');
    render(<Step5Page />);
    expect(screen.getByText('PASS')).toBeInTheDocument();
  });

  it("Swing horizon: an event 8 days out is well inside the 21-day REJECT window, not a CAUTION", () => {
    // Regression test for the Step 5 gate silently using a looser (7d reject / 21d
    // caution) window than the one score_stock() actually applied when it scored
    // this candidate (21d reject / 45d caution, from scoring_rules.yaml). Both
    // numbers now come from the same backend endpoint (/api/config/event-thresholds),
    // so this can no longer drift out of sync.
    setup(8, 'Swing (5-15d)');
    render(<Step5Page />);
    expect(screen.getByText('REJECT')).toBeInTheDocument();
  });

  it('Swing horizon: an event 30 days out is inside the 45-day CAUTION window but outside the 21-day REJECT window', () => {
    setup(30, 'Swing (5-15d)');
    render(<Step5Page />);
    expect(screen.getByText('CAUTION')).toBeInTheDocument();
  });

  it('Swing horizon: an event 50 days out is outside both windows -> PASS', () => {
    setup(50, 'Swing (5-15d)');
    render(<Step5Page />);
    expect(screen.getByText('PASS')).toBeInTheDocument();
  });

  it('Intraday horizon: an event 0 days out is inside the 1-day REJECT window', () => {
    setup(0, 'Intraday (0-2d)');
    render(<Step5Page />);
    expect(screen.getByText('REJECT')).toBeInTheDocument();
  });

  it('Intraday horizon: an event 2 days out is inside the 3-day CAUTION window but outside the 1-day REJECT window', () => {
    setup(2, 'Intraday (0-2d)');
    render(<Step5Page />);
    expect(screen.getByText('CAUTION')).toBeInTheDocument();
  });

  it('Intraday horizon: an event 5 days out is outside both windows -> PASS', () => {
    setup(5, 'Intraday (0-2d)');
    render(<Step5Page />);
    expect(screen.getByText('PASS')).toBeInTheDocument();
  });

  // Boundary semantics: backend stock_scorer.py's _rule_event uses strict `<`
  // (worst_days < reject_days / < caution_days), so an event landing exactly on
  // the boundary day is graded by the LOOSER band, not the stricter one.
  it('Swing horizon: an event exactly 21 days out (== reject_days) is CAUTION, not REJECT', () => {
    setup(21, 'Swing (5-15d)');
    render(<Step5Page />);
    expect(screen.getByText('CAUTION')).toBeInTheDocument();
  });

  it('Swing horizon: an event exactly 45 days out (== caution_days) is PASS, not CAUTION', () => {
    setup(45, 'Swing (5-15d)');
    render(<Step5Page />);
    expect(screen.getByText('PASS')).toBeInTheDocument();
  });

  it('gate reacts to live-fetched thresholds, not just the shipped values', () => {
    // A regression here (e.g. the page silently ignoring useEventThresholdsStore
    // and reading a local constant instead) would still pass every test above,
    // since they all seed the store with the shipped values. Seeding a
    // deliberately different window and asserting the gate follows it is what
    // actually proves the store is wired in, not just present.
    setup(7, 'Swing (5-15d)', { Swing: { reject_days: 5, caution_days: 10 } });
    render(<Step5Page />);
    // Under the shipped window (21/45) day 7 would be REJECT; under this seeded window it's CAUTION.
    expect(screen.getByText('CAUTION')).toBeInTheDocument();
    expect(screen.queryByText('REJECT')).not.toBeInTheDocument();
  });
});

/* Audit round 1, F9 — Step 5 grades the NEARER of earnings and dividend, so a
 * dividend inside the window paints REJECT here while Step 7 (D3: only earnings
 * veto) lets it send. The row must say a dividend is not a send veto. */
describe('audit round 1 F9 — a dividend-only REJECT says it is not a send veto', () => {
  const NOTE = /Dividend — score penalty, not a send veto/;

  function setupRow(over: Partial<TradeCardData>) {
    setup(5, 'Swing (5-15d)');
    useScanStore.setState((s: any) => ({
      scanResult: { ...s.scanResult, candidates: [makeCandidate({ nextEventDays: 5, ...over })] },
    }));
  }

  it('dividend 5d out, earnings 90d out: REJECT, with the note', () => {
    setupRow({ nextEventLabel: 'Dividend', earningsDays: 90 });
    render(<Step5Page />);
    expect(screen.getByText('REJECT')).toBeInTheDocument();
    expect(screen.getByText(NOTE)).toBeInTheDocument();
  });

  it('dividend 5d out with no earnings date: still the note (the dividend is what rejected it)', () => {
    setupRow({ nextEventLabel: 'Dividend', earningsDays: null });
    render(<Step5Page />);
    expect(screen.getByText(NOTE)).toBeInTheDocument();
  });

  it('earnings 5d out: no note — that one IS a veto', () => {
    setupRow({ nextEventLabel: 'Earnings', earningsDays: 5 });
    render(<Step5Page />);
    expect(screen.getByText('REJECT')).toBeInTheDocument();
    expect(screen.queryByText(NOTE)).not.toBeInTheDocument();
  });

  it('dividend 5d out but earnings 10d out (also inside the 21d window): no note', () => {
    setupRow({ nextEventLabel: 'Dividend', earningsDays: 10 });
    render(<Step5Page />);
    expect(screen.queryByText(NOTE)).not.toBeInTheDocument();
  });
});
