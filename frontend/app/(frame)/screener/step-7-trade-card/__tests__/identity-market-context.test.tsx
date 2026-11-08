import '@testing-library/jest-dom';
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import Step7TradeCardPage from '../page';
import { useScanStore } from '@/lib/scanStore';
import { emptyCardEdits } from '@/lib/cardEdits';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useAutoTradeStore } from '@/lib/autoTradeStore';
import { api } from '@/lib/api';
import type { TradeCardData, MethodPick, OptionContract, FundamentalsOut } from '@/types/domain';

// TC-REVIEW-02 (#577). Market Sentiment stays above the card and the page
// renders Fundamental Health directly beneath it, once, for the active
// candidate, with the same lifetime it had inside the card (hidden while an
// overridden contract's plan is still being prepared).

const pick = (): MethodPick => ({
  method: 'ladder', rowStockPrice: 160, rowOptionPrice: null, stopBasis: 'stock',
  pickedAt: '2026-09-14T10:00:00.000Z',
});

jest.mock('@/lib/api', () => ({
  api: {
    getStockQuote: jest.fn().mockResolvedValue({ price: 150 }),
    getContractQuote: jest.fn().mockResolvedValue({
      quoteLive: true, price: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100,
    }),
    postOptionOrder: jest.fn(),
    deletePortfolioPosition: jest.fn(),
    recomputePlan: jest.fn(),
    getStructuralStop: jest.fn(),
    getExitPlan: jest.fn(),
    getAutoTradeStatus: jest.fn().mockResolvedValue({ armed: false }),
    armAutoTrade: jest.fn(),
    disarmAutoTrade: jest.fn(),
    fireAutoTrade: jest.fn(),
  },
}));

const health = (score: number): FundamentalsOut => ({
  score, growth_score: 65, quality_score: 40, risk_score: 39,
  quality_label: 'Strong', risk_label: 'High', safety_flags: ['negative_equity'], detail: {},
});

function makeCard(symbol: string, fundamentals: FundamentalsOut | null): TradeCardData {
  return {
    symbol, company: `${symbol} Inc.`, price: 150, direction: 'Bullish', status: 'PASS',
    stockScore: 80, stockConfidence: 'PASS',
    stockBreakdown: { trend: 80, pullback: 80, trigger: 80, event: 80, volatility: 80 },
    contract: `${symbol} 150C 05/15`, contractScore: 70, contractConfidence: 'PASS',
    contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 60 },
    contractDetails: { strike: 150, expiry: '2026-05-15', right: 'C', mid: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 },
    entry: { limit: 2.5, maxFill: 2.63, orderType: 'Limit' },
    exit: { invalidation: 140, premiumStop: 1.5, timeStopDays: 10, target: 160, targets: [] },
    rrRatio: 2.0, rrModel: 'Heston repriced', finalStatus: 'PASS',
    regimeGate: { headwindCautionPct: -15, headwindRejectPct: -40 },
    fundamentals,
  };
}

const PICKED_ID = 'AAA|160|2026-05-15|C';
const picked: OptionContract = {
  id: PICKED_ID, symbol: 'AAA', strike: 160, expiry: '2026-05-15', right: 'C',
  dte: 24, dteTotal: 30, price: 1.1, delta: 0.3, theta: -0.05,
  ivRank: 77, iv: 41, ivPercentile: 77, spread: 0.05, volume: 500,
  score: 58, contractConfidence: 'CAUTION',
  breakdown: { dteFit: 80, delta: 60, ivAttractiveness: 30, liquidity: 70, spread: 30 },
};

const originalFetch = global.fetch;

