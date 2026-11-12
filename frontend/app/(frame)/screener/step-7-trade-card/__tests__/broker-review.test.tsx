import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor, act, cleanup, within } from '@testing-library/react';
import Step7TradeCardPage from '../page';
import { useScanStore } from '@/lib/scanStore';
import { emptyCardEdits } from '@/lib/cardEdits';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { useAutoTradeStore } from '@/lib/autoTradeStore';
import { useDirectSendNotesStore } from '@/lib/directSendNotesStore';
import { api } from '@/lib/api';
import type { TradeCardData, MethodPick } from '@/types/domain';

/*
 * #583 (TC-REVIEW-08) — a direct send is reviewed against the server's
 * resolution BEFORE anything is saved or sent, and the broker receives the
 * exact request the review showed. Every transport is mocked: `api` is a jest
 * mock and `fetch` answers only the Portfolio endpoints.
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

const AAA_KEY = 'AAA|150|2026-05-15|C';
const AAA_LABEL = 'AAA 150C 05/15/26';
const pick = (): MethodPick => ({
  method: 'ladder', rowStockPrice: 160, rowOptionPrice: null, stopBasis: 'stock', pickedAt: '2026-09-14T10:00:00.000Z',
});

function makeCard(symbol: string): TradeCardData {
  const strike = symbol === 'BBB' ? 155 : 150;
  return {
    symbol, company: `${symbol} Inc.`, price: 150, direction: 'Bullish', status: 'PASS',
    stockScore: 80, stockConfidence: 'PASS',
    stockBreakdown: { trend: 80, pullback: 80, trigger: 80, event: 80, volatility: 80 },
    contract: `${symbol} ${strike}C 05/15`, contractScore: 70, contractConfidence: 'PASS',
    contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 60 },
    contractDetails: { strike, expiry: '2026-05-15', right: 'C', mid: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 },
    entry: { limit: 2.5, maxFill: 2.63, orderType: 'Limit' },
    exit: { invalidation: 140, premiumStop: 1.5, timeStopDays: 10, target: 160, targets: [] },
    rrRatio: 2.0, rrModel: 'Heston repriced', finalStatus: 'PASS',
    regimeGate: { headwindCautionPct: -15, headwindRejectPct: -40 },
  };
}

type Reply = { ok: boolean; status?: number; json: () => Promise<unknown> };
const previewOf = (body: Record<string, unknown>, over: Record<string, unknown> = {}, extra: Record<string, unknown> = {}) => ({
  fingerprint: `v1:${String(body.qty)}:${JSON.stringify(over)}`,
  position: { ...body, id: '', createdAt: '', ...over },
  differences: [],
  ...extra,
});
/** How the next preview answers. Default: the request echoed. */
let previewReply: (body: Record<string, unknown>) => Reply;
/** How the next confirmation answers. Default: the request echoed. */
let persistReply: (body: Record<string, unknown>, headers: Record<string, string>) => Reply;
const echoPreview = (body: Record<string, unknown>): Reply => ({ ok: true, status: 200, json: async () => previewOf(body) });
const echoPersist = (body: Record<string, unknown>): Reply => ({ ok: true, status: 201, json: async () => body });

const originalFetch = global.fetch;
function installFetch() {
  global.fetch = jest.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    const u = String(url);
    if (u.endsWith('/api/portfolio/preview') && init?.method === 'POST') return previewReply(JSON.parse(String(init.body)));
    if (u.endsWith('/api/portfolio') && init?.method === 'POST') {
      return persistReply(JSON.parse(String(init.body)), (init.headers ?? {}) as Record<string, string>);
    }
    return { ok: true, json: async () => ({}) };
  }) as unknown as typeof fetch;
}
const fetchCalls = () => (global.fetch as jest.Mock).mock.calls as [string, RequestInit | undefined][];
const previewBodies = () => fetchCalls()
  .filter(([u, i]) => String(u).endsWith('/api/portfolio/preview') && i?.method === 'POST')
  .map(([, i]) => JSON.parse(String(i!.body)) as Record<string, unknown>);
