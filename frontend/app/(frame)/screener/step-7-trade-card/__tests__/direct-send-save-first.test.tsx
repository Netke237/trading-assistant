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

describe('P1b-i — save first, then send', () => {
  it('1. persists BEFORE the order is sent', async () => {
    await renderPage();
    await sendAndSettle();
    expect(callLog).toEqual(['persist', 'order']);
    expect(screen.getByText(`${AAA_LABEL}: Order placed — ID: ORD-1`)).toBeInTheDocument();
  });

  it('2. a server refusal (P1a\'s cap sentence) sends no order, deletes nothing and leaves no note', async () => {
    const P1A = '6 contracts is above the 5-contract limit per trade (max_contracts_per_trade). Lower Contracts to 5 or fewer and send again.';
    persistReply = () => Promise.resolve({ ok: false, status: 422, json: async () => ({ detail: P1A }) });
    await renderPage();
    await sendAndSettle();
    expect(api.postOptionOrder).not.toHaveBeenCalled();
    const banner = screen.getByText(new RegExp(`^${AAA_LABEL}: No order was sent — 6 contracts is above`));
    expect(banner.textContent).not.toContain('..');
    expect(api.deletePortfolioPosition).not.toHaveBeenCalled();
    expect(notes()).toHaveLength(0);
    expect(positions()).toHaveLength(0);
  });

  it.each([
    ['resolves', () => Promise.resolve(undefined)],
    ['throws → 404', () => Promise.reject(deleteErr(404, 'Position not found'))],
  ])('3. offline: no order, one POST, no row, the note always (delete %s)', async (_n, del) => {
    persistReply = () => Promise.reject(new TypeError('Failed to fetch'));
    (api.deletePortfolioPosition as jest.Mock).mockImplementation(del);
    await renderPage();
    await sendAndSettle();
    expect(api.postOptionOrder).not.toHaveBeenCalled();
    expect(persistBodies()).toHaveLength(1);
    expect(positions()).toHaveLength(0);
    expect(screen.getByText(`${AAA_LABEL}: Portfolio tracking could not be confirmed, so NO order was sent.`)).toBeInTheDocument();
    expect(api.deletePortfolioPosition).toHaveBeenCalledWith(lastRecId());
    expect(notes()).toEqual([expect.objectContaining({ kind: 'save-unconfirmed', recId: lastRecId() })]);
    expect(noteText(/NO order was sent, but Portfolio may still have saved this send \(rec_id REC-/)).toBeInTheDocument();
  });

  it.each([
    ['duplicate rec_id', 409, 'duplicate rec_id REC-1', /No order was sent — duplicate rec_id REC-1\.$/],
    ['already exists', 409, 'A position for AAA|150|2026-05-15|C already exists', /a position for this contract is already tracked in Portfolio/],
  ])('4a. a %s refusal: no delete, no note', async (_n, status, detail, banner) => {
    persistReply = () => Promise.resolve({ ok: false, status, json: async () => ({ detail }) });
    await renderPage();
    await sendAndSettle();
    expect(api.postOptionOrder).not.toHaveBeenCalled();
    expect(api.deletePortfolioPosition).not.toHaveBeenCalled();
    expect(notes()).toHaveLength(0);
    expect(screen.getByText(banner)).toBeInTheDocument();
  });

  it('4b. a bare HTTP 502 on the save is unconfirmed: no order, delete by recId, SAVE-UNCONFIRMED note', async () => {
    persistReply = () => Promise.resolve({ ok: false, status: 502, json: async () => { throw new Error('html'); } });
    await renderPage();
    await sendAndSettle();
    expect(api.postOptionOrder).not.toHaveBeenCalled();
    expect(api.deletePortfolioPosition).toHaveBeenCalledWith(lastRecId());
    expect(notes()).toEqual([expect.objectContaining({ kind: 'save-unconfirmed', recId: lastRecId() })]);
  });

  it('4c. a contract already tracked locally: no save, no order, the "already tracked" banner', async () => {
    await renderPage();
    act(() => { usePortfolioStore.setState({ positions: [{ symbol: 'AAA', contract: AAA_CONTRACT, recId: 'REC-REAL' } as PortfolioPosition] }); });
    await sendAndSettle();
    expect(persistBodies()).toHaveLength(0);
    expect(api.postOptionOrder).not.toHaveBeenCalled();
    expect(screen.getByText(`${AAA_LABEL}: No order was sent — a position for this contract is already tracked in Portfolio. Close or edit that one instead.`)).toBeInTheDocument();
  });

  it('5. the order goes out at the quantity the save approved', async () => {
    persistReply = (body) => Promise.resolve({ ok: true, status: 201, json: async () => ({ ...body, qty: 2, adjustedQty: 2 }) });
    await renderPage();
    fireEvent.click(screen.getByLabelText('Edit Contracts'));
    const input = screen.getByDisplayValue('1');
    fireEvent.change(input, { target: { value: '4' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => expect(screen.getByLabelText('Edit Contracts')).toHaveTextContent('4'));
    await sendAndSettle();
    expect(persistBodies()[0]!.qty).toBe(4);
    expect(api.postOptionOrder).toHaveBeenCalledWith(expect.objectContaining({ quantity: 2 }));
    expect(positions()).toEqual([expect.objectContaining({ contracts: 2 })]);
    expect(screen.getByText(/The order was sent for 2\./)).toBeInTheDocument();
  });
});

describe('P1b-i — auto-delete only when the broker provably never received the order', () => {
  /** Seed the copy a `syncFromBackend` could make between the save and the answer. */
  function seedSyncCopy() {
    persistReply = (body) => {
      act(() => {
        usePortfolioStore.setState((s) => ({
          positions: [...s.positions, { symbol: 'AAA', contract: AAA_CONTRACT, recId: String(body.recId), syncStatus: 'synced' } as PortfolioPosition],
        }));
      });
      return echo(body);
    };
  }

  it.each([
    ['a 422', () => Promise.reject(orderErr(422, 'quantity: bad'))],
    ['503 credentials', () => Promise.reject(orderErr(503, 'Broker credentials unavailable: ibkr_paper'))],
    ['Unknown broker', () => Promise.reject(orderErr(400, 'Unknown broker: x'))],
    ['live trading via', () => Promise.reject(orderErr(400, 'live trading via ibkr is not enabled'))],
    ['IBKR confirm 502', () => Promise.reject(orderErr(502, 'IBKR did not place the order: it asked'))],
    ['status Rejected', () => Promise.resolve({ order_id: 'ORD-R', status: 'Rejected' })],
  ])('6. %s → deleted by recId, "removed" banner, no local row', async (_n, order) => {
    seedSyncCopy();
    // The follow-up forced sync is held unanswered until the assertions are
    // done, so only the IMMEDIATE `dropLocal` after the delete can clear the
    // sync copy (M31). Released at the end: the store's in-flight sync is
    // module-level and a later test must not inherit it.
    const held = deferred<Reply>();
    getReplies = [() => held.promise];
    (api.postOptionOrder as jest.Mock).mockImplementation(order);
    await renderPage();
    await sendAndSettle();
    expect(api.deletePortfolioPosition).toHaveBeenCalledWith(lastRecId());
    expect(screen.getByText(new RegExp(`^${AAA_LABEL}: Order NOT placed: .*The tracked position was removed\\.$`))).toBeInTheDocument();
    expect(positions()).toHaveLength(0);
    expect(notes()).toHaveLength(0);
    expect(screen.queryByText(/Order placed/)).not.toBeInTheDocument();
    await act(async () => { held.resolve({ ok: false, json: async () => ({}) }); });
  });

  it('6b. the auto-delete answering → 404 counts as removed', async () => {
    seedSyncCopy();
    (api.postOptionOrder as jest.Mock).mockRejectedValue(orderErr(422, 'bad'));
    (api.deletePortfolioPosition as jest.Mock).mockRejectedValue(deleteErr(404, 'Position not found'));
    await renderPage();
    await sendAndSettle();
    expect(screen.getByText(/The tracked position was removed/)).toBeInTheDocument();
    expect(notes()).toHaveLength(0);
    expect(positions()).toHaveLength(0);
  });

  it('6c. a sync GET that resolves AFTER the auto-delete cannot write the row back', async () => {
    const held = deferred<Reply>();
    getReplies = [() => held.promise];
    persistReply = (body) => {
      // A sync (QuickLook, AutoTradeArm) starts between the save and the answer.
      void usePortfolioStore.getState().syncFromBackend();
      const serverRow = body;
      (api.deletePortfolioPosition as jest.Mock).mockImplementation(async () => {
        // The GET that started before the DELETE resolves after it, WITH the row.
        setTimeout(() => held.resolve({ ok: true, json: async () => [serverRow] }), 0);
      });
      return echo(body);
    };
    (api.postOptionOrder as jest.Mock).mockRejectedValue(orderErr(422, 'bad'));
    await renderPage();
    await sendAndSettle();
    await settle(80);
    expect(api.deletePortfolioPosition).toHaveBeenCalled();
    expect(positions()).toHaveLength(0);
  });
});

describe('P1b-i — everything else keeps the row, with an ORDER-UNKNOWN note', () => {
  it.each([
    ['400 Expecting value', () => Promise.reject(orderErr(400, 'Expecting value: line 1 column 1')), null],
    ['502 Tradier 401', () => Promise.reject(orderErr(502, 'Tradier paper order failed: HTTP 401 unauthorized')), null],
    ['502 IBKR marker not as prefix', () => Promise.reject(orderErr(502, 'Tradier paper order failed: HTTP 400 — IBKR did not place the order: x')), null],
    ['400 Unknown broker not as prefix', () => Promise.reject(orderErr(400, 'x Unknown broker y')), null],
    ['503 credentials not as prefix', () => Promise.reject(orderErr(503, 'x Broker credentials unavailable')), null],
    ['TypeError', () => Promise.reject(new TypeError('Failed to fetch')), null],
    ['blank order_id', () => Promise.resolve({ order_id: '', status: 'Submitted' }), null],
    ['Inactive', () => Promise.resolve({ order_id: 'ORD-9', status: 'Inactive' }), 'ORD-9'],
    ['Cancelled', () => Promise.resolve({ order_id: 'ORD-9', status: 'Cancelled' }), 'ORD-9'],
    ['Removed', () => Promise.resolve({ order_id: 'ORD-9', status: 'Removed' }), 'ORD-9'],
    ['no order_id field', () => Promise.resolve({ status: 'Submitted' }), null],
  ])('7. %s → no delete, UNKNOWN banner, row kept, note names recId and broker', async (_n, order, id) => {
    (api.postOptionOrder as jest.Mock).mockImplementation(order);
    await renderPage();
    await sendAndSettle();
    expect(api.deletePortfolioPosition).not.toHaveBeenCalled();
    expect(screen.getByText(new RegExp(`^${AAA_LABEL}: Order status UNKNOWN \\(`))).toBeInTheDocument();
    expect(positions()).toEqual([expect.objectContaining({ recId: lastRecId() })]);
    const note = screen.getByText(new RegExp(`order status UNKNOWN.*\\(rec_id ${lastRecId()}\\)\\. Check IBKR Paper first`));
    if (id) expect(note.textContent).toContain(`(broker order ID ${id})`);
    expect(document.body.textContent).not.toMatch(/ID: undefined|undefined/);
    expect(screen.queryByText(/Order placed/)).not.toBeInTheDocument();
  });

  it('7b. a plain Error reads UNKNOWN (Error: boom)', async () => {
    (api.postOptionOrder as jest.Mock).mockRejectedValue(new Error('boom'));
    await renderPage();
    await sendAndSettle();
    expect(screen.getByText(`${AAA_LABEL}: Order status UNKNOWN (Error: boom).`)).toBeInTheDocument();
  });

  it('15. the note is pushed BEFORE the row is added (a throwing add still leaves the note)', async () => {
    (api.postOptionOrder as jest.Mock).mockRejectedValue(new Error('boom'));
    await renderPage();
    act(() => { usePortfolioStore.setState({ addPosition: (() => { throw new Error('store broke'); }) as any }); });
    await sendAndSettle();
    expect(notes()).toEqual([expect.objectContaining({ kind: 'order-unknown', recId: lastRecId() })]);
    expect(screen.getByText(/The local view failed to update: Error: store broke/)).toBeInTheDocument();
  });

  it('16. a throw after the save never reaches the outer catch: it is kept with a note', async () => {
    (api.postOptionOrder as jest.Mock).mockResolvedValue({ get order_id(): string { throw new Error('bad body'); } });
    await renderPage();
    await sendAndSettle();
    expect(notes()).toEqual([expect.objectContaining({ kind: 'order-unknown' })]);
    expect(screen.getByText(`${AAA_LABEL}: Order status UNKNOWN (Error: bad body).`)).toBeInTheDocument();
    expect(screen.queryByText(/No order was sent/)).not.toBeInTheDocument();
  });

  it('14. a 2xx save whose body did not parse sends no order and leaves a SAVE-UNCONFIRMED note', async () => {
    persistReply = () => Promise.resolve({ ok: true, status: 201, json: async () => { throw new Error('not json'); } });
    await renderPage();
    await sendAndSettle();
    expect(api.postOptionOrder).not.toHaveBeenCalled();
    expect(persistBodies()).toHaveLength(1);
    expect(positions()).toHaveLength(0);
    expect(api.deletePortfolioPosition).toHaveBeenCalledWith(lastRecId());
    expect(screen.getByText(`${AAA_LABEL}: Portfolio saved it but its reply could not be read, so NO order was sent.`)).toBeInTheDocument();
    expect(notes()).toEqual([expect.objectContaining({ kind: 'save-unconfirmed', recId: lastRecId() })]);
  });
});

describe('P1b-i — the notes outlive the card', () => {
  // Explicit timeout: this long multi-step test exceeds Jest's 5 s default under CPU load (ticket 26, FIX-26B).
  it('8. an ORDER-UNKNOWN note survives Next, Prev, a basket submit, a new send and a remount', async () => {
    (api.postOptionOrder as jest.Mock).mockRejectedValueOnce(new Error('boom'));
    await renderPage();
    await sendAndSettle();
    const first = lastRecId();
    const firstNote = new RegExp(`\\(rec_id ${first}\\)`);
    expect(noteText(firstNote)).toBeInTheDocument();

    await goNext();
    expect(noteText(firstNote)).toBeInTheDocument();
    await goPrev();
    expect(noteText(firstNote)).toBeInTheDocument();

    // A basket submit, from BBB (AAA is tracked, so its dialog would ask for an override).
    await goNext();
    await sendBasket();
    await waitFor(() => expect(positions().some((p) => p.symbol === 'BBB')).toBe(true));
    await settle();
    expect(noteText(firstNote)).toBeInTheDocument();

    // A successful direct send, on BBB after dropping the basket's BBB row.
    act(() => { usePortfolioStore.setState((s) => ({ positions: s.positions.filter((p) => p.symbol !== 'BBB') })); });
    await sendAndSettle();
    expect(screen.getByText(`${BBB_LABEL}: Order placed — ID: ORD-1`)).toBeInTheDocument();
    expect(noteText(firstNote)).toBeInTheDocument();

    // Navigation away and back (unmount, render again).
    cleanup();
    await renderPage();
    expect(noteText(firstNote)).toBeInTheDocument();
  }, 15_000);

  it('8b. two UNKNOWN sends leave two notes', async () => {
    (api.postOptionOrder as jest.Mock).mockRejectedValue(new Error('boom'));
    await renderPage();
    await sendAndSettle();
    await goNext();
    await sendAndSettle();
    expect(notes().map((n) => n.label)).toEqual([AAA_LABEL, BBB_LABEL]);
  });

  it('9. an auto-delete whose delete fails leaves a NOT-REMOVED note that survives Next', async () => {
    (api.postOptionOrder as jest.Mock).mockRejectedValue(orderErr(422, 'bad'));
    (api.deletePortfolioPosition as jest.Mock).mockRejectedValue(deleteErr(500, 'db down'));
    await renderPage();
    await sendAndSettle();
    expect(screen.getByText(`${AAA_LABEL}: Order NOT placed: bad.`)).toBeInTheDocument();
    const note = new RegExp(`NO order was placed, but its tracked position could not be removed \\(rec_id ${lastRecId()}\\)`);
    expect(noteText(note)).toBeInTheDocument();
    await goNext();
    expect(noteText(note)).toBeInTheDocument();
  });
});

describe('P1b-i — the green line and the entry price', () => {
  it('10a. a failed send after a successful one leaves no green line', async () => {
    await renderPage();
    await sendAndSettle();
    expect(screen.getByText(/Order placed — ID: ORD-1/)).toBeInTheDocument();
    act(() => { usePortfolioStore.setState({ positions: [] }); });
    (api.postOptionOrder as jest.Mock).mockRejectedValueOnce(orderErr(422, 'bad'));
    await sendAndSettle('MKT');
    expect(screen.queryByText(/Order placed/)).not.toBeInTheDocument();
  });

  it('10b. a basket submit after a direct success keeps the green line', async () => {
    await renderPage();
    await sendAndSettle();
    act(() => { usePortfolioStore.setState({ positions: [] }); });
    await sendBasket();
    await waitFor(() => expect(persistBodies().length).toBeGreaterThan(1));
    await settle();
    expect(screen.getByText(`${AAA_LABEL}: Order placed — ID: ORD-1`)).toBeInTheDocument();
  });

  it('11. a 0 scan mid with no live quote stores the entry limit, on both builders', async () => {
    resetStores([makeCard('AAA', 0), makeCard('BBB')]);
    (api.getContractQuote as jest.Mock).mockRejectedValue(new Error('no quote'));
    await renderPage();
    // NO-LIVE-QUOTE (plan 3e, Q-B (a)): a send with no live quote needs the tick.
    fireEvent.click(await screen.findByLabelText('Confirm sending without a live quote'));
    await sendAndSettle();
    expect(persistBodies()[0]!.entryPrice).toBe(CARD_LIMIT);

    cleanup();
    act(() => { usePortfolioStore.setState({ positions: [] }); });
    (global.fetch as jest.Mock).mockClear();
    await renderPage();
    await sendBasket();
    await waitFor(() => expect(persistBodies()).toHaveLength(1));
    expect(persistBodies()[0]!.entryPrice).toBe(CARD_LIMIT);
  });

  it('12. Tastytrade paper: the Market button is disabled, with the refusal as its title', async () => {
    await renderPage();
    act(() => { useAutoTradeStore.setState({ selectedBroker: 'tastytrade_paper' } as any); });
    const market = await screen.findByRole('button', { name: /right now — market/i });
    expect(market).toBeDisabled();
    expect(market).toHaveAttribute('title', 'Tastytrade paper accepts limit orders only — use Place Limit.');
  });

  it('13. a result that lands after Next still names ITS contract', async () => {
    const order = deferred<{ order_id: string; status: string }>();
    (api.postOptionOrder as jest.Mock).mockReturnValue(order.promise);
    persistReply = (body) => Promise.resolve({ ok: true, status: 201, json: async () => ({ ...body, adjustedQty: 2 }) });
    await renderPage();
    await send();
    await waitFor(() => expect(api.postOptionOrder).toHaveBeenCalled());
    await goNext();
    await act(async () => { order.resolve({ order_id: 'ORD-1', status: 'Submitted' }); });
    await settle();
    expect(screen.getByText(`${AAA_LABEL}: Order placed — ID: ORD-1`)).toBeInTheDocument();
    expect(screen.getByText(`${AAA_LABEL}: Size reduced to 2 contracts to fit exposure limits. The order was sent for 2.`)).toBeInTheDocument();
    expect(screen.queryByText(/^Order placed/)).not.toBeInTheDocument();
  });
});

describe('P1b-i — Remove (P1B1-MINIMAL-REMOVE-2026-09-25)', () => {
  async function unknownSend() {
    (api.postOptionOrder as jest.Mock).mockRejectedValueOnce(new Error('boom'));
    await sendAndSettle();
    return lastRecId();
  }

  it('17. ORDER-UNKNOWN: cancel does nothing; confirm deletes by the note\'s recId', async () => {
    await renderPage();
    const recId = await unknownSend();
    confirmSpy.mockReturnValueOnce(false);
    fireEvent.click(removeBtn(AAA_LABEL));
    await settle();
    expect(api.deletePortfolioPosition).not.toHaveBeenCalled();
    expect(notes()).toHaveLength(1);
    expect(confirmSpy.mock.calls[0][0]).toContain('ONLY if IBKR Paper shows no order');

    fireEvent.click(removeBtn(AAA_LABEL));
    await settle();
    expect(api.deletePortfolioPosition).toHaveBeenCalledTimes(1);
    expect(api.deletePortfolioPosition).toHaveBeenCalledWith(recId);
    expect(notes()).toHaveLength(0);
    expect(positions()).toHaveLength(0);
  });

  it('18. SAVE-UNCONFIRMED: a 404 on Remove is final; dismisses note immediately (#171)', async () => {
    persistReply = () => Promise.reject(new TypeError('Failed to fetch'));
    await renderPage();
    await sendAndSettle();
    (api.deletePortfolioPosition as jest.Mock).mockRejectedValueOnce(deleteErr(404, 'Position not found'));
    fireEvent.click(removeBtn(AAA_LABEL));
    await settle();
    expect(notes()).toHaveLength(0);
    expect(screen.queryByText(/Not found yet/)).toBeNull();
  });

  it('19. NOT-REMOVED: a 404 on Remove is final', async () => {
    (api.postOptionOrder as jest.Mock).mockRejectedValue(orderErr(422, 'bad'));
    (api.deletePortfolioPosition as jest.Mock).mockRejectedValueOnce(deleteErr(500, 'db down'));
    await renderPage();
    await sendAndSettle();
    expect(notes()).toEqual([expect.objectContaining({ kind: 'not-removed' })]);
    (api.deletePortfolioPosition as jest.Mock).mockRejectedValueOnce(deleteErr(404, 'Position not found'));
    fireEvent.click(removeBtn(AAA_LABEL));
    await settle();
    expect(notes()).toHaveLength(0);
  });

  it('19b. ORDER-UNKNOWN: a 404 on Remove is final', async () => {
    await renderPage();
    await unknownSend();
    (api.deletePortfolioPosition as jest.Mock).mockRejectedValueOnce(deleteErr(404));
    fireEvent.click(removeBtn(AAA_LABEL));
    await settle();
    expect(notes()).toHaveLength(0);
    expect(positions()).toHaveLength(0);
  });

  it('20. any other error keeps the note, says so, and re-enables the button', async () => {
    await renderPage();
    await unknownSend();
    (api.deletePortfolioPosition as jest.Mock).mockRejectedValueOnce(deleteErr(500, 'x'));
    fireEvent.click(removeBtn(AAA_LABEL));
    await settle();
    expect(notes()).toHaveLength(1);
    expect(screen.getByText('Remove failed: x. Try again.')).toBeInTheDocument();
    expect(removeBtn(AAA_LABEL)).toBeEnabled();
    expect(positions()).toHaveLength(1);
  });

  it('21a. Remove acts on its own note only', async () => {
    await renderPage();
    const aaa = await unknownSend();
    await goNext();
    const bbb = await unknownSend();
    fireEvent.click(removeBtn(BBB_LABEL));
    await settle();
    expect(api.deletePortfolioPosition).toHaveBeenCalledTimes(1);
    expect(api.deletePortfolioPosition).toHaveBeenCalledWith(bbb);
    expect(notes().map((n) => n.recId)).toEqual([aaa]);
  });

  it('21b. Remove on a SAVE-UNCONFIRMED note deletes ITS recId, not a later row of the same contract', async () => {
    persistReply = () => Promise.reject(new TypeError('Failed to fetch'));
    await renderPage();
    await sendAndSettle();
    const noteRec = lastRecId();
    persistReply = echo;
    await sendAndSettle();
    const liveRec = lastRecId();
    expect(liveRec).not.toBe(noteRec);
    expect(screen.getByText(/Order placed — ID: ORD-1/)).toBeInTheDocument();
    (api.deletePortfolioPosition as jest.Mock).mockClear();
    fireEvent.click(removeBtn(AAA_LABEL));
    await settle();
    expect(api.deletePortfolioPosition).toHaveBeenCalledTimes(1);
    expect(api.deletePortfolioPosition).toHaveBeenCalledWith(noteRec);
    expect(positions().map((p) => p.recId)).toEqual([liveRec]);
  });

  it('22. a pending Remove disables the button: one DELETE only', async () => {
    await renderPage();
    await unknownSend();
    const del = deferred<void>();
    (api.deletePortfolioPosition as jest.Mock).mockReturnValueOnce(del.promise);
    fireEvent.click(removeBtn(AAA_LABEL));
    await waitFor(() => expect(removeBtn(AAA_LABEL)).toBeDisabled());
    fireEvent.click(removeBtn(AAA_LABEL));
    expect(api.deletePortfolioPosition).toHaveBeenCalledTimes(1);
    await act(async () => { del.resolve(); });
    await settle();
    expect(notes()).toHaveLength(0);
  });

  it('23. (X1) a sync GET started before the Remove\'s DELETE cannot write the row back', async () => {
    await renderPage();
    const recId = await unknownSend();
    expect(positions()).toHaveLength(1);
    const serverRow = persistBodies().at(-1)!;
    // A sync (the 30s poller, QuickLook, AutoTradeArm) whose GET is in flight...
    const held = deferred<Reply>();
    getReplies = [() => held.promise];
    act(() => { void usePortfolioStore.getState().syncFromBackend(); });
    await settle();
    // ...then Remove. The DELETE lands first; the stale GET resolves after it,
    // still carrying the row.
    (api.deletePortfolioPosition as jest.Mock).mockImplementationOnce(async () => {
      setTimeout(() => held.resolve({ ok: true, json: async () => [serverRow] }), 0);
    });
    fireEvent.click(removeBtn(AAA_LABEL));
    await settle(80);
    expect(api.deletePortfolioPosition).toHaveBeenCalledWith(recId);
    expect(notes()).toHaveLength(0);
    expect(positions()).toHaveLength(0);
  });
});

/* Audit round 1, F1 — the D5 premium cap is judged by the SERVER at the
 * price the order can fill at. The page's job is to tell it which order the
 * save precedes: an edited limit above the mid must reach the server, or it
 * judges 12 x $3.00 while the broker gets 12 @ $3.60. */
describe('audit round 1 F1 — the save carries the order it precedes', () => {
  it('Place Limit sends orderType LMT and the EDITED limit, not the mid', async () => {
    act(() => {
      useScanStore.setState((s: any) => ({
        optionsCardEdits: { ...s.optionsCardEdits, entryLimit: { [AAA_CONTRACT]: 3.1 } },
      }));
    });
    await renderPage();
    await sendAndSettle('LMT');
    const body = persistBodies()[0]!;
    expect(body.orderType).toBe('LMT');
    expect(body.orderLimitPrice).toBe(3.1);
    // The entry stays the mid: the limit judges the cap, it is not the fill.
    expect(body.entryPrice).toBe(CARD_LIMIT);
  });

  it('Right Now — Market sends orderType MKT and no limit', async () => {
    await renderPage();
    await sendAndSettle('MKT');
    const body = persistBodies()[0]!;
    expect(body.orderType).toBe('MKT');
    expect(body.orderLimitPrice).toBeNull();
  });
});
