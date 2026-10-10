import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor, act, cleanup } from '@testing-library/react';
import Step7TradeCardPage from '../page';
import { useScanStore } from '@/lib/scanStore';
import { emptyCardEdits } from '@/lib/cardEdits';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useRiskStore } from '@/lib/riskStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { useAutoTradeStore } from '@/lib/autoTradeStore';
import { useDirectSendNotesStore } from '@/lib/directSendNotesStore';
import { api } from '@/lib/api';
import type { TradeCardData, MethodPick, PortfolioPosition } from '@/types/domain';

/*
 * P1b-i (P1-CARD-SAVE-FIRST-SEND-TRIMMED-2026-09-25) — Step 7's two direct
 * sends SAVE the position first, send the order at the quantity the save
 * approved, delete the saved row only when the broker provably never received
 * the order, and leave a persistent, rec_id-scoped note (with a Remove button)
 * whenever a row may have no order behind it or an order's status is unknown.
 * Test numbers follow the plan (docs/superpowers/plans/
 * 2026-09-25-p1b1-step7-save-first-core-plan.md §5, A4 and X1).
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
  },
}));

const pick = (): MethodPick => ({
  method: 'ladder', rowStockPrice: 160, rowOptionPrice: null, stopBasis: 'stock', pickedAt: '2026-09-14T10:00:00.000Z',
});

const CARD_LIMIT = 2.5;
const AAA_LABEL = 'AAA 150C 05/15/26';
const BBB_LABEL = 'BBB 155C 05/15/26';
const AAA_CONTRACT = 'AAA|150|2026-05-15|C';

function makeCard(symbol: string, mid?: number): TradeCardData {
  const isSecond = symbol === 'BBB';
  const limit = isSecond ? 3.3 : CARD_LIMIT;
  const strike = isSecond ? 155 : 150;
  return {
    symbol, company: `${symbol} Inc.`, price: 150, direction: 'Bullish', status: 'PASS',
    stockScore: 80, stockConfidence: 'PASS',
    stockBreakdown: { trend: 80, pullback: 80, trigger: 80, event: 80, volatility: 80 },
    contract: `${symbol} ${strike}C 05/15`, contractScore: 70, contractConfidence: 'PASS',
    contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 60 },
    contractDetails: { strike, expiry: '2026-05-15', right: 'C', mid: mid ?? limit, delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 },
    entry: { limit, maxFill: 2.63, orderType: 'Limit' },
    exit: { invalidation: isSecond ? 120 : 140, premiumStop: 1.5, timeStopDays: 10, target: 160, targets: [] },
    rrRatio: 2.0, rrModel: 'Heston repriced', finalStatus: 'PASS',
    regimeGate: { headwindCautionPct: -15, headwindRejectPct: -40 },
  };
}

/* ── fetch: the persist POST and the portfolio GET are scriptable ─────────── */

type Reply = { ok: boolean; status?: number; json: () => Promise<unknown> };
/** How the next persist POST answers, given the request body. Default: echo. */
let persistReply: (body: Record<string, unknown>) => Promise<Reply>;
/** Queued replies for `GET /api/portfolio` (default: `{}`, which a sync ignores). */
let getReplies: Array<() => Promise<Reply>>;
/** Shared call-order log (test 1). */
let callLog: string[];
const echo = (body: Record<string, unknown>) => Promise.resolve({ ok: true, status: 201, json: async () => body });
const originalFetch = global.fetch;

function installFetch() {
  global.fetch = jest.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    const u = String(url);
    if (u.endsWith('/api/portfolio') && init?.method === 'POST') {
      callLog.push('persist');
      return persistReply(JSON.parse(String(init.body)));
    }
    if (u.endsWith('/api/portfolio') && (init?.method ?? 'GET') === 'GET') {
      const next = getReplies.shift();
      if (next) return next();
    }
    return { ok: true, json: async () => ({}) };
  }) as unknown as typeof fetch;
}

const persistBodies = () => (global.fetch as jest.Mock).mock.calls
  .filter(([u, init]) => String(u).endsWith('/api/portfolio') && init?.method === 'POST')
  .map(([, init]) => JSON.parse(String(init.body)) as Record<string, unknown>);
