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
 * #591 / #612 (DIRECT-SEND-EXPIRY-PLACEHOLDER) — Place Limit and Right Now —
 * Market used to store `cd?.expiry ?? '2026-12-31'` on the Portfolio row when
 * the selected contract carried no expiry. Both direct sends now refuse such a
 * contract with a reselect-contract reason, BEFORE the quote probe, the server
 * preview, the Portfolio save or the broker order. A contract with a supplied
 * expiry still goes through the reviewed, save-first route unchanged.
 *
 * Every transport is mocked: `api` is a jest mock and `fetch` answers only the
 * Portfolio endpoints.
 */

jest.setTimeout(15_000);

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

const EXPIRY_REASON = /no expiry date.*reselect the contract/i;
/** The send handler's refusal banner (an exact match, so the review's own
 *  "refused before sending: …" line is not counted). */
const EXPIRY_BANNER = 'This contract has no expiry date — reselect the contract in Step 6 before sending.';
const AAA_KEY = 'AAA|150|2026-05-15|C';
const DISPLAY = 'AAA 150C 05/15';
/** The key the page's edit caches (and so the method pick) use when the strict
 *  contract key cannot be built: `${symbol}|${card.contract}`. */
const FALLBACK_KEY = `AAA|${DISPLAY}`;

const pick = (): MethodPick => ({
  method: 'ladder', rowStockPrice: 160, rowOptionPrice: null, stopBasis: 'stock', pickedAt: '2026-09-14T10:00:00.000Z',
});

const DETAILS = { strike: 150, expiry: '2026-05-15', right: 'C' as const, mid: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 };

function makeCard(o: Partial<TradeCardData> = {}): TradeCardData {
  return {
    symbol: 'AAA', company: 'AAA Inc.', price: 150, direction: 'Bullish', status: 'PASS',
    stockScore: 80, stockConfidence: 'PASS',
    stockBreakdown: { trend: 80, pullback: 80, trigger: 80, event: 80, volatility: 80 },
    contract: DISPLAY, contractScore: 70, contractConfidence: 'PASS',
    contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 60 },
    contractDetails: { ...DETAILS },
    entry: { limit: 2.5, maxFill: 2.63, orderType: 'Limit' },
    exit: { invalidation: 140, premiumStop: 1.5, timeStopDays: 10, target: 160, targets: [] },
    rrRatio: 2.0, rrModel: 'Heston repriced', finalStatus: 'PASS',
    regimeGate: { headwindCautionPct: -15, headwindRejectPct: -40 },
    ...o,
  };
}

const withExpiry = (expiry: unknown) => makeCard({ contractDetails: { ...DETAILS, expiry: expiry as string } });

/** Each unavailable-expiry card, and the method-pick key under which its send
 *  buttons are enabled (so the HANDLER, not just a disabled button, is tested). */
const UNAVAILABLE: Array<[string, TradeCardData, string]> = [
  ['missing contractDetails', makeCard({ contractDetails: undefined }), FALLBACK_KEY],
  ['null expiry', withExpiry(null), FALLBACK_KEY],
  ['undefined expiry', withExpiry(undefined), FALLBACK_KEY],
  ['empty expiry', withExpiry(''), FALLBACK_KEY],
  // A whitespace string is truthy, so the strict key is built from it.
  ['whitespace-only expiry', withExpiry('   '), 'AAA|150|   |C'],
];

