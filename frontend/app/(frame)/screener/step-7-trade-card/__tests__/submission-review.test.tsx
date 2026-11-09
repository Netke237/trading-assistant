import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor, act, within, cleanup } from '@testing-library/react';
import Step7TradeCardPage from '../page';
import { useScanStore } from '@/lib/scanStore';
import { emptyCardEdits } from '@/lib/cardEdits';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { useAutoTradeStore } from '@/lib/autoTradeStore';
import { useDirectSendNotesStore } from '@/lib/directSendNotesStore';
import { api } from '@/lib/api';
import type { ExitPlan, MethodPick, TradeCardData } from '@/types/domain';


/** #583 — a direct send opens the server review first; its final action saves
 *  and sends. A send refused before the review (a gate, a quote warning)
 *  opens none, and nothing is clicked. */
async function confirmReview() {
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Placing…' })).not.toBeInTheDocument());
  const confirm = screen.queryByRole('button', { name: /^Send to / });
  if (confirm) fireEvent.click(confirm);
}

/*
 * #581 (TC-REVIEW-06) — the Step 7 review renders the SAME draft the send
 * paths stamp and submit: actual Exit Plan settings (never a calculation's
 * stop), quantity, contract, destination, entry semantics, the raw recorded
 * selection, and the intended target-alert basis with its existing fallback.
 * Every edit refreshes it under a new generation; a late async answer for an
 * older contract never replaces it.
 */

jest.mock('@/lib/api', () => ({
  api: {
    getStockQuote: jest.fn(),
    getContractQuote: jest.fn(),
    postOptionOrder: jest.fn(),
    deletePortfolioPosition: jest.fn(),
    recomputePlan: jest.fn(),
    getAutoTradeStatus: jest.fn(),
    armAutoTrade: jest.fn(),
    disarmAutoTrade: jest.fn(),
    fireAutoTrade: jest.fn(),
    getExitPlan: jest.fn(),
    getFirstPassageEstimate: jest.fn(),
    getStructuralStop: jest.fn(),
  },
}));

const AAA_KEY = 'AAA|150|2026-05-15|C';
const BBB_KEY = 'BBB|155|2026-05-15|C';
const ladderPick = (o: Partial<MethodPick> = {}): MethodPick => ({
  method: 'ladder', rowStockPrice: 160, rowOptionPrice: null, stopBasis: 'stock', pickedAt: '2026-09-14T10:00:00.000Z', ...o,
});

const PLAN: ExitPlan = {
  computedAt: '2026-09-14T10:00:00Z',
  stop: { price: 131, source: 'atr_widened', contractPrice: 1.1, rrModel: 'Heston repriced', structuralSource: null, structuralConfidence: null, structuralPrice: null, atrFloorPrice: 131, distanceDollar: null } as any,
  targets: [
    { rrRatio: 2, arithmeticPrice: 170, price: 170, tpSource: 'arithmetic', structuralPrice: null, contractPrice: 5, rrModel: 'Heston repriced', probability: 0.4, expectedDays: 9, qualityGood: true, qualityReasons: [], distanceDollar: null, toleranceDollar: 1 },
    { rrRatio: 3, arithmeticPrice: 185, price: 185, tpSource: 'arithmetic', structuralPrice: null, contractPrice: 7, rrModel: 'Heston repriced', probability: 0.2, expectedDays: 14, qualityGood: true, qualityReasons: [], distanceDollar: null, toleranceDollar: 1 },
  ] as any,
  atr: 4,
} as ExitPlan;