const lastRecId = () => String(persistBodies().at(-1)!.recId);
const positions = () => usePortfolioStore.getState().positions;
const notes = () => useDirectSendNotesStore.getState().notes;
const apiErr = (path: string, status: number, detail?: string) =>
  new Error(`API ${path} → ${status}${detail ? `: ${detail}` : ''}`);
const orderErr = (status: number, detail: string) => apiErr('/broker/option-order', status, detail);
const deleteErr = (status: number, detail?: string) => apiErr('/api/portfolio/X', status, detail);
const settle = (ms = 30) => act(async () => { await new Promise((r) => setTimeout(r, ms)); });

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function resetStores(cards: TradeCardData[] = [makeCard('AAA'), makeCard('BBB')]) {
  act(() => {
    useScanStore.setState({
      scanResult: { scan_id: 'test-scan', timestamp: '2026-09-14T10:00:00', candidates: cards } as any,
      optionsCardEdits: {
        ...emptyCardEdits(), scanId: 'test-scan',
        picks: { [AAA_CONTRACT]: pick(), 'BBB|155|2026-05-15|C': pick() },
      },
      stocksCardEdits: emptyCardEdits(), pickedContracts: {}, contractsBySymbol: {}, scanOverrides: {},
    } as any);
    usePortfolioStore.setState({ positions: [], lastSyncError: null });
    useSettingsStore.setState((s) => ({
      ibkrPaper: { ...s.ibkrPaper, accountId: 'ACC', baseUrl: 'https://localhost:7499/v1/api' },
    }) as any);
    useAutoTradeStore.setState({ selectedBroker: null, autoMode: 'manual', armed: false, lastOrderId: null });
    useDirectSendNotesStore.setState({ notes: [] });
  });
}

async function renderPage() {
  render(<Step7TradeCardPage />);
  await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
}

async function send(kind: 'LMT' | 'MKT' = 'LMT') {
  fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
  const btn = await screen.findByRole('button', { name: kind === 'LMT' ? /place limit @/i : /right now — market/i });
  await waitFor(() => expect(btn).toBeEnabled());
  fireEvent.click(btn);
}

/** Send, then wait until the send has fully finished (both buttons enabled). */
async function sendAndSettle(kind: 'LMT' | 'MKT' = 'LMT') {
  await send(kind);
  await waitFor(() => expect(screen.getByRole('button', { name: /place limit @/i })).toBeEnabled());
  await settle();
}

async function goNext() {
  fireEvent.click(screen.getByRole('button', { name: 'Next candidate' }));
  await waitFor(() => expect(screen.getByText('BBB Inc.')).toBeInTheDocument());
}
async function goPrev() {
  fireEvent.click(screen.getByRole('button', { name: 'Previous candidate' }));
  await waitFor(() => expect(screen.getByText('AAA Inc.')).toBeInTheDocument());
}

async function sendBasket() {
  fireEvent.click(await screen.findByRole('button', { name: /pin to basket/i }));
  fireEvent.click(await screen.findByRole('button', { name: /track basket/i }));
  const submit = await screen.findByRole('button', { name: /^(Add \d to Portfolio|Override & Submit)$/ });
  await waitFor(() => expect(submit).toBeEnabled());
  fireEvent.click(submit);
}

const noteText = (re: RegExp) => screen.queryByText(re);
const removeBtn = (label: string) => screen.getByRole('button', { name: `Remove (${label})` });

let confirmSpy: jest.SpyInstance;
let dailyBefore: number;
// Test 15 swaps the store's `addPosition` for a throwing one; the store is
// module-level, so every test starts from the real one.
const realAddPosition = usePortfolioStore.getState().addPosition;

