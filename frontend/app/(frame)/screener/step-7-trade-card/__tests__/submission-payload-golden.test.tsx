import '@testing-library/jest-dom';
import fs from 'fs';
import path from 'path';
import { render, screen, fireEvent, waitFor, act, cleanup } from '@testing-library/react';
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
 * #581 — OUTBOUND PAYLOAD PARITY GUARD.
 *
 * The submission draft extracted the two request builders (`positionFromOrder`
 * for Track basket, `buildPaperPosition` + the `postOptionOrder` body for the
 * direct sends) out of the page. That move must not change one byte of what
 * leaves the browser for the same inputs. The golden file beside this test was
 * RECORDED FROM THE PRE-EXTRACTION BUILDERS (commit d538f27b) by running this
 * suite with RECORD_SUBMISSION_GOLDEN=1, and is compared byte-for-byte here.
 *
 * Only the three stamps that are wall-clock or random by design are masked:
 * `recId`, `orderedAt`, `entryDate` (and the optimistic row's
 * `syncPendingSince` and `syncedAt`). Key ORDER is preserved by the mask, so the comparison is
 * of the serialized string, not a deep-equal that would ignore order.
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

const GOLDEN = path.join(__dirname, 'fixtures', 'submission-payload-golden.json');
const RECORD = process.env.RECORD_SUBMISSION_GOLDEN === '1';
const AAA_KEY = 'AAA|150|2026-05-15|C';

const pick = (row = 160): MethodPick => ({
  method: 'ladder', rowStockPrice: row, rowOptionPrice: null, stopBasis: 'premium', pickedAt: '2026-09-14T10:00:00.000Z',
});

function makeCard(symbol: string, mid = 2.5): TradeCardData {
  const isSecond = symbol === 'BBB';
  const strike = isSecond ? 155 : 150;
  return {
    symbol, company: `${symbol} Inc.`, price: 150, direction: 'Bullish', status: 'PASS',
    stockScore: 80, stockConfidence: 'PASS',
    stockBreakdown: { trend: 80, pullback: 80, trigger: 80, event: 80, volatility: 80 },
    contract: `${symbol} ${strike}C 05/15`, contractScore: 70, contractConfidence: 'PASS',
    contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 60 },
    contractDetails: { strike, expiry: '2026-05-15', right: 'C', mid, delta: 0.45, theta: -0.09, ivRank: 45, iv: 0.31, dte: 24 },
    entry: { limit: mid, maxFill: 2.63, orderType: 'Limit' },
    exit: {
      invalidation: isSecond ? 120 : 140, premiumStop: 1.5, timeStopDays: 10, target: 160,
      targets: [
        { id: 'tp1', stockPrice: 160, targetPrice: 160, estimatedOptionPrice: 4.1, contractsToSell: 1 },
        { id: 'tp2', stockPrice: 170, targetPrice: 170, estimatedOptionPrice: 6.2, contractsToSell: 1 },
      ] as any,
    },
    rrRatio: 2.0, rrModel: 'Heston repriced', finalStatus: 'PASS',
    regimeGate: { headwindCautionPct: -15, headwindRejectPct: -40 },
  };
}

const MASKED = new Set(['recId', 'orderedAt', 'entryDate', 'syncPendingSince', 'syncedAt']);
function mask(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(mask);
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[k] = MASKED.has(k) && v != null ? `<${k}>` : mask(v);
    }
    return out;
  }
  return value;
}

function capture(): Record<string, string> {
  const calls = (global.fetch as jest.Mock).mock.calls
    .filter(([u, init]) => String(u).endsWith('/api/portfolio') && init?.method === 'POST')
    .map(([, init]) => JSON.stringify(mask(JSON.parse(String(init.body)))));
  const orders = (api.postOptionOrder as jest.Mock).mock.calls.map(([req]) => JSON.stringify(req));
  const rows = usePortfolioStore.getState().positions.map((p) => JSON.stringify(mask(p)));
  return { portfolioPosts: JSON.stringify(calls), optionOrders: JSON.stringify(orders), storeRows: JSON.stringify(rows) };
}

const recorded: Record<string, Record<string, string>> = RECORD ? {} : JSON.parse(fs.readFileSync(GOLDEN, 'utf8'));
function check(name: string) {
  const actual = capture();
  if (RECORD) { recorded[name] = actual; return; }
  expect(recorded[name]).toBeDefined();
  expect(actual.portfolioPosts).toBe(recorded[name]!.portfolioPosts);
  expect(actual.optionOrders).toBe(recorded[name]!.optionOrders);
  expect(actual.storeRows).toBe(recorded[name]!.storeRows);
}
afterAll(() => {
  if (RECORD) {
    fs.mkdirSync(path.dirname(GOLDEN), { recursive: true });
    fs.writeFileSync(GOLDEN, JSON.stringify(recorded, null, 2) + '\n');
  }
});

