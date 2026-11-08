import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor, act, cleanup, within } from '@testing-library/react';
import Step7TradeCardPage from '../page';
import { useScanStore } from '@/lib/scanStore';
import { emptyCardEdits } from '@/lib/cardEdits';
import { usePortfolioStore, REVIEW_FINGERPRINT_HEADER } from '@/lib/portfolioStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { useAutoTradeStore } from '@/lib/autoTradeStore';
import { useDirectSendNotesStore } from '@/lib/directSendNotesStore';
import { classifyDirectFailure } from '@/lib/directOrder';
import { responseFacts } from '@/lib/brokerReview';
import { api } from '@/lib/api';
import type { TradeCardData, MethodPick } from '@/types/domain';

/*
 * #584 — the whole Step 7 flow, card to server review to confirmation, for the
 * cases the per-ticket suites exercise only in pieces: every exit method, a
 * spread, edits restored from the persisted slice and then reverted, and server
 * adjustments on both review surfaces. All transport is mocked: `api` is a jest
 * mock and `fetch` answers only the Portfolio endpoints.
 */

jest.mock('@/lib/api', () => ({
  api: {
    getStockQuote: jest.fn(),
    getContractQuote: jest.fn(),
    getStructuralStop: jest.fn(),
    getExitPlan: jest.fn(),
    getFirstPassageEstimate: jest.fn(),
    postOptionOrder: jest.fn(),
    deletePortfolioPosition: jest.fn(),
    recomputePlan: jest.fn(),
    getAutoTradeStatus: jest.fn(),
    armAutoTrade: jest.fn(),
    disarmAutoTrade: jest.fn(),
    fireAutoTrade: jest.fn(),
  },
}));

const AAA_KEY = 'AAA|150|2026-05-15|C';
const pick = (): MethodPick => ({
  method: 'ladder', rowStockPrice: 160, rowOptionPrice: null, stopBasis: 'stock', pickedAt: '2026-09-14T10:00:00.000Z',
});

function makeCard(over: Partial<TradeCardData> = {}): TradeCardData {
  return {
    symbol: 'AAA', company: 'AAA Inc.', price: 150, direction: 'Bullish', status: 'PASS',
    stockScore: 80, stockConfidence: 'PASS',
    stockBreakdown: { trend: 80, pullback: 80, trigger: 80, event: 80, volatility: 80 },
    contract: 'AAA 150C 05/15', contractScore: 70, contractConfidence: 'PASS',
    contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 60 },
    contractDetails: { strike: 150, expiry: '2026-05-15', right: 'C', mid: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 },
    entry: { limit: 2.5, maxFill: 2.63, orderType: 'Limit' },
    exit: { invalidation: 140, premiumStop: 1.5, timeStopDays: 10, target: 160, targets: [] },
    rrRatio: 2.0, rrModel: 'Heston repriced', finalStatus: 'PASS',
    regimeGate: { headwindCautionPct: -15, headwindRejectPct: -40 },
    ...over,
  };
}

const EXIT_PLAN = {
  stop: { price: 138, source: 'structural', contractPrice: 0.9, rrModel: 'Heston repriced', structuralSource: 'order_block', structuralConfidence: 80, structuralPrice: 138, atrFloorPrice: 136, distanceDollar: 2 },
  targets: [{ rrRatio: 2, arithmeticPrice: 165, price: 165, tpSource: 'arithmetic', structuralPrice: null, contractPrice: 6, rrModel: 'Delta approximation', probability: 0.5, expectedDays: 9, qualityGood: true, qualityReasons: [], distanceDollar: null, toleranceDollar: 1 }],
  atr: 2.5, computedAt: '2026-09-14T10:01:00Z',
};
const ESTIMATE = {
  targets: [{ pct: 0.25, optionPrice: 3.1, stockPrice: 158, probability: 0.55, expectedDays: 8 }],
  invalidation: { probability: 0.3, expectedDays: 10 },
  race: {
    premiumStopPrice: 1, premiumStopPct: 0.6, stockStopPrice: 140, premiumUsed: 2.5, ivSolved: true, nPaths: 2000,
    outcomes: [{
      targetPct: 0.25, targetOptionPrice: 3.1, pTargetFirst: 0.4, pStockStopFirst: 0.2, pPremiumStopFirst: 0.3, pNeither: 0.1,
      weightTargetFirst: 0.4, weightStockStopFirst: 0.2, weightPremiumStopFirst: 0.3, weightNeither: 0.1,
      daysTarget: 7, daysStockStop: 8, daysPremiumStop: 9, daysAnyPathReachedStop: 10, repriceDaysStockStop: 10,
      terminalMean: 2, rewardDollar: 0.6, stopRepricedValue: 0.5, riskStockStop: 2, riskPremiumStop: 1.5,
      rrStockStop: 0.3, rrPremiumStop: 0.4, edgePerContract: -20,
    }],
  },
};

