import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import Step7TradeCardPage from '../page';
import { useScanStore } from '@/lib/scanStore';
import { emptyCardEdits } from '@/lib/cardEdits';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useAutoTradeStore } from '@/lib/autoTradeStore';
import { api } from '@/lib/api';
import type { TradeCardData, MethodPick, OptionContract } from '@/types/domain';
import { useTradeCardUiStore } from '@/lib/tradeCardUiStore';

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

const RECORDED_ENTRY = {
  entry_spread_tolerance_pct: 0.15,
  entry_max_slippage_pct: 0,
  entry_min_premium: 2.5,
};
const LIVE_ENTRY = {
  entry_spread_tolerance_pct: 0.25,
  entry_max_slippage_pct: 0.05,
  entry_min_premium: 5.0,
};
const ENTRY_KEYS = ['entry_spread_tolerance_pct', 'entry_max_slippage_pct', 'entry_min_premium'];
const entryOf = (body: Record<string, unknown>) =>
  Object.fromEntries(ENTRY_KEYS.filter((k) => k in body).map((k) => [k, body[k]]));

const PICKED_BBB = { ...picked, id: 'BBB|160|2026-05-15|C', symbol: 'BBB' };

function seed(entryOverrides: Record<string, number> | null | undefined) {
  act(() => {
    useScanStore.setState({
      scanResult: {
        scan_id: 'test-scan', candidates: [makeCard('AAA'), makeCard('BBB')],
        ...(entryOverrides !== undefined ? { entry_overrides: entryOverrides } : {}),
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
      scanOverrides: { ...LIVE_ENTRY },
    } as any);
    usePortfolioStore.setState({ positions: [], lastSyncError: null });
    useAutoTradeStore.setState({ selectedBroker: null, autoMode: 'manual', armed: false, lastOrderId: null });
    useTradeCardUiStore.setState({ activeCard: null });
  });
}

describe('step-7-trade-card -- recompute-plan sends the scan\'s entry_* overrides (APP-AUDIT-B-ENTRY-OVERRIDES)', () => {
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

  it('active card sends recorded entry overrides, including zero, not live Step 3 values', async () => {
    seed(RECORDED_ENTRY);
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(callFor('AAA')).toBeDefined());
    expect(entryOf(callFor('AAA'))).toEqual(RECORDED_ENTRY);
  });

  it('basket card sends recorded entry overrides, including zero, not live Step 3 values', async () => {
    seed(RECORDED_ENTRY);
    (api.recomputePlan as jest.Mock).mockReturnValueOnce(new Promise(() => {}));
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(callFor('AAA')).toBeDefined());
    fireEvent.click(await screen.findByTitle('Pin to basket'));
    (api.recomputePlan as jest.Mock).mockClear();
    fireEvent.click(screen.getByRole('button', { name: 'Next candidate' }));
    await waitFor(() => expect(callFor('BBB')).toBeDefined());
    expect(entryOf(callFor('BBB'))).toEqual(RECORDED_ENTRY);
    await waitFor(() => expect(callFor('AAA')).toBeDefined());
    expect(entryOf(callFor('AAA'))).toEqual(RECORDED_ENTRY);
  });

  it('a scan that overrode none sends none, whatever Step 3 says now', async () => {
    seed({});
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(callFor('AAA')).toBeDefined());
    expect(entryOf(callFor('AAA'))).toEqual({});
  });

  it('a result from before the record (null/undefined) falls back to live Step 3 values', async () => {
    seed(undefined);
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(callFor('AAA')).toBeDefined());
    expect(entryOf(callFor('AAA'))).toEqual(LIVE_ENTRY);
  });
});
