import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor, act, within, cleanup } from '@testing-library/react';
import Step7TradeCardPage from '../page';
import { useScanStore } from '@/lib/scanStore';
import { emptyCardEdits } from '@/lib/cardEdits';
import { usePortfolioStore, REVIEW_FINGERPRINT_HEADER } from '@/lib/portfolioStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { useAutoTradeStore } from '@/lib/autoTradeStore';
import { useDirectSendNotesStore } from '@/lib/directSendNotesStore';
import { useRiskStore } from '@/lib/riskStore';
import { api } from '@/lib/api';
import type { MethodPick, TradeCardData } from '@/types/domain';

/*
 * #582 (TC-REVIEW-07) — Step 7's Track basket confirms exactly the values the
 * server reviewed. Rows the server saved leave the basket and adopt the saved
 * row at once; a row whose resolution changed (e.g. an earlier row took the
 * capacity, or the quote moved) is NOT saved and stays for re-review; a network
 * failure queues the row under its ORIGINAL fingerprint. No broker order, ever.
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
const ladderPick = (): MethodPick => ({ method: 'ladder', rowStockPrice: 160, rowOptionPrice: null, stopBasis: 'stock', pickedAt: '2026-09-14T10:00:00.000Z' });

function makeCard(symbol: string): TradeCardData {
  const isSecond = symbol === 'BBB';
  const strike = isSecond ? 155 : 150;
  const mid = isSecond ? 3.3 : 2.5;
  return {
    symbol, company: `${symbol} Inc.`, price: 150, direction: 'Bullish', status: 'PASS',
    stockScore: 80, stockConfidence: 'PASS',
    stockBreakdown: { trend: 80, pullback: 80, trigger: 80, event: 80, volatility: 80 },
    contract: `${symbol} ${strike}C 05/15`, contractScore: 70, contractConfidence: 'PASS',
    contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 60 },
    contractDetails: { strike, expiry: '2026-05-15', right: 'C', mid, delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 },
    entry: { limit: mid, maxFill: mid + 0.1, orderType: 'Limit' },
    exit: {
      invalidation: isSecond ? 120 : 140, premiumStop: 1.5, timeStopDays: 10, target: 160,
      targets: [{ id: 'tp1', stockPrice: 160, targetPrice: 160, estimatedOptionPrice: 4.1, contractsToSell: 1 }] as never,
    },
    rrRatio: 2.0, rrModel: 'Heston repriced', finalStatus: 'PASS',
    regimeGate: { headwindCautionPct: -15, headwindRejectPct: -40 },
  };
}

/** The server's resolution of a request: re-quoted (+0.20), stop re-anchored (+1). */
function resolved(body: Record<string, unknown>, extra = 0) {
  return {
    ...body, id: '', createdAt: '',
    entryPrice: Math.round((Number(body.entryPrice) + 0.2 + extra) * 100) / 100,
    stop: Number(body.stop) + 1,
    targets: (body.targets as Array<Record<string, number>>).map((t) => ({ ...t, stockPrice: t.stockPrice + 1, targetPrice: (t.targetPrice ?? t.stockPrice) + 1 })),
    premiumStopPct: null, activeTpMethod: 'ladder', resolvedTpPrice: null,
  };
}
const previewOf = (body: Record<string, unknown>, fingerprint: string, extra = 0) => ({
  fingerprint, position: resolved(body, extra), entryFromLiveQuote: true, inheritedPremiumStopPct: 0.6,
  differences: [{ field: 'stop', requested: body.stop, effective: Number(body.stop) + 1, reason: 'reanchored' }],
});

type CreateBehaviour = (body: Record<string, unknown>, fingerprint: string | undefined) => { status: number; body?: unknown } | 'network';
let onCreate: CreateBehaviour;
const fingerprintFor = (body: Record<string, unknown>, generation: number) => `v1:${body.symbol}:${body.qty}:${generation}`;
let generation: Record<string, number>;

