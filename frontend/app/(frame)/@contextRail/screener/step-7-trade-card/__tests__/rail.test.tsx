import '@testing-library/jest-dom';
import { render, screen, act } from '@testing-library/react';
import TradeCardContextRail from '../page';
import { useScanStore } from '@/lib/scanStore';
import { useTradeCardUiStore } from '@/lib/tradeCardUiStore';
import { useIvThresholdsStore } from '@/lib/ivThresholdsStore';
import { api } from '@/lib/api';
import { IV_SHIPPED, echoStoredThresholds } from '@/lib/testFixtures/thresholds';
import type { TradeCardData } from '@/types/domain';

// DOCC-3: the rail fetches the IV store on mount; the fetch answers with the
// record the test set, so it re-sets the test's values rather than clearing them.
jest.mock('@/lib/api', () => ({ api: { getIvThresholds: jest.fn(), getEventThresholds: jest.fn() } }));

// The gate and QuickLook are not under test: pass-through / stub.
jest.mock('@/components/organisms/ScreenerStepGate', () => ({
  ScreenerStepGate: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
jest.mock('@/components/organisms/ContextRail/QuickLook', () => ({ RailQuickLook: () => null }));

/*
 * A8, open_questions[64]. The rail used to grade the RAW scan candidate, so
 * after a Step-6 pick it showed the auto-picked contract's IV, score, spread
 * and R:R beside a card showing another contract. It now reads only the card
 * Step 7 publishes.
 */

function card(over: Partial<TradeCardData> = {}): TradeCardData {
  return {
    symbol: 'AAA', company: 'AAA Inc.', price: 150, direction: 'Bullish', status: 'PASS',
    stockScore: 80, stockConfidence: 'PASS',
    stockBreakdown: { trend: 80, pullback: 80, trigger: 80, event: 80, volatility: 80 },
    contract: 'AAA 150C 05/15', contractScore: 70, contractConfidence: 'PASS',
    contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 90 },
    contractDetails: { strike: 150, expiry: '2026-05-15', right: 'C', mid: 2.5, delta: 0.45, theta: -0.09, ivRank: 20, dte: 24 },
    entry: { limit: 2.5, maxFill: 2.63, orderType: 'Limit' },
    exit: { invalidation: 140, premiumStop: 1.5, timeStopDays: 10, target: 160, targets: [] },
    rrRatio: 3.0, rrModel: 'Heston repriced', finalStatus: 'PASS',
    nextEventDays: 30, earningsDays: 30,
    ...over,
  } as TradeCardData;
}

// The auto-pick, as the scan returned it: IV rank 20, score 70, spread 90, R:R 3.0.
const AUTO = card();
// The Step-6 pick, as Step 7 shows it: IV rank 77, score 58, spread 30, R:R 1.2.
const PICKED = card({
  contract: 'AAA 160C 05/15', contractScore: 58,
  contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 30 },
  contractDetails: { strike: 160, expiry: '2026-05-15', right: 'C', mid: 1.1, delta: 0.3, theta: -0.05, ivRank: 77, dte: 24 },
  rrRatio: 1.2,
});

beforeEach(() => {
  (api.getIvThresholds as jest.Mock).mockReset();
  echoStoredThresholds(api as unknown as Parameters<typeof echoStoredThresholds>[0]);
  act(() => {
    useScanStore.setState({
      scanResult: { scan_id: 's', candidates: [AUTO] } as any,
      selectedSymbol: 'AAA',
      combinedRegime: 'PASS',
      context: { universe: 'SP500', direction: 'Bullish', horizon: 'Swing (7–21d)', horizonPreset: 'Swing', holdMin: 7, holdMax: 21 } as any,
    } as any);
    useIvThresholdsStore.setState({
      thresholds: { ...IV_SHIPPED, Swing: { abs_pass_max: 40, abs_caution_max: 60, rank_pass_max: 55, rank_caution_max: 70 } },
      status: 'ready', error: null, overrides: {},
    });
    useTradeCardUiStore.setState({ activeCard: null });
  });
});

it('grades the published (picked) contract, not the scan candidate', () => {
  act(() => { useTradeCardUiStore.setState({ activeCard: { card: PICKED, rrPending: false } }); });
  render(<TradeCardContextRail />);
  // IV: the picked contract's rank 77, not the auto-pick's 20.
  expect(screen.getByText('IV rank 77 vs. pass ≤55 / caution ≤70.')).toBeInTheDocument();
  expect(screen.queryByText(/IV rank 20/)).not.toBeInTheDocument();
  // Score: the picked contract's 58.
  expect(screen.getByText(/contract score \(58\)/)).toBeInTheDocument();
  // Spread: the picked breakdown's 30.
  expect(screen.getByText(/Spread quality sub-score 30\/100/)).toBeInTheDocument();
  // R:R: the picked plan's 1.2.
  expect(screen.getByText(/reward:risk is 1\.2×/)).toBeInTheDocument();
});

it('shows no gates when nothing is published, even with a scan candidate in the store', () => {
  render(<TradeCardContextRail />);
  expect(screen.getByText('Run a scan to populate the checklist.')).toBeInTheDocument();
  expect(screen.queryByText(/IV rank/)).not.toBeInTheDocument();
});

it('cautions on R:R while the picked contract\'s plan is pending, never the stale ratio', () => {
  // rrRatio 3.0 would PASS; it is the auto-pick's and must not be shown.
  act(() => { useTradeCardUiStore.setState({ activeCard: { card: { ...PICKED, rrRatio: 3.0 }, rrPending: true } }); });
  render(<TradeCardContextRail />);
  expect(screen.getByText('R:R not yet recomputed for the contract picked in Step 6.')).toBeInTheDocument();
  expect(screen.queryByText(/reward:risk is/)).not.toBeInTheDocument();
});

/* ── DOCC-3: no thresholds in hand, and the Settings override ─────────────── */

const NOT_LOADED = 'IV thresholds could not be loaded from scoring_rules.yaml — the IV gate was not applied.';

/** The IV item's verdict, as the row publishes it. */
function ivStatus(): string | null {
  return document.querySelector('[data-gate-label="IV acceptable"]')?.getAttribute('data-status') ?? null;
}

describe('R1: with no IV record the IV item is CAUTION with the named reason, never PASS', () => {
  it.each([['Swing (7–21d)'], ['Intraday (0-2d)']])('%s', (horizon) => {
    (api.getIvThresholds as jest.Mock).mockReset().mockReturnValue(new Promise(() => {}));
    act(() => {
      useScanStore.setState({ context: { ...useScanStore.getState().context, horizon } as any } as any);
      useIvThresholdsStore.setState({ thresholds: null, status: 'failed', error: 'x' });
      useTradeCardUiStore.setState({ activeCard: { card: PICKED, rrPending: false } });
    });
    render(<TradeCardContextRail />);
    expect(screen.getByText(NOT_LOADED)).toBeInTheDocument();
    expect(ivStatus()).toBe('CAUTION');
    expect(screen.queryByText(/no IV gate for/)).not.toBeInTheDocument();
    expect(screen.queryByText(/vs\. pass/)).not.toBeInTheDocument();
  });
});

it('R2: an active override adds the suffix, and the verdict uses the override', async () => {
  // An ABSOLUTE reading (no rank), 38 -- above the YAML's 34, inside the override's 50.
  const ABS = card({
    contractDetails: { strike: 150, expiry: '2026-05-15', right: 'C', mid: 2.5, delta: 0.45, theta: -0.09, iv: 38, dte: 24 } as any,
  });
  act(() => {
    useIvThresholdsStore.setState({ thresholds: IV_SHIPPED, status: 'ready', error: null, overrides: { Swing: { abs_pass_max: 50 } } });
    useTradeCardUiStore.setState({ activeCard: { card: ABS, rrPending: false } });
  });
  render(<TradeCardContextRail />);
  expect(screen.getByText(/^IV 38(\.0)?% vs\. pass ≤50 \/ caution ≤55\. \(session override from Settings; scoring_rules\.yaml: 34\)$/))
    .toBeInTheDocument();
  // 38 is above the YAML's 34 (CAUTION there) and inside the override's 50.
  expect(ivStatus()).toBe('PASS');
});

it('R3: mounting fetches the IV thresholds', () => {
  render(<TradeCardContextRail />);
  expect(api.getIvThresholds).toHaveBeenCalledTimes(1);
});

/* ── Fix #3 (review): the earnings gate reads the SCAN's window ───────────── */

const EARNINGS_LABEL = 'Earnings outside reject window';

/** The earnings row's verdict, as the row publishes it. */
function earningsStatus(): string | null {
  return document.querySelector(`[data-gate-label="${EARNINGS_LABEL}"], [data-gate-label="Earnings date"]`)
    ?.getAttribute('data-status') ?? null;
}

function scanWith(eventWindow: { reject_days: number; caution_days: number } | undefined) {
  act(() => {
    useScanStore.setState({
      scanResult: { scan_id: 's', candidates: [AUTO], event_window: eventWindow } as any,
    } as any);
  });
}

function publish(over: Partial<TradeCardData>) {
  act(() => { useTradeCardUiStore.setState({ activeCard: { card: card(over), rrPending: false } }); });
}

describe('earnings gate uses the scan-echoed window, not a fixed 7/3 days', () => {
  it('judges earnings against the scan window (21/45): 10d is REJECT, 30d is CAUTION, 60d is PASS', () => {
    scanWith({ reject_days: 21, caution_days: 45 });

    publish({ earningsDays: 10 });
    const first = render(<TradeCardContextRail />);
    // Under the old fixed 7/3 window 10d was a PASS.
    expect(screen.getByText(EARNINGS_LABEL)).toBeInTheDocument();
    expect(screen.queryByText('Earnings > 7d away')).not.toBeInTheDocument();
    expect(earningsStatus()).toBe('REJECT');
    expect(screen.getByText("Earnings in 10d — reject <21d, caution <45d (this scan's window).")).toBeInTheDocument();
    first.unmount();

    publish({ earningsDays: 30 });
    const second = render(<TradeCardContextRail />);
    expect(earningsStatus()).toBe('CAUTION');
    expect(screen.getByText("Earnings in 30d — reject <21d, caution <45d (this scan's window).")).toBeInTheDocument();
    second.unmount();

    publish({ earningsDays: 60 });
    render(<TradeCardContextRail />);
    expect(earningsStatus()).toBe('PASS');
    expect(screen.getByText("Earnings in 60d — reject <21d, caution <45d (this scan's window).")).toBeInTheDocument();
  });

  it('shows CAUTION, naming a re-run, when the scan echoed no window', () => {
    scanWith(undefined);
    publish({ earningsDays: 30 });
    render(<TradeCardContextRail />);
    // 30d would be PASS under 7/3; with no window in hand it is never PASS.
    expect(screen.getByText(EARNINGS_LABEL)).toBeInTheDocument();
    expect(earningsStatus()).toBe('CAUTION');
    expect(screen.getByText('Earnings in 30d — this scan carried no event window; re-run the scan.')).toBeInTheDocument();
  });

  it('does not grade a nearer DIVIDEND as an Earnings gate (nextEventDays is the nearer of the two)', () => {
    scanWith({ reject_days: 21, caution_days: 45 });
    // Dividend 2d out, no earnings date: nextEventDays = 2 but earningsDays null.
    publish({ nextEventDays: 2, nextEventLabel: 'Dividend', earningsDays: null });
    render(<TradeCardContextRail />);
    expect(screen.queryByText(EARNINGS_LABEL)).not.toBeInTheDocument();
  });

  it('grades on earningsDays even when a dividend is nearer', () => {
    scanWith({ reject_days: 21, caution_days: 45 });
    publish({ nextEventDays: 2, nextEventLabel: 'Dividend', earningsDays: 10 });
    render(<TradeCardContextRail />);
    expect(earningsStatus()).toBe('REJECT');
    expect(screen.getByText("Earnings in 10d — reject <21d, caution <45d (this scan's window).")).toBeInTheDocument();
  });

  it('shows CAUTION "Earnings date" when a single stock has no known earnings date', () => {
    scanWith({ reject_days: 21, caution_days: 45 });
    publish({ earningsDays: null, earningsUnknown: true, isEtf: false });
    render(<TradeCardContextRail />);
    expect(screen.getByText('Earnings date')).toBeInTheDocument();
    expect(earningsStatus()).toBe('CAUTION');
    // D4 amended 2026-10-03: the backend caps the card at CAUTION and the
    // auto-trader refuses to fire it -- the rail says the same thing.
    expect(screen.getByText(
      'No earnings date on file — the card is capped at CAUTION and auto-trade will not fire a single stock. Check the calendar before sending.',
    )).toBeInTheDocument();
    // No days figure, so no window-based gate beside it.
    expect(screen.queryByText(EARNINGS_LABEL)).not.toBeInTheDocument();
  });

  it('treats a card without the isEtf flag (pre-deploy scan) as a single stock', () => {
    scanWith({ reject_days: 21, caution_days: 45 });
    publish({ earningsDays: null, earningsUnknown: true });
    render(<TradeCardContextRail />);
    expect(earningsStatus()).toBe('CAUTION');
  });

  it('passes the "Earnings date" gate for an ETF, which has no earnings', () => {
    scanWith({ reject_days: 21, caution_days: 45 });
    publish({ earningsDays: null, earningsUnknown: true, isEtf: true });
    render(<TradeCardContextRail />);
    expect(earningsStatus()).toBe('PASS');
    expect(screen.getByText('ETF — no earnings date to check.')).toBeInTheDocument();
  });
});

/* Audit round 1, F4 — the rail grades the distance AS OF TODAY, through the
 * same helper (lib/earningsGate.ts) Step 7's buttons read, so the two agree. */
describe('audit round 1 F4 — the earnings gate is aged by the scan\'s age', () => {
  function daysAgo(days: number): string {
    const d = new Date();
    d.setDate(d.getDate() - days);
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T10:00:00`;
  }
  function scanAgo(days: number) {
    act(() => {
      useScanStore.setState({
        scanResult: {
          scan_id: 's', timestamp: daysAgo(days), candidates: [AUTO],
          event_window: { reject_days: 21, caution_days: 45 },
        } as any,
      } as any);
    });
  }

  it('Thursday: a Monday scan at 23d is graded at 20d — REJECT, saying both numbers', () => {
    scanAgo(3);
    publish({ earningsDays: 23, earningsVeto: false, isEtf: false });
    render(<TradeCardContextRail />);
    expect(earningsStatus()).toBe('REJECT');
    expect(screen.getByText(
      "Earnings in 20d (23d at the scan, 3d ago) — reject <21d, caution <45d (this scan's window).",
    )).toBeInTheDocument();
  });

  it('Monday: the same card the same day is CAUTION at 23d', () => {
    scanAgo(0);
    publish({ earningsDays: 23, earningsVeto: false, isEtf: false });
    render(<TradeCardContextRail />);
    expect(earningsStatus()).toBe('CAUTION');
  });

  it('a print that may have passed since the scan is an unknown date — CAUTION for a stock', () => {
    scanAgo(5);
    publish({ earningsDays: 3, earningsVeto: true, isEtf: false });
    render(<TradeCardContextRail />);
    expect(screen.getByText('Earnings date')).toBeInTheDocument();
    expect(earningsStatus()).toBe('CAUTION');
    expect(screen.getByText(/may already have passed/)).toBeInTheDocument();
    expect(screen.queryByText(EARNINGS_LABEL)).not.toBeInTheDocument();
  });
});

it('withholds numeric R/R when its measured stock stop moved', () => {
  act(() => { useTradeCardUiStore.setState({ activeCard: { card: PICKED, rrPending: false, rrStale: true } }); });
  render(<TradeCardContextRail />);
  expect(screen.getByText(/Stock stop moved since R\/R was measured/)).toBeInTheDocument();
  expect(screen.queryByText(/Projected reward:risk/)).not.toBeInTheDocument();
});


it.each(['stock_stop', 'premium_stop'] as const)('names captured %s risk without changing its thresholds', (basis) => {
  act(() => { useTradeCardUiStore.setState({ activeCard: { card: { ...PICKED, exit: { ...PICKED.exit, rrRiskBasis: basis } }, rrPending: false } }); });
  render(<TradeCardContextRail />);
  expect(screen.getByText(new RegExp(`risking the ${basis === 'stock_stop' ? 'stock stop' : 'premium stop'}`))).toBeInTheDocument();
});