const persistCalls = () => fetchCalls().filter(([u, i]) => String(u).endsWith('/api/portfolio') && i?.method === 'POST');
const persistBodies = () => persistCalls().map(([, i]) => JSON.parse(String(i!.body)) as Record<string, unknown>);
const settle = (ms = 30) => act(async () => { await new Promise((r) => setTimeout(r, ms)); });

function resetStores() {
  act(() => {
    useScanStore.setState({
      scanResult: { scan_id: 'review-scan', timestamp: '2026-09-14T10:00:00', candidates: [makeCard('AAA'), makeCard('BBB')] } as any,
      optionsCardEdits: { ...emptyCardEdits(), scanId: 'review-scan', picks: { [AAA_KEY]: pick(), 'BBB|155|2026-05-15|C': pick() } },
      stocksCardEdits: emptyCardEdits(), pickedContracts: {}, contractsBySymbol: {}, scanOverrides: {},
    } as any);
    usePortfolioStore.setState({ positions: [], lastSyncError: null });
    useSettingsStore.setState((s) => ({
      premiumStopPct: 0.6,
      ibkrPaper: { ...s.ibkrPaper, accountId: 'DU123', baseUrl: 'https://localhost:7499/v1/api' },
      tradierPaper: { ...s.tradierPaper, token: 'T', accountId: 'TACC' },
    }) as any);
    useAutoTradeStore.setState({ selectedBroker: null, autoMode: 'manual', armed: false, lastOrderId: null });
    useDirectSendNotesStore.setState({ notes: [] });
  });
}