type Reply = { ok: boolean; status?: number; json: () => Promise<unknown> };
const originalFetch = global.fetch;
function installFetch() {
  global.fetch = jest.fn().mockImplementation(async (url: string, init?: RequestInit): Promise<Reply> => {
    const u = String(url);
    if (u.endsWith('/api/portfolio/preview') && init?.method === 'POST') {
      const body = JSON.parse(String(init.body));
      return { ok: true, status: 200, json: async () => ({ fingerprint: `v1:${body.recId}`, position: { ...body, id: '', createdAt: '' }, differences: [] }) };
    }
    if (u.endsWith('/api/portfolio') && init?.method === 'POST') {
      const body = JSON.parse(String(init.body));
      return { ok: true, status: 201, json: async () => body };
    }
    return { ok: true, json: async () => ({}) };
  }) as unknown as typeof fetch;
}
const fetchCalls = () => (global.fetch as jest.Mock).mock.calls as [string, RequestInit | undefined][];
const previewBodies = () => fetchCalls()
  .filter(([u, i]) => String(u).endsWith('/api/portfolio/preview') && i?.method === 'POST')
  .map(([, i]) => JSON.parse(String(i!.body)) as Record<string, unknown>);
const persistBodies = () => fetchCalls()
  .filter(([u, i]) => String(u).endsWith('/api/portfolio') && i?.method === 'POST')
  .map(([, i]) => JSON.parse(String(i!.body)) as Record<string, unknown>);
const quoteCalls = () => (api.getContractQuote as jest.Mock).mock.calls.length;
const settle = (ms = 30) => act(async () => { await new Promise((r) => setTimeout(r, ms)); });