function makeCard(symbol: string, o: { mid?: number; exitPlan?: ExitPlan } = {}): TradeCardData {
  const isSecond = symbol === 'BBB';
  const strike = isSecond ? 155 : 150;
  const mid = o.mid ?? (isSecond ? 3.3 : 2.5);
  return {
    symbol, company: `${symbol} Inc.`, price: 150, direction: 'Bullish', status: 'PASS',
    stockScore: 80, stockConfidence: 'PASS',
    stockBreakdown: { trend: 80, pullback: 80, trigger: 80, event: 80, volatility: 80 },
    contract: `${symbol} ${strike}C 05/15`, contractScore: 70, contractConfidence: 'PASS',
    contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 60 },
    contractDetails: { strike, expiry: '2026-05-15', right: 'C', mid, delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 },
    entry: { limit: mid, maxFill: 2.63, orderType: 'Limit' },
    exit: {
      invalidation: isSecond ? 120 : 140, premiumStop: 1.5, timeStopDays: 10, target: 160,
      targets: [{ id: 'tp1', stockPrice: 160, targetPrice: 160, estimatedOptionPrice: 4.1, contractsToSell: 1 }] as any,
      ...(o.exitPlan ? { exitPlan: o.exitPlan } : {}),
    },
    rrRatio: 2.0, rrModel: 'Heston repriced', finalStatus: 'PASS',
    regimeGate: { headwindCautionPct: -15, headwindRejectPct: -40 },
  };
}

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((res) => { resolve = res; });
  return { promise, resolve };
}
const quote = (price: number) => ({ quoteLive: true, price, delta: 0.45, theta: -0.09, ivRank: 45, iv: 0.3, spread: 0.1, volume: 100 });


/** #582 — Track basket confirms only server-reviewed rows. The review
 *  (POST /api/portfolio/preview) is answered with the request echoed as the
 *  would-be saved row; every other request goes to `inner`. */
function withPreview(inner: typeof fetch): typeof fetch {
  return jest.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    if (String(url).endsWith('/api/portfolio/preview') && init?.method === 'POST') {
      const body = JSON.parse(String(init.body));
      return { ok: true, status: 200, json: async () => ({ fingerprint: `v1:${body.recId}`, position: { ...body, id: '', createdAt: '' }, differences: [] }) };
    }
    return (inner as unknown as (u: string, i?: RequestInit) => Promise<unknown>)(url, init);
  }) as unknown as typeof fetch;
}

const originalFetch = global.fetch;
function setup(cards: TradeCardData[], picks: Record<string, MethodPick> = { [AAA_KEY]: ladderPick(), [BBB_KEY]: ladderPick() }) {
  act(() => {
    useScanStore.setState({
      scanResult: { scan_id: 'review-scan', timestamp: '2026-09-14T10:00:00', candidates: cards } as any,
      optionsCardEdits: { ...emptyCardEdits(), scanId: 'review-scan', picks },
      stocksCardEdits: emptyCardEdits(), pickedContracts: {}, contractsBySymbol: {}, scanOverrides: {},
    } as any);
    usePortfolioStore.setState({ positions: [], lastSyncError: null });
    useSettingsStore.setState((s) => ({
      premiumStopPct: 0.6,
      ibkrPaper: { ...s.ibkrPaper, accountId: 'ACC', baseUrl: 'https://localhost:7499/v1/api' },
    }) as any);
    useAutoTradeStore.setState({ selectedBroker: null, autoMode: 'manual', armed: false, lastOrderId: null });
    useDirectSendNotesStore.setState({ notes: [] });
  });
  jest.clearAllMocks();
  (api.getStockQuote as jest.Mock).mockResolvedValue({ price: 151 });
  (api.getContractQuote as jest.Mock).mockResolvedValue(quote(4.0));
  (api.postOptionOrder as jest.Mock).mockResolvedValue({ order_id: 'ORD-1', status: 'submitted', broker: 'ibkr_paper' });
  (api.getAutoTradeStatus as jest.Mock).mockResolvedValue({ armed: false });
  global.fetch = withPreview(jest.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    if (String(url).endsWith('/api/portfolio') && init?.method === 'POST') {
      const body = { ...JSON.parse(String(init.body)), premiumStopPct: null };
      return { ok: true, status: 201, json: async () => body };
    }
    return { ok: true, json: async () => ({}) };
  }) as unknown as typeof fetch);
}

const review = () => within(screen.getByRole('region', { name: 'Submission review' }));
const reviewValue = (label: string) => review().getByText(label, { selector: 'dt' }).nextElementSibling as HTMLElement;
const generation = () => Number(screen.getByRole('region', { name: 'Submission review' }).getAttribute('data-generation'));
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 20)); });
const persistBodies = () => (global.fetch as jest.Mock).mock.calls
  .filter(([u, init]) => String(u).endsWith('/api/portfolio') && init?.method === 'POST')
  .map(([, init]) => JSON.parse(String(init.body)) as Record<string, unknown>);

