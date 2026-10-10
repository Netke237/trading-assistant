import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import Step7TradeCardPage from '../page';
import { useScanStore } from '@/lib/scanStore';
import { emptyCardEdits } from '@/lib/cardEdits';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { useAutoTradeStore } from '@/lib/autoTradeStore';
import { api } from '@/lib/api';
import type { TradeCardData, MethodPick, OptionContract } from '@/types/domain';
import { useTradeCardUiStore } from '@/lib/tradeCardUiStore';

// Phase G piece 5, build step 4 — this suite is about the shared Contracts
// map, not the method-pick gate, so every fixture stamps a satisfied pick
// for both basket symbols or the new `pickMissing` check leaves every send
// path disabled regardless of what these tests exercise.
const pick = (): MethodPick => ({
  method: 'ladder',
  rowStockPrice: 160,
  rowOptionPrice: null,
  stopBasis: 'stock',
  pickedAt: '2026-09-14T10:00:00.000Z',
});


jest.mock('@/lib/api', () => ({
  api: {
    getStockQuote: jest.fn().mockResolvedValue({ price: 150 }),
    getContractQuote: jest.fn().mockResolvedValue({
      quoteLive: true, price: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100,
    }),
    postOptionOrder: jest.fn().mockResolvedValue({ order_id: 'ORD-1' }),
    deletePortfolioPosition: jest.fn().mockResolvedValue(undefined),
    recomputePlan: jest.fn(),
    getStructuralStop: jest.fn(),
    getExitPlan: jest.fn(),
    getAutoTradeStatus: jest.fn().mockResolvedValue({ armed: false }),
    armAutoTrade: jest.fn().mockResolvedValue({ armed: true }),
    disarmAutoTrade: jest.fn().mockResolvedValue({ armed: false }),
    fireAutoTrade: jest.fn().mockResolvedValue({ order_id: 'ORD-AUTO' }),
  },
}));

/* P1b-i -- the direct sends now SAVE FIRST, and a 2xx whose body carries no
 * positive `entryPrice` is treated as unconfirmed (no order is sent). So the
 * persist POST ECHOES its request body back, which carries the `entryPrice`
 * and `recId` the page sent; every other request keeps the old `{}` reply. */
function echoFetch(): typeof fetch {
  return jest.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    if (String(url).endsWith('/api/portfolio') && init?.method === 'POST') {
      const body = JSON.parse(String(init.body));
      return { ok: true, status: 201, json: async () => body };
    }
    return { ok: true, json: async () => ({}) };
  }) as unknown as typeof fetch;
}

function makeCard(symbol: string): TradeCardData {
  return {
    symbol,
    company: `${symbol} Inc.`,
    price: 150,
    direction: 'Bullish',
    status: 'PASS',
    stockScore: 80,
    stockConfidence: 'PASS',
    stockBreakdown: { trend: 80, pullback: 80, trigger: 80, event: 80, volatility: 80 },
    contract: `${symbol} 150C 05/15`,
    contractScore: 70,
    contractConfidence: 'PASS',
    contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 60 },
    contractDetails: { strike: 150, expiry: '2026-05-15', right: 'C', mid: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 },
    entry: { limit: 2.5, maxFill: 2.63, orderType: 'Limit' },
    exit: { invalidation: 140, premiumStop: 1.5, timeStopDays: 10, target: 160, targets: [] },
    rrRatio: 2.0,
    rrModel: 'Heston repriced',
    finalStatus: 'PASS',
    // Every card a current scan produces carries its resolved regime-gate
    // rule; AutoTradeArm refuses one that does not.
    regimeGate: { headwindCautionPct: -15, headwindRejectPct: -40 },
  };
}

const originalFetch = global.fetch;

/*
 * A8, open_questions[64]. Step 7 publishes the card it SHOWS -- the Step-6
 * pick applied, the recomputed plan merged -- for the @contextRail checklist,
 * which used to grade the raw scan candidate (the auto-pick).
 */

const PICKED_ID = 'AAA|160|2026-05-15|C';
const picked: OptionContract = {
  id: PICKED_ID, symbol: 'AAA', strike: 160, expiry: '2026-05-15', right: 'C',
  dte: 24, dteTotal: 30, price: 1.1, delta: 0.3, theta: -0.05,
  ivRank: 77, iv: 41, ivPercentile: 77, spread: 0.05, volume: 500,
  score: 58, contractConfidence: 'CAUTION',
  breakdown: { dteFit: 80, delta: 60, ivAttractiveness: 30, liquidity: 70, spread: 30 },
};