const originalFetch = global.fetch;
function setup(cards: TradeCardData[], liveMid: number) {
  act(() => {
    useScanStore.setState({
      scanResult: { scan_id: 'golden-scan', timestamp: '2026-09-14T10:00:00', candidates: cards } as any,
      optionsCardEdits: {
        ...emptyCardEdits(), scanId: 'golden-scan',
        picks: { [AAA_KEY]: pick(), 'BBB|155|2026-05-15|C': pick(170) },
      },
      stocksCardEdits: emptyCardEdits(), pickedContracts: {}, contractsBySymbol: {}, scanOverrides: {},
    } as any);
    usePortfolioStore.setState({ positions: [], lastSyncError: null });
    useSettingsStore.setState((s) => ({
      premiumStopPct: 0.6,
      ibkrPaper: { ...s.ibkrPaper, accountId: 'ACC', baseUrl: 'https://localhost:7499/v1/api' },
      tradierPaper: { ...s.tradierPaper, token: 'T', accountId: 'TACC' },
    }) as any);
    useAutoTradeStore.setState({ selectedBroker: null, autoMode: 'manual', armed: false, lastOrderId: null });
    useDirectSendNotesStore.setState({ notes: [] });
  });
  jest.clearAllMocks();
  (api.getStockQuote as jest.Mock).mockResolvedValue({ price: 151 });
  (api.getContractQuote as jest.Mock).mockResolvedValue({
    quoteLive: true, price: liveMid, delta: 0.45, theta: -0.09, ivRank: 45, iv: 0.3, spread: 0.1, volume: 100,
  });
  (api.postOptionOrder as jest.Mock).mockResolvedValue({ order_id: 'ORD-1', status: 'submitted', broker: 'ibkr_paper' });
  (api.getAutoTradeStatus as jest.Mock).mockResolvedValue({ armed: false });
  global.fetch = jest.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    if (String(url).endsWith('/api/portfolio') && init?.method === 'POST') {
      const body = { ...JSON.parse(String(init.body)), premiumStopPct: null };
      return { ok: true, status: 201, json: async () => body };
    }
    return { ok: true, json: async () => ({}) };
  }) as unknown as typeof fetch;
}

async function renderPage() {
  render(<Step7TradeCardPage />);
  await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
  await waitFor(() => expect(api.getContractQuote).toHaveBeenCalled());
  await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
}

function editField(label: string, to: string) {
  fireEvent.click(screen.getByLabelText(`Edit ${label}`));
  const input = screen.getByLabelText(`Edit ${label}`) as HTMLInputElement;
  fireEvent.change(input, { target: { value: to } });
  fireEvent.keyDown(input, { key: 'Enter' });
}

async function editAll(quantity?: string) {
  editField('Invalidation', '132');
  editField('Premium stop', '0.90');
  editField('Limit', '2.71');
  if (quantity) editField('Contracts', quantity);
  await waitFor(() => expect(screen.getByLabelText('Edit Invalidation')).toHaveTextContent('132'));
}

async function direct(kind: 'LMT' | 'MKT', broker: RegExp) {
  fireEvent.click(screen.getByRole('button', { name: broker }));
  const btn = await screen.findByRole('button', { name: kind === 'LMT' ? /place limit @/i : /right now — market/i });
  await waitFor(() => expect(btn).toBeEnabled());
  fireEvent.click(btn);
  await waitFor(() => expect(api.postOptionOrder).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
}

async function basket() {
  fireEvent.click(screen.getByRole('button', { name: /pin to basket/i }));
  fireEvent.click(await screen.findByRole('button', { name: /track basket \(1\)/i }));
  const submit = await screen.findByRole('button', { name: /^(Add 1 to Portfolio|Override & Submit)$/ });
  await waitFor(() => expect(submit).toBeEnabled());
  fireEvent.click(submit);
  await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
  await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
}

describe('#581 outbound payload parity — golden payloads from the pre-extraction builders', () => {
  beforeEach(() => { localStorage.clear(); });
  afterEach(() => { cleanup(); global.fetch = originalFetch; });

  it('direct Place Limit, untouched fields, live mid differs from scan mid', async () => {
    setup([makeCard('AAA'), makeCard('BBB')], 4.0);
    await renderPage();
    await direct('LMT', /ibkr paper/i);
    check('direct-limit-untouched');
  });

  it('direct Market, edited stop / premium stop / limit and quantity 3 (Tradier)', async () => {
    setup([makeCard('AAA'), makeCard('BBB')], 4.0);
    await renderPage();
    await editAll('3');
    await direct('MKT', /tradier paper/i);
    check('direct-market-edited-qty3');
  });

  it('basket tracking, untouched fields', async () => {
    setup([makeCard('AAA'), makeCard('BBB')], 4.0);
    await renderPage();
    await basket();
    check('basket-untouched');
  });

  it('basket tracking, edited stop / premium stop / limit, quantity 2', async () => {
    setup([makeCard('AAA'), makeCard('BBB')], 4.0);
    await renderPage();
    await editAll('2');
    await basket();
    check('basket-edited-qty2');
  });

  it('direct Place Limit on a tiny-premium contract, premium stop untouched', async () => {
    setup([makeCard('AAA', 0.01), makeCard('BBB')], 0.01);
    await renderPage();
    await direct('LMT', /ibkr paper/i);
    check('direct-limit-tiny-premium');
  });

  it('basket tracking of a spread card sends the selected contract only', async () => {
    const spread = {
      ...makeCard('AAA'), spreadType: 'bear_put',
      legs: [
        { strike: 150, right: 'P', action: 'BUY', mid: 3.0 },
        { strike: 140, right: 'P', action: 'SELL', mid: 1.2 },
      ],
    } as unknown as TradeCardData;
    setup([spread, makeCard('BBB')], 4.0);
    await renderPage();
    await basket();
    check('basket-spread');
  });
});