type Reply = { ok: boolean; status?: number; json: () => Promise<unknown> };
const previewOf = (body: Record<string, unknown>, over: Record<string, unknown> = {}, extra: Record<string, unknown> = {}) => ({
  fingerprint: `v1:${String(body.qty)}:${JSON.stringify(over)}:${String(body.stop)}`,
  position: { ...body, id: '', createdAt: '', ...over },
  differences: [],
  ...extra,
});
let previewReply: (body: Record<string, unknown>) => Reply;
const echoPreview = (body: Record<string, unknown>): Reply => ({ ok: true, status: 200, json: async () => previewOf(body) });

const originalFetch = global.fetch;
function installFetch() {
  global.fetch = jest.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    const u = String(url);
    if (u.endsWith('/api/portfolio/preview') && init?.method === 'POST') return previewReply(JSON.parse(String(init.body)));
    if (u.endsWith('/api/portfolio') && init?.method === 'POST') {
      return { ok: true, status: 201, json: async () => ({ ...JSON.parse(String(init.body)), id: 'row', createdAt: '2026-09-14' }) };
    }
    if (u.endsWith('/api/portfolio')) return { ok: true, status: 200, json: async () => [] };
    return { ok: true, json: async () => ({}) };
  }) as unknown as typeof fetch;
}
const fetchCalls = () => (global.fetch as jest.Mock).mock.calls as [string, RequestInit | undefined][];
const previewBodies = () => fetchCalls()
  .filter(([u, i]) => String(u).endsWith('/api/portfolio/preview') && i?.method === 'POST')
  .map(([, i]) => JSON.parse(String(i!.body)) as Record<string, unknown>);
const creates = () => fetchCalls()
  .filter(([u, i]) => String(u).endsWith('/api/portfolio') && i?.method === 'POST')
  .map(([, i]) => ({ body: JSON.parse(String(i!.body)) as Record<string, unknown>, fingerprint: (i!.headers as Record<string, string>)[REVIEW_FINGERPRINT_HEADER] }));
const settle = (ms = 30) => act(async () => { await new Promise((r) => setTimeout(r, ms)); });

function seed(card: TradeCardData, edits: Partial<ReturnType<typeof emptyCardEdits>> = {}) {
  act(() => {
    useScanStore.setState({
      scanResult: { scan_id: 'flow-scan', timestamp: '2026-09-14T10:00:00', candidates: [card] } as any,
      optionsCardEdits: { ...emptyCardEdits(), scanId: 'flow-scan', ...edits },
      stocksCardEdits: emptyCardEdits(), pickedContracts: {}, contractsBySymbol: {}, scanOverrides: {},
    } as any);
    usePortfolioStore.setState({ positions: [], lastSyncError: null });
    useSettingsStore.setState((s) => ({
      premiumStopPct: 0.6,
      ibkrPaper: { ...s.ibkrPaper, accountId: 'DU123', baseUrl: 'https://localhost:7499/v1/api' },
    }) as any);
    useAutoTradeStore.setState({ selectedBroker: null, autoMode: 'manual', armed: false, lastOrderId: null });
    useDirectSendNotesStore.setState({ notes: [] });
  });
}

beforeEach(() => {
  localStorage.clear();
  jest.clearAllMocks();
  previewReply = echoPreview;
  (api.getStockQuote as jest.Mock).mockResolvedValue({ price: 150 });
  (api.getContractQuote as jest.Mock).mockResolvedValue({ quoteLive: true, price: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100 });
  (api.getStructuralStop as jest.Mock).mockResolvedValue({ available: true, price: 140, source: 'order_block', confidence: 75, distancePct: 6 });
  (api.getExitPlan as jest.Mock).mockResolvedValue(EXIT_PLAN);
  (api.getFirstPassageEstimate as jest.Mock).mockResolvedValue(ESTIMATE);
  (api.postOptionOrder as jest.Mock).mockResolvedValue({ order_id: 'ORD-1', status: 'Submitted', broker: 'ibkr_paper', deduped: false });
  (api.getAutoTradeStatus as jest.Mock).mockResolvedValue({ armed: false });
  installFetch();
});
afterEach(() => {
  cleanup();
  global.fetch = originalFetch;
});