const originalFetch = global.fetch;
function setup() {
  act(() => {
    useScanStore.setState({
      scanResult: { scan_id: 'basket-scan', timestamp: '2026-09-14T10:00:00', candidates: [makeCard('AAA'), makeCard('BBB')] } as never,
      optionsCardEdits: { ...emptyCardEdits(), scanId: 'basket-scan', picks: { [AAA_KEY]: ladderPick(), [BBB_KEY]: ladderPick() } },
      stocksCardEdits: emptyCardEdits(), pickedContracts: {}, contractsBySymbol: {}, scanOverrides: {},
    } as never);
    usePortfolioStore.setState({ positions: [], lastSyncError: null });
    useRiskStore.setState({ dailyRecommendations: 0 });
    useSettingsStore.setState({ premiumStopPct: 0.6 } as never);
    useAutoTradeStore.setState({ selectedBroker: null, autoMode: 'manual', armed: false, lastOrderId: null });
    useDirectSendNotesStore.setState({ notes: [] });
  });
  jest.clearAllMocks();
  generation = { AAA: 1, BBB: 1 };
  (api.getStockQuote as jest.Mock).mockResolvedValue({ price: 151 });
  (api.getContractQuote as jest.Mock).mockResolvedValue({ quoteLive: true, price: 2.6, delta: 0.45, theta: -0.09, ivRank: 45, iv: 0.3, spread: 0.1, volume: 100 });
  (api.getAutoTradeStatus as jest.Mock).mockResolvedValue({ armed: false });
  onCreate = (body, fp) => (fp === fingerprintFor(body, generation[String(body.symbol)]!)
    ? { status: 201, body: resolved(body) }
    : { status: 412, body: { detail: { code: 'review_required', preview: previewOf(body, fingerprintFor(body, generation[String(body.symbol)]!)) } } });
  global.fetch = jest.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    const u = String(url);
    if (u.endsWith('/api/portfolio/preview') && init?.method === 'POST') {
      const body = JSON.parse(String(init.body));
      return { ok: true, status: 200, json: async () => previewOf(body, fingerprintFor(body, generation[body.symbol]!)) };
    }
    if (u.endsWith('/api/portfolio') && init?.method === 'POST') {
      const body = JSON.parse(String(init.body));
      const reply = onCreate(body, (init.headers as Record<string, string>)[REVIEW_FINGERPRINT_HEADER]);
      if (reply === 'network') throw new TypeError('Failed to fetch');
      return { ok: reply.status < 300, status: reply.status, json: async () => reply.body ?? {} };
    }
    if (u.endsWith('/api/portfolio')) return { ok: true, status: 200, json: async () => [] };
    return { ok: true, json: async () => ({}) };
  }) as unknown as typeof fetch;
}

const creates = () => (global.fetch as jest.Mock).mock.calls
  .filter(([u, init]) => String(u).endsWith('/api/portfolio') && init?.method === 'POST')
  .map(([, init]) => ({ body: JSON.parse(String(init.body)), fingerprint: (init.headers as Record<string, string>)[REVIEW_FINGERPRINT_HEADER] }));
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 20)); });

async function openBasketWithBoth() {
  render(<Step7TradeCardPage />);
  await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
  await settle();
  fireEvent.click(await screen.findByRole('button', { name: /pin to basket/i }));
  fireEvent.click(screen.getByRole('button', { name: 'Next candidate' }));
  await waitFor(() => expect(screen.getByText('BBB Inc.')).toBeInTheDocument());
  fireEvent.click(await screen.findByRole('button', { name: /pin to basket/i }));
  fireEvent.click(await screen.findByRole('button', { name: /basket \(2\)/i }));
}

