import '@testing-library/jest-dom';
import { render, screen, act } from '@testing-library/react';
import TradeCardContextRail from '../page';
import { useScanStore } from '@/lib/scanStore';
import { useTradeCardUiStore } from '@/lib/tradeCardUiStore';
import { useIvThresholdsStore } from '@/lib/ivThresholdsStore';
import type { TradeCardData } from '@/types/domain';

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
    nextEventDays: 30,
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
  act(() => {
    useScanStore.setState({
      scanResult: { scan_id: 's', candidates: [AUTO] } as any,
      selectedSymbol: 'AAA',
      combinedRegime: 'PASS',
      context: { universe: 'SP500', direction: 'Bullish', horizon: 'Swing (7–21d)', horizonPreset: 'Swing', holdMin: 7, holdMax: 21 } as any,
    } as any);
    useIvThresholdsStore.setState({
      thresholds: { Swing: { abs_pass_max: 40, abs_caution_max: 60, rank_pass_max: 55, rank_caution_max: 70 } },
    } as any);
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