function setup(card: TradeCardData, picks: Record<string, MethodPick>) {
  act(() => {
    useScanStore.setState({
      scanResult: { scan_id: 'expiry-scan', timestamp: '2026-09-14T10:00:00', candidates: [card] } as any,
      optionsCardEdits: { ...emptyCardEdits(), scanId: 'expiry-scan', picks },
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
  fireEvent.click(screen.getByText('What Track basket and direct sends will submit'));
}

const sendButton = (kind: 'LMT' | 'MKT') =>
  screen.getByRole('button', { name: kind === 'LMT' ? /place limit @/i : /right now — market/i });

describe('#612 — a contract with no supplied expiry is refused before anything is sent', () => {
  it.each(UNAVAILABLE)('%s: the review states the refusal on both direct routes', async (_n, card, pickKey) => {
    setup(card, { [pickKey]: pick() });
    await renderPage();
    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    const review = within(await screen.findByRole('region', { name: 'Submission review' }));
    await waitFor(() => expect(review.getAllByText(/refused before sending:/)).toHaveLength(2));
    for (const line of review.getAllByText(/refused before sending:/)) {
      expect(line.textContent).toMatch(EXPIRY_REASON);
      expect(line.textContent).not.toContain('2026-12-31');
    }
  });

  it.each(UNAVAILABLE.flatMap(([n, c, k]) => [[n, 'LMT', c, k], [n, 'MKT', c, k]] as Array<[string, 'LMT' | 'MKT', TradeCardData, string]>))(
    '%s, %s: a clear refusal and ZERO quote / preview / save / order calls',
    async (_n, kind, card, pickKey) => {
      setup(card, { [pickKey]: pick() });
      await renderPage();
      fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
      const btn = sendButton(kind);
      // The button is clickable: the refusal below is the handler's, not a disabled button's.
      await waitFor(() => expect(btn).toBeEnabled());
      const quotesBefore = quoteCalls();
      fireEvent.click(btn);
      await settle(60);
      expect(quoteCalls()).toBe(quotesBefore);
      expect(previewBodies()).toHaveLength(0);
      expect(persistBodies()).toHaveLength(0);
      expect(api.postOptionOrder).not.toHaveBeenCalled();
      expect(screen.getByText(EXPIRY_BANNER)).toBeInTheDocument();
      expect(api.deletePortfolioPosition).not.toHaveBeenCalled();
      expect(usePortfolioStore.getState().positions).toHaveLength(0);
      expect(useDirectSendNotesStore.getState().notes).toHaveLength(0);
      expect(screen.queryByRole('region', { name: 'Broker order review' })).not.toBeInTheDocument();
    },
  );

  it.each(['LMT', 'MKT'] as const)('%s with a supplied expiry still reaches the reviewed save-first route, payload unchanged', async (kind) => {
    setup(makeCard(), { [AAA_KEY]: pick() });
    await renderPage();
    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    const btn = sendButton(kind);
    await waitFor(() => expect(btn).toBeEnabled());
    fireEvent.click(btn);
    const region = within(await screen.findByRole('region', { name: 'Broker order review' }));
    expect(previewBodies()).toHaveLength(1);
    expect(previewBodies()[0]).toMatchObject({ contract: AAA_KEY, orderType: kind });
    expect(persistBodies()).toHaveLength(0);
    fireEvent.click(region.getByRole('button', { name: /^Send to / }));
    await waitFor(() => expect(api.postOptionOrder).toHaveBeenCalledTimes(1));
    expect(persistBodies()).toHaveLength(1);
    expect(persistBodies()[0]).toEqual(previewBodies()[0]);
    expect(persistBodies()[0]).toMatchObject({ contract: AAA_KEY });
    // The expiry is local row metadata (the POST body carries the contract id): the row keeps the supplied one.
    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
    expect(usePortfolioStore.getState().positions[0]).toMatchObject({ contract: AAA_KEY, expiry: '2026-05-15' });
    expect((api.postOptionOrder as jest.Mock).mock.calls[0][0]).toMatchObject({
      broker: 'ibkr_paper', symbol: 'AAA', option_symbol: AAA_KEY, action: 'BUY', effect: 'OPEN',
      quantity: 1, order_type: kind, limit_price: kind === 'LMT' ? 2.5 : null, tif: 'DAY',
    });
  });
});

describe('#612 — a review captured with an expiry cannot submit once the expiry disappears', () => {
  it.each([
    ['empty', '', FALLBACK_KEY],
    ['whitespace-only', '   ', 'AAA|150|   |C'],
  ])('known → %s expiry: the open review cannot save or send, and its refresh is refused', async (_n, gone, goneKey) => {
    setup(makeCard(), { [AAA_KEY]: pick(), [goneKey]: pick() });
    await renderPage();
    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    const btn = sendButton('LMT');
    await waitFor(() => expect(btn).toBeEnabled());
    fireEvent.click(btn);
    await screen.findByRole('region', { name: 'Broker order review' });
    expect(previewBodies()).toHaveLength(1);
    const quotesBefore = quoteCalls();

    // The scan's contract loses its expiry while the review is open.
    act(() => {
      useScanStore.setState((s: any) => ({
        scanResult: { ...s.scanResult, candidates: [withExpiry(gone)] },
      }) as any);
    });
    await settle();

    const confirm = screen.queryByRole('button', { name: /^Send to / });
    if (confirm) {
      expect(confirm).toBeDisabled();
      fireEvent.click(confirm);
      await settle();
    }
    expect(persistBodies()).toHaveLength(0);
    expect(api.postOptionOrder).not.toHaveBeenCalled();

    const refresh = screen.queryByRole('button', { name: 'Refresh review' });
    if (refresh) {
      fireEvent.click(refresh);
      await settle(60);
    }
    // Whatever route reaches the handler now, nothing new is probed, previewed, saved or sent.
    expect(previewBodies()).toHaveLength(1);
    expect(persistBodies()).toHaveLength(0);
    expect(api.postOptionOrder).not.toHaveBeenCalled();
    expect(usePortfolioStore.getState().positions).toHaveLength(0);
    if (refresh) {
      expect(screen.getByText(EXPIRY_BANNER)).toBeInTheDocument();
      // The live-quote effect may re-probe the changed contract on its own; the send must not.
      expect(quoteCalls() - quotesBefore).toBeLessThanOrEqual(1);
    }
    const stillOpen = screen.queryByRole('button', { name: /^Send to / });
    if (stillOpen) {
      fireEvent.click(stillOpen);
      await settle();
    }
    expect(persistBodies()).toHaveLength(0);
    expect(api.postOptionOrder).not.toHaveBeenCalled();
  });
});