describe('step-7-trade-card -- publishes the shown card for the context rail (A8)', () => {
  beforeEach(() => {
    act(() => {
      useScanStore.setState({
        scanResult: { scan_id: 'test-scan', candidates: [makeCard('AAA')] } as any,
        optionsCardEdits: {
          ...emptyCardEdits(), scanId: 'test-scan',
          picks: { 'AAA|150|2026-05-15|C': pick(), [PICKED_ID]: pick() },
        },
        pickedContracts: { AAA: PICKED_ID },
        contractsBySymbol: { AAA: [picked] },
        scanOverrides: {},
      } as any);
      usePortfolioStore.setState({ positions: [], lastSyncError: null });
      useAutoTradeStore.setState({ selectedBroker: null, autoMode: 'manual', armed: false, lastOrderId: null });
      useTradeCardUiStore.setState({ activeCard: null });
    });
    jest.clearAllMocks();
    (api.getStockQuote as jest.Mock).mockResolvedValue({ price: 150 });
    (api.getContractQuote as jest.Mock).mockResolvedValue({
      quoteLive: true, price: 1.1, delta: 0.3, theta: -0.05, ivRank: 77, spread: 0.05, volume: 500,
    });
    (api.getAutoTradeStatus as jest.Mock).mockResolvedValue({ armed: false });
    global.fetch = echoFetch();
  });
  afterEach(() => { global.fetch = originalFetch; });

  it('publishes the picked contract with rrPending until its plan lands, then the plan\'s R:R; clears on unmount', async () => {
    let resolvePlan!: (p: unknown) => void;
    (api.recomputePlan as jest.Mock).mockReturnValue(new Promise((r) => { resolvePlan = r; }));

    const { unmount } = render(<Step7TradeCardPage />);

    await waitFor(() => expect(useTradeCardUiStore.getState().activeCard).not.toBeNull());
    let pub = useTradeCardUiStore.getState().activeCard!;
    expect(pub.card.contract).toBe(PICKED_ID);
    expect(pub.card.contractScore).toBe(58);
    expect(pub.card.contractDetails?.ivRank).toBe(77);
    expect(pub.card.contractBreakdown.spread).toBe(30);
    // The auto-pick's rrRatio (2.0) is still on the card: pending.
    expect(pub.rrPending).toBe(true);

    await waitFor(() => expect(api.recomputePlan).toHaveBeenCalled());
    const base = makeCard('AAA');
    await act(async () => {
      resolvePlan({ entry: base.entry, exit: base.exit, rrRatio: 1.2, rrModel: 'Heston repriced' });
    });
    await waitFor(() => expect(useTradeCardUiStore.getState().activeCard!.rrPending).toBe(false));
    pub = useTradeCardUiStore.getState().activeCard!;
    expect(pub.card.rrRatio).toBe(1.2);
    expect(pub.card.contract).toBe(PICKED_ID);

    unmount();
    expect(useTradeCardUiStore.getState().activeCard).toBeNull();
  });

  it('publishes the scan card, not pending, when nothing was picked', async () => {
    act(() => { useScanStore.setState({ pickedContracts: {} } as any); });
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(useTradeCardUiStore.getState().activeCard).not.toBeNull());
    const pub = useTradeCardUiStore.getState().activeCard!;
    expect(pub.card.contract).toBe('AAA 150C 05/15');
    expect(pub.rrPending).toBe(false);
  });
});

/*
 * A8, open_questions[51]. The "Check structure" cache is keyed by CONTRACT:
 * its response carries `stopCost`, the stop-vs-premium verdict priced against
 * the contract that was sent. Keyed by symbol, a check on the auto-pick was
 * restored onto a different contract of the same symbol.
 */