function seed(pickedContracts: Record<string, string> = {}) {
  act(() => {
    useScanStore.setState({
      scanResult: { scan_id: 'test-scan', candidates: [makeCard('AAA', health(64)), makeCard('BBB', null)] } as any,
      optionsCardEdits: {
        ...emptyCardEdits(), scanId: 'test-scan',
        picks: { 'AAA|150|2026-05-15|C': pick(), 'BBB|150|2026-05-15|C': pick(), [PICKED_ID]: pick() },
      },
      pickedContracts,
      contractsBySymbol: { AAA: [picked] },
      scanOverrides: {},
    } as any);
    usePortfolioStore.setState({ positions: [], lastSyncError: null });
    useAutoTradeStore.setState({ selectedBroker: null, autoMode: 'manual', armed: false, lastOrderId: null });
  });
}

const follows = (a: Element, b: Element) =>
  (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;

describe('step-7-trade-card — identity and market context (#577)', () => {
  beforeEach(() => {
    localStorage.clear();
    jest.clearAllMocks();
    (api.getStockQuote as jest.Mock).mockResolvedValue({ price: 150 });
    (api.getContractQuote as jest.Mock).mockResolvedValue({
      quoteLive: true, price: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100,
    });
    (api.getAutoTradeStatus as jest.Mock).mockResolvedValue({ armed: false });
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({}) }) as unknown as typeof fetch;
  });
  afterEach(() => { global.fetch = originalFetch; });

  it('renders Fundamental Health once, directly beneath Market Sentiment and above the card', async () => {
    seed();
    render(<Step7TradeCardPage />);
    const identity = await screen.findByRole('region', { name: 'Selected stock and contract' });
    const sentimentRoot = screen.getByText('Regime: Unmeasured').parentElement!;
    const healthTitle = screen.getByText('Fundamental Health');
    expect(screen.getAllByText('Fundamental Health')).toHaveLength(1);
    expect(sentimentRoot.nextElementSibling).toContainElement(healthTitle);
    expect(follows(healthTitle, screen.getByRole('button', { name: /Prev/ }))).toBe(true);
    expect(follows(healthTitle, identity)).toBe(true);
    expect(screen.getByText('negative equity')).toBeInTheDocument();
    expect(screen.getByText('Score definitions & safety flags')).toBeInTheDocument();
  });

  it('follows the active candidate, including its missing-data state', async () => {
    seed();
    render(<Step7TradeCardPage />);
    await screen.findByRole('region', { name: 'Selected stock and contract' });
    expect(screen.getByText('64')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Next/ }));
    await screen.findByText('BBB Inc.');
    expect(screen.getByText('Fundamental Health — no data')).toBeInTheDocument();
    expect(screen.queryByText('Strong quality · High risk')).not.toBeInTheDocument();
    const sentimentRoot = screen.getByText('Regime: Unmeasured').parentElement!;
    expect(sentimentRoot.nextElementSibling).toHaveTextContent('Fundamental Health — no data');
  });

  it('keeps the card lifetime: hidden while an overridden contract plan is prepared, then shown', async () => {
    let resolvePlan!: (p: unknown) => void;
    (api.recomputePlan as jest.Mock).mockReturnValue(new Promise((r) => { resolvePlan = r; }));
    seed({ AAA: PICKED_ID });
    render(<Step7TradeCardPage />);
    await screen.findByText('Preparing the plan for your selected contract…');
    expect(screen.getByText('Regime: Unmeasured')).toBeInTheDocument();
    expect(screen.queryByText('Fundamental Health')).not.toBeInTheDocument();
    await waitFor(() => expect(api.recomputePlan).toHaveBeenCalled());
    await act(async () => {
      resolvePlan({
        entry: { limit: 1.1, maxFill: 1.16, orderType: 'Limit' },
        exit: { invalidation: 140, premiumStop: 0.66, timeStopDays: 10, target: 170, targets: [] },
        rrRatio: 3.1, rrModel: 'Heston repriced',
      });
    });
    await waitFor(() => expect(screen.getByText('Fundamental Health')).toBeInTheDocument());
    expect(screen.getAllByText('Fundamental Health')).toHaveLength(1);
    expect(screen.getByRole('group', { name: 'Contract identity' })).toHaveTextContent('$160 Call');
  });
});