beforeEach(() => {
  localStorage.clear();
  act(() => { usePortfolioStore.setState({ addPosition: realAddPosition }); });
  resetStores();
  jest.clearAllMocks();
  callLog = [];
  persistReply = echo;
  getReplies = [];
  (api.getStockQuote as jest.Mock).mockResolvedValue({ price: 150 });
  (api.getContractQuote as jest.Mock).mockResolvedValue({
    quoteLive: true, price: CARD_LIMIT, delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100,
  });
  (api.postOptionOrder as jest.Mock).mockImplementation(async () => {
    callLog.push('order');
    return { order_id: 'ORD-1', status: 'Submitted' };
  });
  (api.deletePortfolioPosition as jest.Mock).mockResolvedValue(undefined);
  (api.getAutoTradeStatus as jest.Mock).mockResolvedValue({ armed: false });
  installFetch();
  confirmSpy = jest.spyOn(window, 'confirm').mockReturnValue(true);
  dailyBefore = useRiskStore.getState().dailyRecommendations;
});
afterEach(() => {
  cleanup();
  global.fetch = originalFetch;
  confirmSpy.mockRestore();
  act(() => { useRiskStore.setState({ dailyRecommendations: dailyBefore }); });
});


describe('T11 no live quote direct send', () => {
  it.each(['LMT', 'MKT'] as const)('rechecks at send time and refuses %s before saving when the session closes', async (kind) => {
    await renderPage();
    await waitFor(() => expect(screen.queryByLabelText('Confirm sending without a live quote')).not.toBeInTheDocument());
    (api.getContractQuote as jest.Mock).mockResolvedValue({ price: 2.5, spread: 0.1, quoteLive: false, quoteState: 'session_closed' });
    await sendAndSettle(kind);
    expect(persistBodies()).toHaveLength(0);
    expect(api.postOptionOrder).not.toHaveBeenCalled();
    expect(screen.getByText(/No live quote \(market closed\)/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Confirm sending without a live quote'));
    await sendAndSettle(kind);
    expect(api.postOptionOrder).toHaveBeenCalledTimes(1);
  });
  it('unavailable quote and a persisted false flag still warn and require a tick', async () => {
    (api.getContractQuote as jest.Mock).mockRejectedValue(new Error('offline'));
    await renderPage();
    await sendAndSettle();
    expect(screen.getByText(/Live quote unavailable/)).toBeInTheDocument();
    expect(persistBodies()).toHaveLength(0);
    expect(api.postOptionOrder).not.toHaveBeenCalled();
  });
  it('A confirmation never covers B and returning to A clears it', async () => {
    (api.getContractQuote as jest.Mock).mockResolvedValue({ price: 2.5, spread: 0.1, quoteLive: false });
    await renderPage();
    fireEvent.click(await screen.findByLabelText('Confirm sending without a live quote'));
    await goNext();
    await sendAndSettle();
    expect(persistBodies()).toHaveLength(0);
    expect(api.postOptionOrder).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Confirm sending without a live quote')).not.toBeChecked();
    await goPrev();
    expect(screen.getByLabelText('Confirm sending without a live quote')).not.toBeChecked();
  });
  it('navigation while the send quote is pending cancels before save', async () => {
    await renderPage();
    const probe = deferred<any>();
    (api.getContractQuote as jest.Mock).mockReturnValueOnce(probe.promise);
    await send();
    await goNext();
    await act(async () => { probe.resolve({ quoteLive: true, price: 9 }); });
    expect(persistBodies()).toHaveLength(0);
    expect(api.postOptionOrder).not.toHaveBeenCalled();
  });
  it('failed quote recomputes from the picked spread, never a fabricated zero', async () => {
    const row = { id: 'AAA|160|2026-05-15|C', symbol: 'AAA', strike: 160, expiry: '2026-05-15', right: 'C', price: 3, delta: 0.4, theta: -0.1, ivRank: 40, dte: 24, score: 75, contractConfidence: 'CAUTION', spread: 0.37, noLiveQuote: true };
    act(() => useScanStore.setState({ pickedContracts: { AAA: row.id }, contractsBySymbol: { AAA: [row] } } as any));
    (api.getContractQuote as jest.Mock).mockRejectedValue(new Error('offline'));
    (api.recomputePlan as jest.Mock).mockResolvedValue({ entry: makeCard('AAA').entry, exit: makeCard('AAA').exit, rrRatio: 2, rrModel: 'Heston repriced' });
    await renderPage();
    await waitFor(() => expect(api.recomputePlan).toHaveBeenCalledWith(expect.objectContaining({ spread: 0.37, quote_live: false }), expect.anything()));
  });
});

it('audit: an old open-time quote must not overwrite the fresh refused quote', async () => {
 const oldProbe = deferred<any>();
 (api.getContractQuote as jest.Mock).mockReturnValueOnce(oldProbe.promise).mockResolvedValue({quoteLive:false,quoteState:'session_closed',price:9,spread:0.1});
 await renderPage();
 await sendAndSettle();
 expect(persistBodies()).toHaveLength(0);
 expect(screen.getByText(/No live quote \(market closed\)/)).toBeInTheDocument();
 await act(async () => oldProbe.resolve({quoteLive:true,price:1,spread:0.1}));
 expect(screen.getByText(/No live quote \(market closed\)/)).toBeInTheDocument();
 expect(screen.queryByText('Live mid: $1.00')).not.toBeInTheDocument();
});
it('audit: revoking the tick during the send probe refuses the order', async () => {
 (api.getContractQuote as jest.Mock).mockResolvedValue({quoteLive:false,price:2.5,spread:0.1});
 await renderPage();
 fireEvent.click(await screen.findByLabelText('Confirm sending without a live quote'));
 const probe = deferred<any>();
 (api.getContractQuote as jest.Mock).mockReturnValueOnce(probe.promise);
 await send();
 fireEvent.click(screen.getByLabelText('Confirm sending without a live quote'));
 await act(async () => probe.resolve({quoteLive:false,price:2.5,spread:0.1}));
 await settle();
 expect(api.postOptionOrder).not.toHaveBeenCalled();
});
it('audit: an unrelated basket Retry during the send probe must not suppress the fresh refused quote', async () => {
 const row = (sym: 'AAA' | 'BBB') => {
  const strike = sym === 'BBB' ? 155 : 150;
  return { id: `${sym}|${strike}|2026-05-15|C`, symbol: sym, strike, expiry: '2026-05-15', right: 'C', price: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, dte: 24, score: 75, contractConfidence: 'PASS', spread: 0.1 };
 };
 resetStores([makeCard('BBB'), makeCard('AAA')]);
 act(() => useScanStore.setState({
  pickedContracts: { AAA: row('AAA').id, BBB: row('BBB').id },
  contractsBySymbol: { AAA: [row('AAA')], BBB: [row('BBB')] },
 } as any));
 (api.getContractQuote as jest.Mock).mockResolvedValue({quoteLive:true,price:1,spread:0.1});
 (api.recomputePlan as jest.Mock).mockImplementation(async (req: { symbol: string }) => {
  if (req.symbol === 'BBB') throw new Error('plan failed');
  const c = makeCard('AAA');
  return { entry: c.entry, exit: c.exit, rrRatio: 2, rrModel: 'Heston repriced' };
 });
 render(<Step7TradeCardPage />);
 await screen.findByText(/Could not compute the plan for the selected contract/);
 fireEvent.click(await screen.findByRole('button', { name: /pin to basket/i }));
 fireEvent.click(screen.getByRole('button', { name: 'Next candidate' }));
 await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
 await screen.findByText('Live mid: $1.00');
 const retryBbb = await screen.findByRole('button', { name: 'Retry BBB' });
 const probe = deferred<any>();
 (api.getContractQuote as jest.Mock).mockReturnValueOnce(probe.promise);
 await send();
 fireEvent.click(retryBbb);
 await act(async () => probe.resolve({quoteLive:false,quoteState:'session_closed',price:9,spread:0.1}));
 await settle();
 expect(persistBodies()).toHaveLength(0);
 expect(api.postOptionOrder).not.toHaveBeenCalled();
 expect(screen.getByText(/No live quote \(market closed\)/)).toBeInTheDocument();
 expect(screen.getByLabelText('Confirm sending without a live quote')).toBeInTheDocument();
 expect(screen.queryByText('Live mid: $1.00')).not.toBeInTheDocument();
});