describe('step-7-trade-card -- the structural-stop cache is keyed by contract (A8)', () => {
  beforeEach(() => {
    act(() => {
      useScanStore.setState({
        scanResult: { scan_id: 'test-scan', candidates: [makeCard('AAA')] } as any,
        optionsCardEdits: {
          ...emptyCardEdits(), scanId: 'test-scan',
          picks: { 'AAA|150|2026-05-15|C': pick(), [PICKED_ID]: pick() },
        },
        pickedContracts: {},
        contractsBySymbol: { AAA: [picked] },
        scanOverrides: {},
      } as any);
      usePortfolioStore.setState({ positions: [], lastSyncError: null });
      useAutoTradeStore.setState({ selectedBroker: null, autoMode: 'manual', armed: false, lastOrderId: null });
    });
    jest.clearAllMocks();
    (api.getStockQuote as jest.Mock).mockResolvedValue({ price: 150 });
    (api.getContractQuote as jest.Mock).mockResolvedValue({
      quoteLive: true, price: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100,
    });
    (api.getAutoTradeStatus as jest.Mock).mockResolvedValue({ armed: false });
    (api.getStructuralStop as jest.Mock).mockResolvedValue({
      available: true, price: 143.25, source: 'order_block', confidence: 75, distancePct: 4.5,
    });
    // The picked card renders only once its plan lands; resolve it so the
    // assertion below is about the cache, not about an unrendered card.
    { const b = makeCard('AAA');
      (api.recomputePlan as jest.Mock).mockResolvedValue({ entry: b.entry, exit: b.exit, rrRatio: 1.2, rrModel: 'Heston repriced' }); }
    global.fetch = echoFetch();
  });
  afterEach(() => { global.fetch = originalFetch; });

  it('does not restore a check made on one contract onto another contract of the same symbol', async () => {
    render(<Step7TradeCardPage />);
    fireEvent.click(await screen.findByRole('button', { name: /check structure/i }));
    expect(await screen.findByText('$143.25 (4.5% away)')).toBeInTheDocument();

    // An in-page contract switch (none exists in production today -- a Step-6
    // pick unmounts this page -- which is exactly the invariant the symbol key
    // leaned on).
    act(() => { useScanStore.setState({ pickedContracts: { AAA: PICKED_ID } } as any); });
    await waitFor(() => expect(useTradeCardUiStore.getState().activeCard?.rrPending).toBe(false));
    expect(useTradeCardUiStore.getState().activeCard?.card.contract).toBe(PICKED_ID);
    expect(screen.getByRole('button', { name: /check structure/i })).toBeInTheDocument();
    expect(screen.queryByText('$143.25 (4.5% away)')).not.toBeInTheDocument();

    // Back to the auto-pick: its own check is still cached for it.
    act(() => { useScanStore.setState({ pickedContracts: {} } as any); });
    expect(await screen.findByText('$143.25 (4.5% away)')).toBeInTheDocument();
  });

  it('sends the checked level on a direct order for the contract it was checked on', async () => {
    (api.postOptionOrder as jest.Mock).mockResolvedValue({ order_id: 'ORD-1' });
    act(() => {
      useSettingsStore.setState((st) => ({
        ibkrPaper: { ...st.ibkrPaper, accountId: 'ACC', baseUrl: 'https://localhost:7499/v1/api' },
      }) as any);
    });
    render(<Step7TradeCardPage />);
    fireEvent.click(await screen.findByRole('button', { name: /check structure/i }));
    expect(await screen.findByText('$143.25 (4.5% away)')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    const limitBtn = await screen.findByRole('button', { name: /place limit @/i });
    await waitFor(() => expect(limitBtn).toBeEnabled());
    fireEvent.click(limitBtn);
    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
    expect(usePortfolioStore.getState().positions[0].structuralStop).toBe(143.25);
  });

  it('arms with the checked level and the computed plan, the two fields a fired trade books', async () => {
    // POSITION-WRITER-O4-CLEANUP (O4 step 6 round 2, item 6): the page passes
    // `structuralStop` and `exitPlan` to AutoTradeArm, and no test read them
    // back, so `structuralStop={null}` / `exitPlan={null}` at the call site
    // survived. The fired trade books both through `book_fired_order`.
    (api.getExitPlan as jest.Mock).mockResolvedValue({
      stop: {
        price: 141.0, source: 'atr_floor', contractPrice: 1.2,
        rrModel: 'Heston repriced', structuralSource: 'order_block', structuralConfidence: 75,
        structuralPrice: 143.25, atrFloorPrice: 141.0, distanceDollar: 9.0,
      },
      targets: [],
      atr: 3.5,
    });
    act(() => {
      useSettingsStore.setState((st) => ({
        ibkrPaper: { ...st.ibkrPaper, accountId: 'ACC', baseUrl: 'https://localhost:7499/v1/api' },
      }) as any);
    });
    render(<Step7TradeCardPage />);
    fireEvent.click(await screen.findByRole('button', { name: /check structure/i }));
    expect(await screen.findByText('$143.25 (4.5% away)')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /compute arithmetic plan/i }));
    await waitFor(() => expect(api.getExitPlan).toHaveBeenCalled());

    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    fireEvent.click(await screen.findByText(/armed — fire on next qualifying condition/i));
    fireEvent.click(await screen.findByRole('button', { name: /^Arm —/ }));

    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalled());
    const body = (api.armAutoTrade as jest.Mock).mock.calls[0][0];
    expect(body.structural_stop).toBe(143.25);
    expect(body.exit_plan).toEqual(expect.objectContaining({
      stop: expect.objectContaining({ price: 141.0, atrFloorPrice: 141.0 }),
      atr: 3.5,
    }));
  });
});
