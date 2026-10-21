import { BEARISH_UNVALIDATED_MESSAGE, isBearishUnvalidated } from '@/lib/unvalidated';
import { useStockOrderOwnershipStore } from '@/lib/stockExecutionSession';
import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { sendStockSaveFirst, removeNoteRow, stockSendLabel } from '@/lib/stockDirectSend';
import { brokerLabelFor } from '@/lib/directOrder';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useDirectSendNotesStore } from '@/lib/directSendNotesStore';
import { buildPaperStockPosition } from '@/lib/paperTrade';
import { DirectSendNotesPanel } from '@/components/organisms/DirectSendNotesPanel';
import { api } from '@/lib/api';

/*
 * STOCK-SENDS (plan §A1, A3) — the one stock send: save first, order at the
 * saved quantity, remove the row only when the broker provably never got the
 * order, and leave a rec_id-scoped note whenever a row may have no order or an
 * order's status is unknown.
 */

jest.mock('@/lib/api', () => ({
  api: {
    postStockOrder: jest.fn(),
    deletePortfolioPosition: jest.fn(),
  },
}));

type Reply = { ok: boolean; status?: number; json: () => Promise<unknown> };
let saveReply: (body: Record<string, unknown>) => Promise<Reply>;
let log: string[];
const originalFetch = global.fetch;

const echo = (extra: Record<string, unknown> = {}) => (body: Record<string, unknown>) =>
  Promise.resolve({ ok: true, status: 201, json: async () => ({ ...body, ...extra }) });

beforeEach(() => {
  jest.clearAllMocks();
  log = [];
  saveReply = echo();
  global.fetch = jest.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    if (String(url).endsWith('/api/portfolio') && init?.method === 'POST') {
      log.push('save');
      return saveReply(JSON.parse(String(init.body)));
    }
    return { ok: true, json: async () => ({}) };
  }) as unknown as typeof fetch;
  (api.deletePortfolioPosition as jest.Mock).mockResolvedValue(undefined);
  (api.postStockOrder as jest.Mock).mockImplementation(async () => { log.push('order'); return { order_id: 'ORD-1', status: 'Submitted' }; });
  act(() => {
    usePortfolioStore.setState({ positions: [], lastSyncError: null });
    useDirectSendNotesStore.setState({ notes: [] });
  });
});
afterEach(() => { global.fetch = originalFetch; });

const pos = (shares = 300) => buildPaperStockPosition('AAPL', 200, shares, 'Bullish', undefined, { stop: 190, targets: [{ price: 220 }] });
const send = (p = pos(), broker = 'ibkr_paper', orderType: 'LMT' | 'MKT' = 'LMT') => sendStockSaveFirst({
  pos: p, broker, orderType, limitPrice: orderType === 'LMT' ? 200 : null, action: 'BUY',
  addPosition: usePortfolioStore.getState().addPosition, earningsVeto: false,
});
const notes = () => useDirectSendNotesStore.getState().notes;
const positions = () => usePortfolioStore.getState().positions;