async function renderPage() {
  render(<Step7TradeCardPage />);
  await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
  await settle();
}
async function openBasket() {
  fireEvent.click(await screen.findByRole('button', { name: /pin to basket/i }));
  fireEvent.click(await screen.findByRole('button', { name: /basket \(1\)/i }));
  const dialog = await screen.findByRole('dialog', { name: 'Track basket in Portfolio' });
  await within(dialog).findByText('SERVER-RESOLVED');
  return within(dialog);
}
async function openBrokerReview() {
  fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
  const btn = await screen.findByRole('button', { name: /place limit @/i });
  await waitFor(() => expect(btn).toBeEnabled());
  fireEvent.click(btn);
  return screen.findByRole('region', { name: 'Broker order review' });
}
const reviewRow = (label: string) => {
  const review = screen.getByRole('region', { name: 'Submission review' });
  return within(review).getByText(label).closest('div') as HTMLElement;
};

describe('#584 on-demand calculation', () => {
  it('opening Step 7 runs no calculation and writes nothing', async () => {
    seed(makeCard());
    await renderPage();
    expect(api.getExitPlan).not.toHaveBeenCalled();
    expect(api.getFirstPassageEstimate).not.toHaveBeenCalled();
    expect(fetchCalls().filter(([, i]) => i?.method === 'POST')).toEqual([]);
    expect(api.postOptionOrder).not.toHaveBeenCalled();
  });
});

describe('#584 every exit method reaches the tracking review unchanged', () => {
  const steps: [string, string, (() => Promise<void>)][] = [
    ['Ladder', 'ladder', async () => { fireEvent.click(screen.getByRole('radio', { name: 'Ladder' })); }],
    ['Arithmetic', 'arithmetic', async () => {
      await act(async () => { fireEvent.click(screen.getByRole('button', { name: /compute arithmetic plan/i })); });
      await waitFor(() => expect(screen.getByRole('radio', { name: 'Arithmetic' })).toBeEnabled());
      fireEvent.click(screen.getByRole('radio', { name: 'Arithmetic' }));
    }],
    ['Monte Carlo', 'monte_carlo', async () => {
      await act(async () => { fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i })); });
      await waitFor(() => expect(screen.getByRole('radio', { name: 'Monte Carlo' })).toBeEnabled());
      fireEvent.click(screen.getByRole('radio', { name: 'Monte Carlo' }));
    }],
    ['Barrier Race shortcut', 'barrier_race', async () => {
      await act(async () => { fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i })); });
      fireEvent.click(await screen.findByRole('button', { name: 'Use Barrier Race T25%' }));
    }],
  ];

  it.each(steps)('%s', async (_name, method, choose) => {
    seed(makeCard());
    await renderPage();
    await choose();
    await settle();
    const dialog = await openBasket();
    const submit = dialog.getByRole('button', { name: /^(Add 1 to Portfolio|Override & Submit)$/ });
    await waitFor(() => expect(submit).toBeEnabled());
    const reviewed = previewBodies().at(-1)!;
    expect(reviewed.pickedMethod).toBe(method);
    // The stored request is the reviewed one, with the reviewed fingerprint.
    fireEvent.click(submit);
    await waitFor(() => expect(creates()).toHaveLength(1));
    expect(creates()[0]!.body).toEqual(reviewed);
    expect(creates()[0]!.fingerprint).toBe(previewOf(reviewed).fingerprint);
    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
    expect(usePortfolioStore.getState().positions[0]).toMatchObject({ symbol: 'AAA', pickedMethod: method });
    expect(api.postOptionOrder).not.toHaveBeenCalled();
  });
});