beforeEach(() => {
  localStorage.clear();
  resetStores();
  jest.clearAllMocks();
  previewReply = echoPreview;
  persistReply = echoPersist;
  (api.getStockQuote as jest.Mock).mockResolvedValue({ price: 150 });
  (api.getContractQuote as jest.Mock).mockResolvedValue({
    quoteLive: true, price: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100,
  });
  (api.postOptionOrder as jest.Mock).mockResolvedValue({ order_id: 'ORD-1', status: 'Submitted', broker: 'ibkr_paper', deduped: false });
  (api.deletePortfolioPosition as jest.Mock).mockResolvedValue(undefined);
  (api.getAutoTradeStatus as jest.Mock).mockResolvedValue({ armed: false });
  installFetch();
});
afterEach(() => {
  // No transport outside the mocks: nothing ever fetched a broker URL.
  expect(fetchCalls().every(([u]) => !/\/broker\//.test(String(u)))).toBe(true);
  cleanup();
  global.fetch = originalFetch;
});

async function renderPage() {
  render(<Step7TradeCardPage />);
  await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
  await settle();
}

async function openReview(kind: 'LMT' | 'MKT' = 'LMT', broker = /ibkr paper/i) {
  fireEvent.click(screen.getByRole('button', { name: broker }));
  const btn = await screen.findByRole('button', { name: kind === 'LMT' ? /place limit @/i : /right now — market/i });
  await waitFor(() => expect(btn).toBeEnabled());
  fireEvent.click(btn);
  return screen.findByRole('region', { name: 'Broker order review' });
}
const reviewRegion = () => within(screen.getByRole('region', { name: 'Broker order review' }));
const confirmBtn = () => screen.getByRole('button', { name: /^Send to / });
const exactRequest = () => screen.getByTestId('broker-request').textContent ?? '';

function editField(label: string, to: string) {
  fireEvent.click(screen.getByLabelText(`Edit ${label}`));
  const input = screen.getByLabelText(`Edit ${label}`) as HTMLInputElement;
  fireEvent.change(input, { target: { value: to } });
  fireEvent.keyDown(input, { key: 'Enter' });
}

describe('#583 — the destination-specific review comes before any write', () => {
  it('reviews the server-resolved row and names the destination; nothing is saved or sent yet', async () => {
    await renderPage();
    await openReview();
    expect(previewBodies()).toHaveLength(1);
    expect(previewBodies()[0]).toMatchObject({ orderType: 'LMT', orderLimitPrice: 2.5, contract: AAA_KEY, qty: 1 });
    expect(persistCalls()).toHaveLength(0);
    expect(api.postOptionOrder).not.toHaveBeenCalled();

    const r = reviewRegion();
    expect(r.getByText('IBKR Paper', { selector: 'dd' })).toBeInTheDocument();
    expect(r.getByText(/^Paper$/, { selector: 'dd' })).toBeInTheDocument();
    expect(r.getByText(/DU123/)).toBeInTheDocument();
    expect(r.getByText(new RegExp(`${AAA_LABEL}`))).toBeInTheDocument();
    expect(r.getByText('Limit', { selector: 'dd' })).toBeInTheDocument();
    expect(r.getByText('$2.50', { selector: 'dd' })).toBeInTheDocument();
    expect(r.getByText('DAY', { selector: 'dd' })).toBeInTheDocument();
    // Alert semantics: in-app alerts, never broker protective orders.
    expect(r.getByText(/No stop-loss or take-profit order is sent to the broker/)).toBeInTheDocument();
    // Market price and totals are estimates.
    expect(r.getAllByText(/estimate/i).length).toBeGreaterThan(0);
    expect(confirmBtn()).toHaveTextContent(/^Send to IBKR Paper — Limit 1 @ \$2\.50$/);
  });

  it('a market review says the fill price is unknown until execution', async () => {
    await renderPage();
    await openReview('MKT');
    expect(reviewRegion().getByText(/fills at the market price, unknown until execution/)).toBeInTheDocument();
    expect(confirmBtn()).toHaveTextContent(/^Send to IBKR Paper — Market 1$/);
  });

  it('Cancel closes the review with nothing saved or sent', async () => {
    await renderPage();
    await openReview();
    fireEvent.click(reviewRegion().getByRole('button', { name: 'Cancel' }));
    await settle();
    expect(screen.queryByRole('region', { name: 'Broker order review' })).not.toBeInTheDocument();
    expect(persistCalls()).toHaveLength(0);
    expect(api.postOptionOrder).not.toHaveBeenCalled();
  });
});

describe('#583 — the broker receives exactly the reviewed request', () => {
  it('posts the captured request byte-for-byte, with the saved row\'s durable identity', async () => {
    await renderPage();
    await openReview();
    const shown = exactRequest();
    fireEvent.click(confirmBtn());
    await waitFor(() => expect(api.postOptionOrder).toHaveBeenCalledTimes(1));
    const [sent] = (api.postOptionOrder as jest.Mock).mock.calls[0];
    expect(JSON.stringify(sent)).toBe(shown);
    expect(Object.isFrozen(sent)).toBe(true);
    const recId = String(persistBodies()[0]!.recId);
    expect(previewBodies()[0]!.recId).toBe(recId);
    expect(sent).toMatchObject({ quantity: 1, order_type: 'LMT', limit_price: 2.5, broker: 'ibkr_paper', attempt_id: `opt-${recId}`, saved_rec_id: recId });
    // The confirmation carries the reviewed fingerprint; its body is the previewed body.
    const [, init] = persistCalls()[0]!;
    expect((init!.headers as Record<string, string>)['X-Review-Fingerprint']).toBe(previewOf(previewBodies()[0]!).fingerprint);
    expect(persistBodies()[0]).toEqual(previewBodies()[0]);
    // A direct send never touches the auto-trade path.
    expect(api.armAutoTrade).not.toHaveBeenCalled();
    expect(api.fireAutoTrade).not.toHaveBeenCalled();
  });

  it('a market order to another broker is posted exactly as shown, with no limit', async () => {
    (api.postOptionOrder as jest.Mock).mockResolvedValue({ order_id: 'ORD-2', status: 'Submitted', broker: 'tradier_paper', deduped: false });
    await renderPage();
    await openReview('MKT', /tradier paper/i);
    const shown = exactRequest();
    expect(confirmBtn()).toHaveTextContent(/^Send to Tradier Paper — Market 1$/);
    expect(persistCalls()).toHaveLength(0);
    fireEvent.click(confirmBtn());
    await waitFor(() => expect(api.postOptionOrder).toHaveBeenCalledTimes(1));
    const [sent] = (api.postOptionOrder as jest.Mock).mock.calls[0];
    expect(JSON.stringify(sent)).toBe(shown);
    expect(sent).toMatchObject({ broker: 'tradier_paper', order_type: 'MKT', limit_price: null, quantity: 1 });
    expect(persistBodies()[0]).toMatchObject({ orderType: 'MKT', orderLimitPrice: null });
  });

  it('the server\'s normalised quantity is what is reviewed and sent', async () => {
    previewReply = (body) => ({
      ok: true, status: 200,
      json: async () => previewOf(body, { qty: 2 }, {
        adjustedQty: 2, differences: [{ field: 'qty', requested: 4, effective: 2, reason: 'exposure_resize' }],
      }),
    });
    persistReply = (body) => ({ ok: true, status: 201, json: async () => ({ ...body, qty: 2, adjustedQty: 2 }) });
    await renderPage();
    editField('Contracts', '4');
    await waitFor(() => expect(screen.getByLabelText('Edit Contracts')).toHaveTextContent('4'));
    await openReview();
    expect(reviewRegion().getByText(/requested 4/)).toBeInTheDocument();
    expect(confirmBtn()).toHaveTextContent(/Limit 2 @ \$2\.50$/);
    fireEvent.click(confirmBtn());
    await waitFor(() => expect(api.postOptionOrder).toHaveBeenCalledTimes(1));
    expect((api.postOptionOrder as jest.Mock).mock.calls[0][0].quantity).toBe(2);
    expect(persistBodies()[0]!.qty).toBe(4);
  });

  it('review-required at confirmation sends nothing; the re-review keeps the same saved-row identity', async () => {
    let first = true;
    persistReply = (body) => {
      if (first) {
        first = false;
        return {
          ok: false, status: 412,
          json: async () => ({ detail: { code: 'review_required', preview: previewOf(body, { qty: 2 }, { adjustedQty: 2 }) } }),
        };
      }
      return { ok: true, status: 201, json: async () => ({ ...body, qty: 2, adjustedQty: 2 }) };
    };
    await renderPage();
    await openReview();
    fireEvent.click(confirmBtn());
    await waitFor(() => expect(reviewRegion().getByText(/changed since your review/i)).toBeInTheDocument());
    expect(api.postOptionOrder).not.toHaveBeenCalled();
    expect(api.deletePortfolioPosition).not.toHaveBeenCalled();
    expect(confirmBtn()).toHaveTextContent(/Limit 2 @ \$2\.50$/);
    const reReviewed = exactRequest();

    fireEvent.click(confirmBtn());
    await waitFor(() => expect(api.postOptionOrder).toHaveBeenCalledTimes(1));
    expect(JSON.stringify((api.postOptionOrder as jest.Mock).mock.calls[0][0])).toBe(reReviewed);
    const [a, b] = persistBodies();
    expect(a!.recId).toBe(b!.recId);
    expect((api.postOptionOrder as jest.Mock).mock.calls[0][0]).toMatchObject({
      quantity: 2, attempt_id: `opt-${a!.recId}`, saved_rec_id: a!.recId,
    });
  });

  it('a save at a quantity other than the reviewed one dispatches nothing and removes the row', async () => {
    persistReply = (body) => ({ ok: true, status: 201, json: async () => ({ ...body, qty: 3, adjustedQty: 3 }) });
    await renderPage();
    await openReview();
    fireEvent.click(confirmBtn());
    await waitFor(() => expect(api.deletePortfolioPosition).toHaveBeenCalledWith(String(persistBodies()[0]!.recId)));
    expect(api.postOptionOrder).not.toHaveBeenCalled();
    expect(screen.getByText(new RegExp(`^${AAA_LABEL}: NO order was sent — Portfolio saved 3 contracts but 1 was reviewed`))).toBeInTheDocument();
  });

  it('a card edit after review blocks the send until the review is refreshed', async () => {
    await renderPage();
    await openReview();
    const recId = String(previewBodies()[0]!.recId);
    editField('Limit', '2.71');
    await waitFor(() => expect(reviewRegion().getByText(/Changed since this review/)).toBeInTheDocument());
    expect(confirmBtn()).toBeDisabled();
    fireEvent.click(confirmBtn());
    await settle();
    expect(persistCalls()).toHaveLength(0);

    fireEvent.click(reviewRegion().getByRole('button', { name: 'Refresh review' }));
    await waitFor(() => expect(previewBodies()).toHaveLength(2));
    await waitFor(() => expect(confirmBtn()).toBeEnabled());
    expect(previewBodies()[1]!.recId).toBe(recId);
    expect(confirmBtn()).toHaveTextContent(/Limit 1 @ \$2\.71$/);
    fireEvent.click(confirmBtn());
    await waitFor(() => expect(api.postOptionOrder).toHaveBeenCalledTimes(1));
    expect((api.postOptionOrder as jest.Mock).mock.calls[0][0].limit_price).toBe(2.71);
  });

  it('a broker change after review blocks the send; it is never re-routed silently', async () => {
    await renderPage();
    await openReview();
    fireEvent.click(screen.getByRole('button', { name: /tradier paper/i }));
    await waitFor(() => expect(reviewRegion().getByText(/Changed since this review/)).toBeInTheDocument());
    expect(confirmBtn()).toBeDisabled();
    expect(confirmBtn()).toHaveTextContent(/^Send to IBKR Paper/);
    expect(api.postOptionOrder).not.toHaveBeenCalled();
  });
});

describe('#583 — nothing later rebuilds or bypasses the reviewed request', () => {
  it('a quantity edit after review blocks the send until the review is refreshed', async () => {
    await renderPage();
    await openReview();
    editField('Contracts', '3');
    await waitFor(() => expect(reviewRegion().getByText(/Changed since this review/)).toBeInTheDocument());
    expect(confirmBtn()).toBeDisabled();
    expect(confirmBtn()).toHaveTextContent(/Limit 1 @ \$2\.50$/);
    expect(api.postOptionOrder).not.toHaveBeenCalled();
  });

  it('a quote that lands after the review changes nothing in the shown or posted request', async () => {
    let lateContract!: (v: unknown) => void;
    let lateStock!: (v: unknown) => void;
    (api.getContractQuote as jest.Mock).mockReturnValueOnce(new Promise((r) => { lateContract = r; }));
    (api.getStockQuote as jest.Mock).mockReturnValueOnce(new Promise((r) => { lateStock = r; }));
    await renderPage();
    await openReview();
    const shown = exactRequest();
    await act(async () => {
      lateContract({ quoteLive: true, price: 9.9, delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100 });
      lateStock({ price: 188 });
    });
    await settle();
    expect(exactRequest()).toBe(shown);
    expect(confirmBtn()).toBeEnabled();
    fireEvent.click(confirmBtn());
    await waitFor(() => expect(api.postOptionOrder).toHaveBeenCalledTimes(1));
    expect(JSON.stringify((api.postOptionOrder as jest.Mock).mock.calls[0][0])).toBe(shown);
  });

  it('a global premium-stop change after review does not rewrite the reviewed lines', async () => {
    previewReply = (body) => ({
      ok: true, status: 200,
      json: async () => previewOf(body, {}, {
        differences: [{ field: 'premiumStop', requested: null, effective: 0.6, reason: 'exposure_resize' }],
      }),
    });
    await renderPage();
    await openReview();
    const premiumLine = () => reviewRegion().getByText('Premium stop', { selector: 'dt' }).nextElementSibling?.textContent;
    const before = premiumLine();
    expect(before).toMatch(/60/);
    act(() => { useSettingsStore.setState({ premiumStopPct: 0.25 } as any); });
    await settle();
    expect(premiumLine()).toBe(before);
  });

  it('an earnings veto that arrives while the review is open refuses the send', async () => {
    await renderPage();
    await openReview();
    act(() => {
      useScanStore.setState((s: any) => ({
        scanResult: { ...s.scanResult, candidates: s.scanResult.candidates.map((c: TradeCardData) => ({ ...c, earningsVeto: true })) },
      }) as any);
    });
    await settle();
    const stillOpen = screen.queryByRole('button', { name: /^Send to / });
    if (stillOpen) fireEvent.click(stillOpen);
    await settle();
    expect(persistCalls()).toHaveLength(0);
    expect(api.postOptionOrder).not.toHaveBeenCalled();
  });

  it('a second click on the final action saves and sends once', async () => {
    let releaseSave!: () => void;
    const held = new Promise<void>((r) => { releaseSave = r; });
    persistReply = (body) => ({ ok: true, status: 201, json: async () => { await held; return body; } });
    await renderPage();
    await openReview();
    const confirm = confirmBtn();
    fireEvent.click(confirm);
    await waitFor(() => expect(confirm).toBeDisabled());
    fireEvent.click(confirm);
    await act(async () => { releaseSave(); });
    await waitFor(() => expect(api.postOptionOrder).toHaveBeenCalledTimes(1));
    await settle();
    expect(persistCalls()).toHaveLength(1);
    expect(api.postOptionOrder).toHaveBeenCalledTimes(1);
  });

  it('navigating away while the server review is pending opens no review on the other card', async () => {
    let answer!: (r: Reply) => void;
    const pending = new Promise<Reply>((r) => { answer = r; });
    const asFetch = global.fetch as jest.Mock;
    const original = asFetch.getMockImplementation()!;
    asFetch.mockImplementation(async (url: string, init?: RequestInit) => {
      if (String(url).endsWith('/api/portfolio/preview')) return pending;
      return original(url, init);
    });
    await renderPage();
    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    const limit = await screen.findByRole('button', { name: /place limit @/i });
    await waitFor(() => expect(limit).toBeEnabled());
    fireEvent.click(limit);
    await waitFor(() => expect(previewBodies()).toHaveLength(1));
    fireEvent.click(screen.getByRole('button', { name: 'Next candidate' }));
    await waitFor(() => expect(screen.getByText('BBB Inc.')).toBeInTheDocument());
    await act(async () => { answer(echoPreview(previewBodies()[0]!)); });
    await settle();
    expect(screen.queryByRole('region', { name: 'Broker order review' })).not.toBeInTheDocument();
    expect(persistCalls()).toHaveLength(0);
    expect(api.postOptionOrder).not.toHaveBeenCalled();
  });
});

describe('#583 — a refused or unreachable server review writes nothing', () => {
  async function clickPlaceLimit() {
    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    const limit = await screen.findByRole('button', { name: /place limit @/i });
    await waitFor(() => expect(limit).toBeEnabled());
    fireEvent.click(limit);
  }

  it.each([
    [422, 'Exceeds the premium cap.', /No order was sent — Exceeds the premium cap\.$/],
    [409, 'A position for AAA already exists', /already tracked in Portfolio/],
  ])('preview %i: no save, no order, no note', async (status, detail, banner) => {
    previewReply = () => ({ ok: false, status: status as number, json: async () => ({ detail }) });
    await renderPage();
    await clickPlaceLimit();
    expect(await screen.findByText(banner as RegExp)).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Broker order review' })).not.toBeInTheDocument();
    expect(persistCalls()).toHaveLength(0);
    expect(api.postOptionOrder).not.toHaveBeenCalled();
    expect(useDirectSendNotesStore.getState().notes).toHaveLength(0);
  });

  it('preview unreachable: no save, no order, no note', async () => {
    previewReply = () => { throw new TypeError('Failed to fetch'); };
    await renderPage();
    await clickPlaceLimit();
    expect(await screen.findByText(/No order was sent — the server review could not be reached\./)).toBeInTheDocument();
    expect(persistCalls()).toHaveLength(0);
    expect(api.postOptionOrder).not.toHaveBeenCalled();
    expect(useDirectSendNotesStore.getState().notes).toHaveLength(0);
  });

  it('a 412 without a usable new review still sends nothing', async () => {
    persistReply = () => ({ ok: false, status: 412, json: async () => ({ detail: { code: 'review_required', preview: {} } }) });
    await renderPage();
    await openReview();
    fireEvent.click(confirmBtn());
    expect(await screen.findByText(/No order was sent — HTTP 412\./)).toBeInTheDocument();
    expect(api.postOptionOrder).not.toHaveBeenCalled();
    expect(api.deletePortfolioPosition).not.toHaveBeenCalled();
  });
});

describe('#583 — retry identity', () => {
  it('a rejected send was never placed: the next review is a new saved row and a new attempt', async () => {
    (api.postOptionOrder as jest.Mock).mockResolvedValueOnce({ order_id: 'ORD-R', status: 'Rejected', broker: 'ibkr_paper' });
    await renderPage();
    await openReview();
    fireEvent.click(confirmBtn());
    await waitFor(() => expect(api.deletePortfolioPosition).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByRole('button', { name: /place limit @/i })).toBeEnabled());
    await settle();
    await openReview();
    await waitFor(() => expect(previewBodies()).toHaveLength(2));
    expect(previewBodies()[1]!.recId).not.toBe(previewBodies()[0]!.recId);
    fireEvent.click(confirmBtn());
    await waitFor(() => expect(api.postOptionOrder).toHaveBeenCalledTimes(2));
    const [first, second] = (api.postOptionOrder as jest.Mock).mock.calls.map((c) => c[0]);
    expect(second.attempt_id).not.toBe(first.attempt_id);
    expect(second.saved_rec_id).toBe(previewBodies()[1]!.recId);
  });

  it('an unknown outcome cannot be resent under a new identity: the contract is already tracked', async () => {
    (api.postOptionOrder as jest.Mock).mockRejectedValueOnce(new TypeError('Failed to fetch'));
    await renderPage();
    await openReview();
    fireEvent.click(confirmBtn());
    await waitFor(() => expect(useDirectSendNotesStore.getState().notes).toHaveLength(1));
    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
    await waitFor(() => expect(screen.getByRole('button', { name: /place limit @/i })).toBeEnabled());
    await settle();
    fireEvent.click(screen.getByRole('button', { name: /place limit @/i }));
    expect(await screen.findByText(/already tracked in Portfolio/)).toBeInTheDocument();
    expect(previewBodies()).toHaveLength(1);
    expect(api.postOptionOrder).toHaveBeenCalledTimes(1);
  });
});

describe('#583 — the outcome shows only what the broker response supplies', () => {
  const outcome = () => within(screen.getByRole('region', { name: 'Broker order outcome' }));
  const value = (label: string) => outcome().getByText(label, { selector: 'dt' }).nextElementSibling as HTMLElement;

  it.each([
    ['accepted', { order_id: 'ORD-1', status: 'Submitted', broker: 'ibkr_paper', deduped: false }, /Submitted.*not a fill/],
    ['pending', { order_id: 'ORD-1', status: 'PendingSubmit', broker: 'ibkr_paper', deduped: false }, /PendingSubmit.*not a fill/],
    ['filled reported', { order_id: 'ORD-1', status: 'Filled', broker: 'ibkr_paper', deduped: false }, /Filled.*no fill price or filled quantity/],
  ])('%s: order id and status shown, fill price and quantity unavailable', async (_n, res, status) => {
    (api.postOptionOrder as jest.Mock).mockResolvedValue(res);
    await renderPage();
    await openReview();
    fireEvent.click(confirmBtn());
    await screen.findByRole('region', { name: 'Broker order outcome' });
    expect(value('Order ID')).toHaveTextContent('ORD-1');
    expect(value('Broker status')).toHaveTextContent(status);
    expect(value('Fill price')).toHaveTextContent(/^Unavailable/);
    expect(value('Filled quantity')).toHaveTextContent(/^Unavailable/);
    expect(value('Recorded position')).toHaveTextContent(/1 contract .*\$2\.50.*not a fill/);
    const rec = String(persistBodies()[0]!.recId);
    expect(value('Attempt')).toHaveTextContent(`opt-${rec}`);
    expect(value('Attempt')).toHaveTextContent(rec);
  });

  it('duplicate: the replayed result is said to be the stored one, no second order', async () => {
    (api.postOptionOrder as jest.Mock).mockResolvedValue({ order_id: 'ORD-1', status: 'Submitted', broker: 'ibkr_paper', deduped: true });
    await renderPage();
    await openReview();
    fireEvent.click(confirmBtn());
    await screen.findByRole('region', { name: 'Broker order outcome' });
    expect(value('Deduplicated')).toHaveTextContent(/no second order/);
  });

  it('rejected: the saved row is removed, as before', async () => {
    (api.postOptionOrder as jest.Mock).mockResolvedValue({ order_id: 'ORD-R', status: 'Rejected', broker: 'ibkr_paper' });
    await renderPage();
    await openReview();
    fireEvent.click(confirmBtn());
    await screen.findByRole('region', { name: 'Broker order outcome' });
    expect(value('Broker status')).toHaveTextContent(/^Not placed — broker status Rejected/);
    expect(api.deletePortfolioPosition).toHaveBeenCalledWith(String(persistBodies()[0]!.recId));
    expect(screen.getByText(new RegExp(`^${AAA_LABEL}: Order NOT placed: .*The tracked position was removed\\.$`))).toBeInTheDocument();
    expect(usePortfolioStore.getState().positions).toHaveLength(0);
  });

  it('unknown: the row stays with its ORDER-UNKNOWN note, nothing inferred', async () => {
    (api.postOptionOrder as jest.Mock).mockRejectedValue(new TypeError('Failed to fetch'));
    await renderPage();
    await openReview();
    fireEvent.click(confirmBtn());
    await screen.findByRole('region', { name: 'Broker order outcome' });
    expect(value('Broker status')).toHaveTextContent(/^Unknown/);
    expect(value('Order ID')).toHaveTextContent('Not reported');
    expect(useDirectSendNotesStore.getState().notes).toEqual([
      expect.objectContaining({ kind: 'order-unknown', recId: String(persistBodies()[0]!.recId) }),
    ]);
  });

  it('an unconfirmed save still leaves its SAVE-UNCONFIRMED note and sends nothing', async () => {
    persistReply = () => { throw new TypeError('Failed to fetch'); };
    await renderPage();
    await openReview();
    fireEvent.click(confirmBtn());
    await waitFor(() => expect(useDirectSendNotesStore.getState().notes).toHaveLength(1));
    expect(useDirectSendNotesStore.getState().notes[0]).toMatchObject({ kind: 'save-unconfirmed' });
    expect(api.postOptionOrder).not.toHaveBeenCalled();
  });
});

/* #609 — the destination review was re-arranged for reading only. For fixed
 * inputs the preview body, the saved body and the broker order stay byte-for-
 * byte what they were before (only the per-click stamps are normalised). */
const STAMPS = new Set(['entryDate', 'orderedAt', 'recId', 'attempt_id', 'saved_rec_id']);
const normalised = (v: unknown) => JSON.stringify(v, (k, x) => (STAMPS.has(k) ? '<stamp>' : x));
const DIRECT_PERSIST_BODY = '{"recId":"<stamp>","symbol":"AAA","contract":"AAA|150|2026-05-15|C","direction":"Bullish","entryPrice":2.5,"qty":1,"entryDate":"<stamp>","stop":140,"structuralStop":null,"exitPlan":null,"maxLossOverride":null,"premiumStopDollar":null,"premiumStopPct":null,"targets":[],"dteTotal":24,"portfolioValue":100000,"scanStockPrice":150,"stopIsUserSet":false,"tradeCardSnapshot":{"stockScore":80,"stockConfidence":"PASS","stockBreakdown":{"trend":80,"pullback":80,"trigger":80,"event":80,"volatility":80},"contractScore":70,"contractConfidence":"PASS","contractBreakdown":{"dteFit":80,"delta":65,"ivAttractiveness":55,"liquidity":75,"spread":60},"rrRatio":2,"rrModel":"Heston repriced","strike":150},"pickedMethod":"ladder","pickedRowStockPrice":160,"pickedRowOptionPrice":null,"pickedStopBasis":"stock","pickedAt":"2026-09-14T10:00:00.000Z","holdMaxDays":null,"orderType":"LMT","orderLimitPrice":2.5}';
const DIRECT_ORDER = '{"broker":"ibkr_paper","symbol":"AAA","option_symbol":"AAA|150|2026-05-15|C","action":"BUY","effect":"OPEN","quantity":1,"order_type":"LMT","limit_price":2.5,"tif":"DAY","attempt_id":"<stamp>","saved_rec_id":"<stamp>"}';

describe('#609 — direct-send request parity after the review re-arrangement', () => {
  it('previews, saves and sends byte-identical bodies for the same inputs', async () => {
    await renderPage();
    await openReview();
    fireEvent.click(confirmBtn());
    await waitFor(() => expect(api.postOptionOrder).toHaveBeenCalledTimes(1));
    expect(normalised(previewBodies()[0])).toBe(DIRECT_PERSIST_BODY);
    expect(normalised(persistBodies()[0])).toBe(DIRECT_PERSIST_BODY);
    expect(normalised((api.postOptionOrder as jest.Mock).mock.calls[0][0])).toBe(DIRECT_ORDER);
  });
});