describe('sendStockSaveFirst', () => {
  it('saves before ordering and orders the quantity the save approved', async () => {
    saveReply = echo({ adjustedQty: 100 });
    const out = await send();
    expect(log).toEqual(['save', 'order']);
    expect((api.postStockOrder as jest.Mock).mock.calls[0][0]).toMatchObject({
      symbol: 'AAPL', quantity: 100, action: 'BUY', effect: 'OPEN', order_type: 'LMT', limit_price: 200, tif: 'DAY',
    });
    expect(out).toEqual(expect.objectContaining({ kind: 'placed', orderId: 'ORD-1', qty: 100, resizedFrom: 300 }));
    expect(out.message).toBe('AAPL 100 sh (Portfolio sized it from 300): Order placed (ID ORD-1).');
    expect(positions()).toHaveLength(1);
    expect(positions()[0]).toMatchObject({ contracts: 100, source: 'broker', sourceLabel: 'IBKR Paper — Limit (ID: ORD-1)' });
  });

  it('an unresized placed order reports resizedFrom null', async () => {
    const out = await send(pos(30));
    expect(out).toEqual(expect.objectContaining({ kind: 'placed', qty: 30, resizedFrom: null }));
    expect((api.postStockOrder as jest.Mock).mock.calls[0][0].quantity).toBe(30);
  });

  it('a refused save sends no order, writes no note', async () => {
    saveReply = async () => ({ ok: false, status: 422, json: async () => ({ detail: 'total_exposure_limit_reached' }) });
    const out = await send();
    expect(out).toEqual({ kind: 'refused', message: 'AAPL 300 sh: No order was sent — total_exposure_limit_reached.' });
    expect(api.postStockOrder).not.toHaveBeenCalled();
    expect(notes()).toEqual([]);
  });

  it.each([
    ['offline', () => Promise.reject(new Error('offline'))],
    ['bare 5xx', () => Promise.resolve({ ok: false, status: 502, json: async () => { throw new Error('html'); } })],
    ['unparsed 2xx', () => Promise.resolve({ ok: true, status: 201, json: async () => { throw new Error('bad json'); } })],
  ])('an unconfirmed save (%s) sends no order and leaves a SAVE-UNCONFIRMED note', async (_n, reply) => {
    saveReply = reply as typeof saveReply;
    const out = await send();
    expect(out).toEqual(expect.objectContaining({ kind: 'unknown', qty: null }));
    expect(api.postStockOrder).not.toHaveBeenCalled();
    expect(notes()).toEqual([expect.objectContaining({ kind: 'save-unconfirmed', label: 'AAPL 300 sh' })]);
  });

  it('a locally tracked position for the symbol refuses before saving', async () => {
    act(() => { usePortfolioStore.setState({ positions: [{ ...pos(5), recId: 'OLD' }] }); });
    const out = await send();
    expect(out.kind).toBe('refused');
    expect(log).toEqual([]);
  });

  it('a Tastytrade market order is refused before saving', async () => {
    const out = await send(pos(), 'tastytrade_paper', 'MKT');
    expect(out.kind).toBe('refused');
    expect(log).toEqual([]);
  });

  it('a pre-submit broker failure removes the saved row', async () => {
    (api.postStockOrder as jest.Mock).mockRejectedValueOnce(new Error('API /broker/stock-order → 422: bad qty'));
    const out = await send();
    expect(out).toEqual({ kind: 'not-placed', message: 'AAPL 300 sh: Order NOT placed: bad qty. The tracked position was removed.' });
    expect(api.deletePortfolioPosition).toHaveBeenCalledTimes(1);
    expect(notes()).toEqual([]);
  });

  it('a failed removal leaves a NOT-REMOVED note', async () => {
    (api.postStockOrder as jest.Mock).mockRejectedValueOnce(new Error('API /broker/stock-order → 422: bad qty'));
    (api.deletePortfolioPosition as jest.Mock).mockRejectedValueOnce(new Error('API /api/portfolio/X → 500: boom'));
    const out = await send();
    expect(out.kind).toBe('not-placed');
    expect(notes()).toEqual([expect.objectContaining({ kind: 'not-removed' })]);
  });

  it('an unknown broker outcome keeps the row with an ORDER-UNKNOWN note naming the SENT quantity and the broker', async () => {
    saveReply = echo({ adjustedQty: 100 });
    (api.postStockOrder as jest.Mock).mockRejectedValueOnce(new Error('API /broker/stock-order → 504: Gateway Timeout'));
    const out = await send(pos(), 'alpaca_paper');
    expect(out).toEqual(expect.objectContaining({ kind: 'unknown', qty: 100, resizedFrom: 300 }));
    expect(notes()).toEqual([expect.objectContaining({ kind: 'order-unknown', label: 'AAPL 100 sh', brokerLabel: 'Alpaca Paper' })]);
    expect(positions()).toHaveLength(1);
    expect(positions()[0].contracts).toBe(100);
    expect(api.deletePortfolioPosition).not.toHaveBeenCalled();
  });

  it('a reply with no usable order id keeps the row with a note', async () => {
    (api.postStockOrder as jest.Mock).mockResolvedValueOnce({ order_id: '', status: 'Submitted' });
    const out = await send();
    expect(out.kind).toBe('unknown');
    expect(notes()).toEqual([expect.objectContaining({ kind: 'order-unknown' })]);
  });

  function savedBodies(): Record<string, unknown>[] {
    return (global.fetch as jest.Mock).mock.calls
      .filter((call) => call[1]?.method === 'POST' && String(call[0]).includes('/api/portfolio'))
      .map((call) => JSON.parse(String(call[1].body)) as Record<string, unknown>);
  }

  it('saves order type and limit before submission and sends one stable attempt id', async () => {
    const p = pos();
    await send(p);
    expect(log[0]).toBe('save');
    expect(savedBodies()[0]).toMatchObject({ orderType: 'LMT', orderLimitPrice: 200 });
    expect((api.postStockOrder as jest.Mock).mock.calls[0][0]).toMatchObject({
      attempt_id: `stk-${p.recId}`,
      savedRecId: p.recId,
      symbol: 'AAPL',
      effect: 'OPEN',
    });
  });

  it('a market save carries its order type and a null limit before the order', async () => {
    const p = pos(12);
    await send(p, 'alpaca_paper', 'MKT');
    expect(savedBodies()[0]).toMatchObject({ orderType: 'MKT', orderLimitPrice: null });
    expect((api.postStockOrder as jest.Mock).mock.calls[0][0]).toMatchObject({
      attempt_id: `stk-${p.recId}`,
      savedRecId: p.recId,
      order_type: 'MKT',
      limit_price: null,
    });
  });

  it('an unknown remount of the same saved row repeats that attempt id', async () => {
    const p = pos();
    (api.postStockOrder as jest.Mock).mockRejectedValueOnce(new Error('API /broker/stock-order → 504: Gateway Timeout'));
    const first = await send(p);
    expect(first.kind).toBe('unknown');
    expect((api.postStockOrder as jest.Mock).mock.calls[0][0].attempt_id).toBe(`stk-${p.recId}`);
    act(() => {
      usePortfolioStore.setState({ positions: [] });
      useStockOrderOwnershipStore.setState({ bySymbol: {} });
    });
    await send(p);
    expect((api.postStockOrder as jest.Mock).mock.calls.map((call) => call[0].attempt_id)).toEqual([
      `stk-${p.recId}`, `stk-${p.recId}`,
    ]);
  });

  it('a genuine refusal still removes the saved row when the order carries an attempt id', async () => {
    const p = pos();
    (api.postStockOrder as jest.Mock).mockRejectedValueOnce(new Error('API /broker/stock-order → 422: bad qty'));
    const out = await send(p);
    expect((api.postStockOrder as jest.Mock).mock.calls[0][0]).toMatchObject({
      attempt_id: `stk-${p.recId}`,
      savedRecId: p.recId,
    });
    expect(out.kind).toBe('not-placed');
    expect(api.deletePortfolioPosition).toHaveBeenCalledWith(p.recId);
    expect(notes()).toEqual([]);
  });
});