describe('#584 a spread', () => {
  const spread = () => makeCard({
    direction: 'Bearish', spreadType: 'bear_put', netDebitCredit: 1.2, maxProfit: 3.8, maxLoss: 1.2, breakeven: 148.8,
    contractDetails: { strike: 150, expiry: '2026-05-15', right: 'P', mid: 2.5, delta: -0.45, theta: -0.09, ivRank: 45, dte: 24 },
    legs: [
      { action: 'BUY', qty: 1, strike: 150, right: 'P', expiry: '2026-05-15' },
      { action: 'SELL', qty: 1, strike: 145, right: 'P', expiry: '2026-05-15' },
    ],
  } as Partial<TradeCardData>);

  it('reviews the selected contract only, says so, and the basket row is server-reviewed like any other', async () => {
    seed(spread(), { picks: { 'AAA|150|2026-05-15|P': pick() } });
    await renderPage();
    expect(within(screen.getByRole('region', { name: 'Submission review' })).getByText(/only the selected contract is submitted/)).toBeInTheDocument();
    const dialog = await openBasket();
    expect(dialog.getByRole('region', { name: 'Server review AAA' })).toBeInTheDocument();
    const body = previewBodies().at(-1)!;
    expect(String(body.contract)).toContain('150');
    expect(String(body.contract)).not.toContain('145');
    expect(api.postOptionOrder).not.toHaveBeenCalled();
  });
});

describe('#584 edits restored from the persisted slice, then reverted', () => {
  it('the restored values are reviewed and sent; reverting returns to the plan under a new draft', async () => {
    seed(makeCard(), {
      picks: { [AAA_KEY]: pick() }, invalidation: { AAA: 138 }, premiumStop: { [AAA_KEY]: 1.2 }, entryLimit: { [AAA_KEY]: 2.4 },
    });
    await renderPage();

    expect(reviewRow('Stock stop')).toHaveTextContent('$138.00 stock · typed (absolute; not re-anchored)');
    expect(reviewRow('Premium stop')).toHaveTextContent('$1.20/share pinned');
    expect(reviewRow('Entry limit')).toHaveTextContent('$2.40/share');
    const review = screen.getByRole('region', { name: 'Submission review' });
    const firstFingerprint = review.getAttribute('data-fingerprint');
    const firstGeneration = Number(review.getAttribute('data-generation'));

    let dialog = await openBasket();
    expect(previewBodies().at(-1)).toMatchObject({ stop: 138, stopIsUserSet: true, premiumStopDollar: 1.2 });
    fireEvent.click(dialog.getByRole('button', { name: 'Cancel' }));

    fireEvent.click(screen.getByLabelText('Edit Invalidation'));
    const input = screen.getByRole('textbox', { name: 'Edit Invalidation' });
    await act(async () => { fireEvent.change(input, { target: { value: '' } }); fireEvent.blur(input); });

    expect(reviewRow('Stock stop')).toHaveTextContent('$140.00 stock · plan-derived');
    const after = screen.getByRole('region', { name: 'Submission review' });
    expect(after.getAttribute('data-fingerprint')).not.toBe(firstFingerprint);
    expect(Number(after.getAttribute('data-generation'))).toBeGreaterThan(firstGeneration);

    fireEvent.click(await screen.findByRole('button', { name: /basket \(1\)/i }));
    dialog = within(await screen.findByRole('dialog', { name: 'Track basket in Portfolio' }));
    await dialog.findByText('SERVER-RESOLVED');
    expect(previewBodies().at(-1)).toMatchObject({ stop: 140, stopIsUserSet: false, premiumStopDollar: 1.2 });
  });
});