describe('#582 Step 7 — Track basket confirms server-reviewed values', () => {
  beforeEach(() => { localStorage.clear(); setup(); });
  afterEach(() => { cleanup(); global.fetch = originalFetch; });

  it('a partial basket keeps the saved row and re-reviews the changed one; no broker order', async () => {
    await openBasketWithBoth();
    const dialog = within(screen.getByRole('dialog', { name: 'Track basket in Portfolio' }));
    const submit = dialog.getByRole('button', { name: /^(Add 2 to Portfolio|Override & Submit)$/ });
    await waitFor(() => expect(submit).toBeEnabled());
    // The capacity changes after review for BBB only (e.g. AAA used it).
    generation.BBB = 2;
    fireEvent.click(submit);

    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
    // AAA was saved and adopted IMMEDIATELY with the server's levels.
    const [aaa] = usePortfolioStore.getState().positions;
    expect(aaa).toMatchObject({ symbol: 'AAA', stop: 141, syncStatus: 'synced', source: 'manual' });
    expect(aaa!.targets[0]).toMatchObject({ stockPrice: 161 });
    // BBB was not saved: the dialog stays, with BBB only, showing the change.
    const left = within(await screen.findByRole('dialog', { name: 'Track basket in Portfolio' }));
    expect(left.queryByRole('region', { name: 'Server review AAA' })).not.toBeInTheDocument();
    expect(within(left.getByRole('region', { name: 'Server review BBB' })).getByText(/Changed since your review — nothing was saved/)).toBeInTheDocument();
    const again = left.getByRole('button', { name: /^(Add 1 to Portfolio|Override & Submit)$/ });
    await waitFor(() => expect(again).toBeEnabled());
    fireEvent.click(again);
    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(2));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Track basket in Portfolio' })).not.toBeInTheDocument());

    const sent = creates();
    expect(sent.map((c) => [c.body.symbol, c.fingerprint])).toEqual([
      ['AAA', 'v1:AAA:1:1'], ['BBB', 'v1:BBB:1:1'], ['BBB', 'v1:BBB:1:2'],
    ]);
    // Same request, same recId, from review to re-confirmation.
    expect(sent[1]!.body.recId).toBe(sent[2]!.body.recId);
    expect(api.postOptionOrder).not.toHaveBeenCalled();
  });

  it('a network failure queues the row under its original fingerprint, and the retry carries it', async () => {
    await openBasketWithBoth();
    const dialog = within(screen.getByRole('dialog', { name: 'Track basket in Portfolio' }));
    const submit = dialog.getByRole('button', { name: /^(Add 2 to Portfolio|Override & Submit)$/ });
    await waitFor(() => expect(submit).toBeEnabled());
    onCreate = () => 'network';
    fireEvent.click(submit);
    expect(await screen.findByText('2 awaiting backend sync')).toBeInTheDocument();
    const queued = usePortfolioStore.getState().positions;
    expect(queued.map((p) => [p.symbol, p.syncStatus, p.reviewFingerprint])).toEqual([
      ['AAA', 'pending', 'v1:AAA:1:1'], ['BBB', 'pending', 'v1:BBB:1:1'],
    ]);

    // The quote moves before the retry: the retry may not approve it.
    generation.AAA = 2;
    onCreate = (body, fp) => (fp === fingerprintFor(body, generation[String(body.symbol)]!)
      ? { status: 201, body: resolved(body) }
      : { status: 412, body: { detail: { code: 'review_required', preview: previewOf(body, 'v1:moved', 0.4) } } });
    await act(async () => { await usePortfolioStore.getState().syncFromBackend(true); });
    const retries = creates().slice(2);
    expect(retries.map((c) => [c.body.symbol, c.fingerprint])).toEqual([['AAA', 'v1:AAA:1:1'], ['BBB', 'v1:BBB:1:1']]);
    expect(usePortfolioStore.getState().positions.map((p) => [p.symbol, p.syncStatus])).toEqual([['BBB', 'synced']]);
    expect(usePortfolioStore.getState().lastSyncError?.detail).toMatch(/changed since you reviewed/);
    expect(api.postOptionOrder).not.toHaveBeenCalled();
  });
});