async function renderPage() {
  render(<Step7TradeCardPage />);
  await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
  await settle();
}
function editField(label: string, to: string) {
  fireEvent.click(screen.getByLabelText(`Edit ${label}`));
  const input = screen.getByLabelText(`Edit ${label}`) as HTMLInputElement;
  fireEvent.change(input, { target: { value: to } });
  fireEvent.keyDown(input, { key: 'Enter' });
}

describe('#581 Step 7 submission review', () => {
  beforeEach(() => { localStorage.clear(); });
  afterEach(() => { cleanup(); global.fetch = originalFetch; });

  it('shows the actual execution inputs once, in the decision section, and they are what is sent', async () => {
    setup([makeCard('AAA'), makeCard('BBB')]);
    await renderPage();
    const final = within(screen.getByRole('region', { name: 'Decision and execution' }));
    expect(final.getByRole('region', { name: 'Submission review' })).toBeInTheDocument();
    // The old "Execution …" echo rows are consolidated into the review.
    expect(screen.queryByText('Execution order / limit')).not.toBeInTheDocument();
    expect(screen.queryByText('Execution premium stop')).not.toBeInTheDocument();

    editField('Invalidation', '132');
    editField('Premium stop', '0.90');
    editField('Limit', '2.71');
    editField('Contracts', '3');
    await waitFor(() => expect(reviewValue('Quantity')).toHaveTextContent('3 contracts × 100 = 300 shares'));
    expect(reviewValue('Contract')).toHaveTextContent('AAA|150|2026-05-15|C');
    expect(reviewValue('Stock stop')).toHaveTextContent('$132.00 stock · typed');
    expect(reviewValue('Premium stop')).toHaveTextContent('$0.90/share pinned · 22.5% of the $4.00/share entry basis');
    expect(reviewValue('Entry limit')).toHaveTextContent('$2.71/share');
    expect(reviewValue('Entry basis sent')).toHaveTextContent('$4.00/share · live mid');
    expect(reviewValue('Effective target alert')).toHaveTextContent('Unresolved until server review');
    expect(reviewValue('Place Limit')).toHaveTextContent('Select a paper broker');

    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    await waitFor(() => expect(reviewValue('Place Limit')).toHaveTextContent('IBKR Paper · BUY to open 3 × AAA|150|2026-05-15|C · LMT $2.71 · DAY'));
    const btn = await screen.findByRole('button', { name: /place limit @/i });
    await waitFor(() => expect(btn).toBeEnabled());
    fireEvent.click(btn);
    await confirmReview();
    await waitFor(() => expect(api.postOptionOrder).toHaveBeenCalledTimes(1));
    const [order] = (api.postOptionOrder as jest.Mock).mock.calls[0];
    expect(order).toMatchObject({ quantity: 3, order_type: 'LMT', limit_price: 2.71, option_symbol: 'AAA|150|2026-05-15|C' });
    const posted = persistBodies()[0]!;
    expect(posted).toMatchObject({ stop: 132, stopIsUserSet: true, premiumStopDollar: 0.9, premiumStopPct: 0.9 / 4, entryPrice: 4, qty: 3 });
  });

  it('a calculation stop is shown as a result; the actual stop is reviewed and sent', async () => {
    setup([makeCard('AAA', { exitPlan: PLAN }), makeCard('BBB')]);
    await renderPage();
    const final = within(screen.getByRole('region', { name: 'Decision and execution' }));
    // The calculation's own stop is on screen as a result...
    expect(final.queryAllByText(/\$131\.00/).length + screen.queryAllByText(/\$131\.00/).length).toBeGreaterThan(0);
    // ...while the review shows and the send carries the Exit Plan stop.
    expect(reviewValue('Stock stop')).toHaveTextContent('$140.00 stock · plan-derived');
    expect(reviewValue('Arithmetic plan attached')).toHaveTextContent(/Yes/);
    fireEvent.click(screen.getByRole('button', { name: /pin to basket/i }));
    fireEvent.click(await screen.findByRole('button', { name: /track basket \(1\)/i }));
    const submit = await screen.findByRole('button', { name: /^(Add 1 to Portfolio|Override & Submit)$/ });
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.click(submit);
    await waitFor(() => expect(persistBodies()).toHaveLength(1));
    expect(persistBodies()[0]).toMatchObject({ stop: 140, stopIsUserSet: false });
    expect((persistBodies()[0]!.exitPlan as ExitPlan).stop.price).toBe(131);
  });

  it('tiny premium, untouched: the review says global % against the saved entry, never a $/share stop', async () => {
    (api.getContractQuote as jest.Mock).mockResolvedValue(quote(0.01));
    setup([makeCard('AAA', { mid: 0.01 }), makeCard('BBB')]);
    (api.getContractQuote as jest.Mock).mockResolvedValue(quote(0.01));
    await renderPage();
    await waitFor(() => expect(reviewValue('Entry basis sent')).toHaveTextContent('$0.01/share · live mid'));
    expect(reviewValue('Premium stop')).toHaveTextContent('Global 60% of the saved entry — no dollar amount sent');
    expect(reviewValue('Premium stop')).not.toHaveTextContent('/share');
  });

  it('a recorded method with no target row shows the existing live-Ladder fallback', async () => {
    setup([makeCard('AAA'), makeCard('BBB')], { [AAA_KEY]: ladderPick({ rowStockPrice: null }), [BBB_KEY]: ladderPick() });
    await renderPage();
    expect(reviewValue('Recorded stock target')).toHaveTextContent('None sent');
    expect(reviewValue('Intended basis')).toHaveTextContent('Live Ladder fallback');
    expect(reviewValue('Effective target alert')).toHaveTextContent('Unresolved until server review');
    expect(review().getByText(/No target row is recorded, so no stock-price target is sent/)).toBeInTheDocument();
  });

  it('Judged on is recorded as a basis; both stop alerts stay armed in the review', async () => {
    setup([makeCard('AAA'), makeCard('BBB')], { [AAA_KEY]: ladderPick({ stopBasis: 'premium' }), [BBB_KEY]: ladderPick() });
    await renderPage();
    expect(reviewValue('Judged on')).toHaveTextContent('Premium stop — a recorded basis; the stock-stop and premium-stop alerts both stay armed');
    expect(reviewValue('Stock stop')).toHaveTextContent('$140.00 stock');
  });

  it('every edit and selection change refreshes the draft under a new generation', async () => {
    setup([makeCard('AAA'), makeCard('BBB')]);
    await renderPage();
    const g0 = generation();
    editField('Contracts', '2');
    await waitFor(() => expect(generation()).toBeGreaterThan(g0));
    const g1 = generation();
    editField('Invalidation', '133');
    await waitFor(() => expect(generation()).toBeGreaterThan(g1));
    const g2 = generation();
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }));
    await waitFor(() => expect(generation()).toBeGreaterThan(g2));
    expect(reviewValue('Method')).toHaveTextContent('Not selected');
    expect(reviewValue('Intended basis')).toHaveTextContent('No method recorded');
  });

  it('a late quote for the previous contract never replaces the newer contract\'s review', async () => {
    const aaa = deferred<ReturnType<typeof quote>>();
    setup([makeCard('AAA'), makeCard('BBB')]);
    (api.getContractQuote as jest.Mock).mockImplementation((symbol: string) =>
      symbol === 'AAA' ? aaa.promise : Promise.resolve(quote(3.9)));
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /next/i }));
    await waitFor(() => expect(reviewValue('Contract')).toHaveTextContent('BBB|155|2026-05-15|C'));
    await waitFor(() => expect(reviewValue('Entry basis sent')).toHaveTextContent('$3.90/share · live mid'));
    const g = generation();
    await act(async () => { aaa.resolve(quote(4.4)); await new Promise((r) => setTimeout(r, 20)); });
    expect(reviewValue('Contract')).toHaveTextContent('BBB|155|2026-05-15|C');
    expect(reviewValue('Entry basis sent')).toHaveTextContent('$3.90/share · live mid');
    expect(review().queryByText(/4\.40/)).not.toBeInTheDocument();
    expect(generation()).toBe(g);
  });

  it('a spread card reviews the selected contract only', async () => {
    const spread = {
      ...makeCard('AAA'), spreadType: 'bear_put',
      legs: [{ strike: 150, right: 'P', action: 'BUY', mid: 3.0 }, { strike: 140, right: 'P', action: 'SELL', mid: 1.2 }],
    } as unknown as TradeCardData;
    setup([spread, makeCard('BBB')]);
    await renderPage();
    expect(review().getByText(/Bear Put Spread: only the selected contract is submitted/)).toBeInTheDocument();
    expect(reviewValue('Track basket')).toHaveTextContent('Portfolio row only — no broker order · stored as AAA 150C 05/15');
  });
});