describe('brokerLabelFor (R1-1)', () => {
  it.each([
    ['ibkr_paper', 'IBKR Paper'], ['tradier_paper', 'Tradier Paper'],
    ['tastytrade_paper', 'Tastytrade Paper'], ['alpaca_paper', 'Alpaca Paper'],
  ])('%s -> %s', (b, label) => { expect(brokerLabelFor(b)).toBe(label); });
  it('stockSendLabel', () => { expect(stockSendLabel('AAPL', 12)).toBe('AAPL 12 sh'); });
});

describe('DirectSendNotesPanel', () => {
  it('renders each note and Remove deletes exactly its rec_id after a confirm', async () => {
    act(() => {
      useDirectSendNotesStore.getState().addNote({ recId: 'R1', kind: 'order-unknown', label: 'AAPL 10 sh', brokerLabel: 'Alpaca Paper', orderId: null });
      useDirectSendNotesStore.getState().addNote({ recId: 'R2', kind: 'not-removed', label: 'MSFT 5 sh', brokerLabel: 'IBKR Paper', orderId: null });
    });
    const confirmSpy = jest.spyOn(window, 'confirm').mockReturnValue(true);
    render(<DirectSendNotesPanel />);
    expect(screen.getByText(/AAPL 10 sh: order status UNKNOWN/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Remove (AAPL 10 sh)' }));
    await waitFor(() => expect(notes().map((n) => n.recId)).toEqual(['R2']));
    expect(api.deletePortfolioPosition).toHaveBeenCalledWith('R1');
    expect(confirmSpy.mock.calls[0][0]).toMatch(/ONLY if Alpaca Paper shows no order/);
    confirmSpy.mockRestore();
  });

  it('a declined confirm deletes nothing', async () => {
    act(() => {
      useDirectSendNotesStore.getState().addNote({ recId: 'R1', kind: 'order-unknown', label: 'AAPL 10 sh', brokerLabel: 'IBKR Paper', orderId: null });
    });
    const confirmSpy = jest.spyOn(window, 'confirm').mockReturnValue(false);
    await removeNoteRow(notes()[0]);
    expect(api.deletePortfolioPosition).not.toHaveBeenCalled();
    expect(notes()).toHaveLength(1);
    confirmSpy.mockRestore();
  });

  it('SAVE-UNCONFIRMED: a 404 on Remove is final, deletes note and clears ownership (#171)', async () => {
    act(() => {
      useDirectSendNotesStore.getState().addNote({
        recId: 'R-UNCONFIRMED',
        kind: 'save-unconfirmed',
        label: 'NVDA 10 sh',
        brokerLabel: 'IBKR Paper',
        orderId: null,
      });
      useStockOrderOwnershipStore.setState({
        bySymbol: { NVDA: { status: 'unknown', recId: 'R-UNCONFIRMED', identity: 'NVDA', message: 'unconfirmed' } },
      });
    });
    (api.deletePortfolioPosition as jest.Mock).mockRejectedValueOnce(new Error("API /api/portfolio/R-UNCONFIRMED → 404: Position not found."));
    const confirmSpy = jest.spyOn(window, 'confirm').mockReturnValue(true);
    await removeNoteRow(notes()[0]);
    expect(notes()).toHaveLength(0);
    expect(useStockOrderOwnershipStore.getState().bySymbol['NVDA']).toBeUndefined();
    confirmSpy.mockRestore();
  });
});

// Exercise the existing save-first/recovery machinery behind the boundary.
// Production has no positive validation authority; separate S2 tests verify
// the real fail-closed boundary with this module unmocked.
jest.mock('@/lib/stockExecutionSession', () => ({
  ...jest.requireActual('@/lib/stockExecutionSession'), stockExecutionBlock: jest.fn(() => null),
}));
beforeEach(() => useStockOrderOwnershipStore.setState({ bySymbol: {} }));

it('blocks a second send while the first save/order is in flight across a new scan and keeps its outcome ownership', async () => {
  let resolveSave!: (reply: Reply) => void;
  saveReply = body => new Promise(resolve => { resolveSave = resolve; });
  const first = send();
  await Promise.resolve();
  const second = await send();
  expect(second.kind).toBe('refused');
  expect(log).toEqual(['save']);
  resolveSave({ ok: true, status: 201, json: async () => ({ entryPrice: 200 }) });
  expect((await first).kind).toBe('placed');
  expect(useStockOrderOwnershipStore.getState().bySymbol.AAPL.status).toBe('placed');
  expect((await send()).kind).toBe('refused');
  expect(log).toEqual(['save', 'order']);
});

it('rechecks validation availability after an async save and sends no broker request if it was revoked', async () => {
  const availability = (await import('@/lib/stockExecutionSession')).stockExecutionBlock as jest.Mock;
  availability.mockReturnValueOnce(null).mockReturnValueOnce('Validation unavailable after save');
  const outcome = await send();
  expect(outcome.kind).toBe('not-placed');
  expect(api.postStockOrder).not.toHaveBeenCalled();
  expect(api.deletePortfolioPosition).toHaveBeenCalledTimes(1);
  expect(log).toEqual(['save']);
  expect(useStockOrderOwnershipStore.getState().bySymbol.AAPL).toBeUndefined();
  availability.mockReturnValue(null);
});

const BEARISH_REASON = 'Bearish setups are Unvalidated: no bearish strategy has passed validation yet (decision STOCKS-PARAMS-PER-HORIZON-2026-10-05). Visible for research; no PASS, no auto-trade, no opening order.';

it('B4 refuses a SELL opening before validation, save or ownership claim', async () => {
  const availability = (await import('@/lib/stockExecutionSession')).stockExecutionBlock as jest.Mock;
  availability.mockReturnValue('Validation unavailable');
  const claim = jest.spyOn(useStockOrderOwnershipStore.getState(), 'claim');
  const out = await sendStockSaveFirst({
    pos: pos(), broker: 'ibkr_paper', orderType: 'LMT', limitPrice: 200, action: 'SELL',
    addPosition: usePortfolioStore.getState().addPosition, earningsVeto: false,
  });
  expect(out).toEqual({ kind: 'not-placed', message: BEARISH_REASON });
  expect(log).toEqual([]);
  expect(api.postStockOrder).not.toHaveBeenCalled();
  expect(claim).not.toHaveBeenCalled();
  expect(notes()).toEqual([]);
  claim.mockRestore();
  availability.mockReturnValue(null);
});

it('B4 uses the exact backend Unvalidated reason', () => {
  expect(BEARISH_UNVALIDATED_MESSAGE).toBe(BEARISH_REASON);
});
it.each(['Bearish', 'Bullish', 'bearish', '', null, undefined])('B4 tests only exact Bearish direction: %s', direction => {
  expect(isBearishUnvalidated(direction)).toBe(direction === 'Bearish');
});

/* STOCKS-HORIZON-P0B B7 — the earnings veto refuses the ORDER even if a button
 * is bypassed: nothing is saved, nothing claimed, no broker request. */
it('B7 refuses an earnings-vetoed send before validation, save or ownership claim', async () => {
  const claim = jest.spyOn(useStockOrderOwnershipStore.getState(), 'claim');
  const out = await sendStockSaveFirst({
    pos: pos(), broker: 'ibkr_paper', orderType: 'LMT', limitPrice: 200, action: 'BUY',
    addPosition: usePortfolioStore.getState().addPosition, earningsVeto: true,
  });
  expect(out).toEqual({ kind: 'refused', message: 'Earnings inside the reject window — no send' });
  expect(log).toEqual([]);
  expect(api.postStockOrder).not.toHaveBeenCalled();
  expect(claim).not.toHaveBeenCalled();
  expect(notes()).toEqual([]);
  expect(positions()).toEqual([]);
  claim.mockRestore();
});
