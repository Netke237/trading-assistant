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


const PICKED_ID = 'AAA|160|2026-05-15|C';
const picked: OptionContract = {
  id: PICKED_ID, symbol: 'AAA', strike: 160, expiry: '2026-05-15', right: 'C',
  dte: 24, dteTotal: 30, price: 1.1, delta: 0.3, theta: -0.05,
  ivRank: 77, iv: 41, ivPercentile: 77, spread: 0.05, volume: 500,
  score: 58, contractConfidence: 'CAUTION',
  breakdown: { dteFit: 80, delta: 60, ivAttractiveness: 30, liquidity: 70, spread: 30 },
};


/*
 * STEP3-PARAM-REACH (STEP6-SCAN-CONTRACT-RULES deferred item 4). Both
 * recompute-plan call sites -- the active card and every other overridden
 * basket card -- send the Reward/Risk overrides the SCAN priced with
 * (ScanResult.rr_overrides), not live Step-3 scanOverrides edited after it.
 */
const RECORDED = { rr_target_r_multiple: 2.5, rr_bullish_invalidation_pct: 0.04 };
const LIVE = { rr_target_r_multiple: 3, rr_bullish_invalidation_pct: 0.2 };
const RR_KEYS = ['rr_target_r_multiple', 'rr_bullish_invalidation_pct', 'rr_bearish_invalidation_pct'];
const rrOf = (body: Record<string, unknown>) =>
  Object.fromEntries(RR_KEYS.filter((k) => k in body).map((k) => [k, body[k]]));

const PICKED_BBB = { ...picked, id: 'BBB|160|2026-05-15|C', symbol: 'BBB' };

function seed(rr: Record<string, number> | null | undefined) {
  act(() => {
    useScanStore.setState({
      scanResult: {
        scan_id: 'test-scan', candidates: [makeCard('AAA'), makeCard('BBB')],
        ...(rr !== undefined ? { rr_overrides: rr } : {}),
      } as any,
      optionsCardEdits: {
        ...emptyCardEdits(), scanId: 'test-scan',
        picks: {
          'AAA|150|2026-05-15|C': pick(), [PICKED_ID]: pick(),
          'BBB|150|2026-05-15|C': pick(), [PICKED_BBB.id]: pick(),
        },
      },
      pickedContracts: { AAA: PICKED_ID, BBB: PICKED_BBB.id },
      contractsBySymbol: { AAA: [picked], BBB: [PICKED_BBB] },
      scanOverrides: { ...LIVE },
    } as any);
    usePortfolioStore.setState({ positions: [], lastSyncError: null });
    useAutoTradeStore.setState({ selectedBroker: null, autoMode: 'manual', armed: false, lastOrderId: null });
    useTradeCardUiStore.setState({ activeCard: null });
  });
}

describe('step-7-trade-card -- recompute-plan sends the scan\'s rr_* (STEP3-PARAM-REACH)', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (api.getStockQuote as jest.Mock).mockResolvedValue({ price: 150 });
    (api.getContractQuote as jest.Mock).mockResolvedValue({
      quoteLive: true, price: 1.1, delta: 0.3, theta: -0.05, ivRank: 77, spread: 0.05, volume: 500,
    });
    (api.getAutoTradeStatus as jest.Mock).mockResolvedValue({ armed: false });
    const b = makeCard('AAA');
    (api.recomputePlan as jest.Mock).mockResolvedValue({ entry: b.entry, exit: b.exit, rrRatio: 1.2, rrModel: 'Heston repriced' });
    global.fetch = echoFetch();
  });
  afterEach(() => { global.fetch = originalFetch; });

  const callFor = (sym: string) =>
    (api.recomputePlan as jest.Mock).mock.calls.map((c) => c[0]).find((b) => b.symbol === sym);

  it('active card: the recorded overrides, not live Step-3 values', async () => {
    seed(RECORDED);
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(callFor('AAA')).toBeDefined());
    expect(rrOf(callFor('AAA'))).toEqual(RECORDED);
  });

  it('basket card: the recorded overrides, not live Step-3 values', async () => {
    seed(RECORDED);
    // AAA's active-card request never settles, so leaving AAA releases its
    // claim and the BASKET effect (not the active one) re-requests it.
    (api.recomputePlan as jest.Mock).mockReturnValueOnce(new Promise(() => {}));
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(callFor('AAA')).toBeDefined());
    fireEvent.click(await screen.findByTitle('Pin to basket'));
    (api.recomputePlan as jest.Mock).mockClear();
    // BBB becomes the active card; AAA, pinned and overridden, is now
    // recomputed by the basket effect.
    fireEvent.click(screen.getByRole('button', { name: 'Next candidate' }));
    await waitFor(() => expect(callFor('BBB')).toBeDefined());
    expect(rrOf(callFor('BBB'))).toEqual(RECORDED);
    await waitFor(() => expect(callFor('AAA')).toBeDefined());
    expect(rrOf(callFor('AAA'))).toEqual(RECORDED);
  });

  it('round-trips captured target provenance for active and basket overrides', async () => {
    seed(RECORDED);
    act(() => {
      const result = useScanStore.getState().scanResult!;
      useScanStore.setState({ scanResult: { ...result, candidates: result.candidates.map((card) => ({
        ...card, exit: { ...card.exit, target: 164.23, targetSource: 'structural_snap' as const },
      })) } });
    });
    (api.recomputePlan as jest.Mock).mockReturnValueOnce(new Promise(() => {}));
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(callFor('AAA')).toMatchObject({ target_stock_price: 164.23, target_source: 'structural_snap', rr_target_r_multiple: 2.5 }));
    fireEvent.click(await screen.findByTitle('Pin to basket'));
    (api.recomputePlan as jest.Mock).mockClear();
    fireEvent.click(screen.getByRole('button', { name: 'Next candidate' }));
    await waitFor(() => expect(callFor('BBB')).toMatchObject({ target_stock_price: 164.23, target_source: 'structural_snap' }));
    await waitFor(() => expect(callFor('AAA')).toMatchObject({ target_stock_price: 164.23, target_source: 'structural_snap' }));
  });

  it('omits old flat target from a card without captured provenance', async () => {
    seed(RECORDED);
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(callFor('AAA')).toBeDefined());
    expect(callFor('AAA')).not.toHaveProperty('target_stock_price');
    expect(callFor('AAA')).not.toHaveProperty('target_source');
  });

  it('a scan that overrode none sends none, whatever Step 3 says now', async () => {
    seed({});
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(callFor('AAA')).toBeDefined());
    expect(rrOf(callFor('AAA'))).toEqual({});
  });

  it('a result from before the record falls back to live Step-3 values', async () => {
    seed(undefined);
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(callFor('AAA')).toBeDefined());
    expect(rrOf(callFor('AAA'))).toEqual(LIVE);
  });
});