describe('#584 server adjustments on both review surfaces', () => {
  const adjusted = (body: Record<string, unknown>): Reply => ({
    ok: true, status: 200,
    json: async () => previewOf(body, { stop: 141, activeTpMethod: 'ladder', resolvedTpPrice: null }, {
      differences: [
        { field: 'stop', requested: 140, effective: 141, reason: 'reanchored' },
        { field: 'targetAlert', requested: 'monte_carlo', effective: 'ladder', reason: 'ladder_fallback' },
      ],
    }),
  });

  it('the basket row shows the fallback and re-anchor as the server\'s, with its reasons', async () => {
    previewReply = adjusted;
    seed(makeCard(), { picks: { [AAA_KEY]: pick() } });
    await renderPage();
    const dialog = await openBasket();
    const region = dialog.getByRole('region', { name: 'Server review AAA' });
    const target = region.querySelector('[data-field="targetAlert"]') as HTMLElement;
    expect(target).toHaveAttribute('data-adjusted', 'true');
    expect(target).toHaveTextContent('Live Ladder');
    expect(target).toHaveTextContent('Adjusted — falls back to the live Ladder');
    const stop = region.querySelector('[data-field="stop"]') as HTMLElement;
    expect(stop).toHaveTextContent('$141.00');
    expect(stop).toHaveTextContent('Adjusted — re-anchored to the live underlying');
  });

  it('the broker review shows the same server row, and that those are alerts rather than orders', async () => {
    previewReply = adjusted;
    seed(makeCard(), { picks: { [AAA_KEY]: pick() } });
    await renderPage();
    const review = within(await openBrokerReview());
    expect(review.getByText('Target alert').closest('div')).toHaveTextContent('Live Ladder (requested ladder · stock $160.00 — falls back to the live Ladder)');
    expect(review.getByText('Stock stop').closest('div')).toHaveTextContent('$141.00 (requested $140.00 · plan level — re-anchored to the live underlying)');
    expect(review.getByText(/No stop-loss or take-profit order is sent to the broker/)).toBeInTheDocument();
    expect(api.postOptionOrder).not.toHaveBeenCalled();
    expect(creates()).toHaveLength(0);
  });
});

describe('#584 CHECK a — the card review before and beside the server review', () => {
  it('the card says unresolved while the basket shows the server values, and neither borrows from the other', async () => {
    previewReply = (body) => ({
      ok: true, status: 200,
      json: async () => previewOf(body, { activeTpMethod: 'monte_carlo', resolvedTpPrice: 158.5 }),
    });
    seed(makeCard(), { picks: { [AAA_KEY]: pick() } });
    await renderPage();
    expect(reviewRow('Effective target alert')).toHaveTextContent('Unresolved until server review');
    const dialog = await openBasket();
    const region = dialog.getByRole('region', { name: 'Server review AAA' });
    expect(region.querySelector('[data-field="targetAlert"]')).toHaveTextContent('Monte Carlo stock level · stock $158.50');
    expect(reviewRow('Effective target alert')).toHaveTextContent('Unresolved until server review');
    expect(reviewRow('Effective target alert')).not.toHaveTextContent('158.50');
  });
});

describe('#584 CHECK b — a literal "None" or "null" order id from an adapter', () => {
  /* `tradier_paper.py` and `ibkr_paper.py` build `order_id` with str(...), so a
     JSON null id arrives as the text "None", which `routers/broker.py` serves in
     a 200 body and records as outcome-unknown. `classifyDirectFailure` and
     `responseFacts` share `UNUSABLE_ORDER_IDS` (#593), so the banner, the note
     and the outcome panel all agree that no order id was reported. */
  it.each(['None', 'null'])('"%s" keeps the row as an unknown order and the outcome facts report no id', (id) => {
    expect(classifyDirectFailure({ response: { order_id: id, status: 'Submitted' } })).toEqual({
      verdict: 'keep',
      why: 'broker reply had no usable order ID (status Submitted)',
      orderId: null,
    });
    expect(responseFacts({ order_id: id, status: 'Submitted', broker: 'ibkr_paper' }).orderId).toBeNull();
  });

  it.each(['', 'unknown'])('"%s" keeps the row as an unknown order', (id) => {
    expect(classifyDirectFailure({ response: { order_id: id, status: 'Submitted' } }).verdict).toBe('keep');
  });

  it('on the page no order is announced, the outcome says Not reported, and one order-unknown note is raised', async () => {
    (api.postOptionOrder as jest.Mock).mockResolvedValue({ order_id: 'None', status: 'Submitted', broker: 'ibkr_paper', deduped: false });
    seed(makeCard(), { picks: { [AAA_KEY]: pick() } });
    await renderPage();
    const review = await openBrokerReview();
    fireEvent.click(within(review).getByRole('button', { name: /^Send to / }));
    const outcome = within(await screen.findByRole('region', { name: 'Broker order outcome' }));
    expect(outcome.getByText('Order ID').closest('div')).toHaveTextContent('Not reported');
    expect(screen.queryByText(/Order placed — ID: None/)).not.toBeInTheDocument();
    const notes = useDirectSendNotesStore.getState().notes;
    expect(notes).toHaveLength(1);
    expect(notes[0]).toMatchObject({ kind: 'order-unknown', orderId: null });
  });
});
