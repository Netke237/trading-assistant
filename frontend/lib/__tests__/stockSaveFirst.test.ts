/*
 * STOCK-SENDS-SAVE-FIRST-THEN-REAL-SHARES (plan B5 tests 1-9, R1 test 14, Q2).
 * `placeStockOrderSaveFirst` is a plain async function, so it is tested
 * directly: a method- and URL-aware fetch mock (the save) and a mocked
 * `@/lib/api` (the broker order and the delete).
 */
import { placeStockOrderSaveFirst } from '@/lib/stockSaveFirst';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useDirectSendNotesStore } from '@/lib/directSendNotesStore';
import { buildPaperStockPosition } from '@/lib/paperTrade';
import { directSendNoteText, removeConfirmText } from '@/lib/directOrder';
import { api } from '@/lib/api';
import type { PortfolioPosition } from '@/types/domain';

jest.mock('@/lib/api', () => ({
  api: {
    postStockOrder: jest.fn(),
    deletePortfolioPosition: jest.fn(),
  },
}));

const log: string[] = [];
type Reply = (body: Record<string, unknown>) => Promise<unknown>;
const echo: Reply = (body) => Promise.resolve({ ok: true, status: 201, json: async () => body });
let persistReply: Reply = echo;
let persistBodies: Record<string, unknown>[] = [];

function installFetch() {
  global.fetch = jest.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === 'POST' && String(url).endsWith('/api/portfolio')) {
      log.push('persist');
      const body = JSON.parse(String(init.body));
      persistBodies.push(body);
      return persistReply(body);
    }
    return { ok: true, status: 200, json: async () => [] };
  }) as unknown as typeof fetch;
}

function pos(overrides: Partial<PortfolioPosition> = {}, shares = 200, rungs: number[] = []): PortfolioPosition {
  return {
    ...buildPaperStockPosition('AAA', 50, shares, 'Bullish', undefined, {
      stop: 45,
      targets: rungs.map((q, i) => ({ price: 55 + i, shares: q })),
    }),
    source: 'broker',
    sourceLabel: 'IBKR Paper — Limit (ID: pending)',
    ...overrides,
  };
}

const send = (p: PortfolioPosition, broker = 'ibkr_paper', orderType: 'LMT' | 'MKT' = 'LMT') =>
  placeStockOrderSaveFirst({ pos: p, broker, orderType, limitPrice: orderType === 'LMT' ? 50 : null, action: 'BUY' });

const orderMock = api.postStockOrder as jest.Mock;
const deleteMock = api.deletePortfolioPosition as jest.Mock;
const notes = () => useDirectSendNotesStore.getState().notes;
const rows = () => usePortfolioStore.getState().positions;

beforeEach(() => {
  jest.clearAllMocks();
  log.length = 0;
  persistBodies = [];
  persistReply = echo;
  installFetch();
  usePortfolioStore.setState({ positions: [] });
  useDirectSendNotesStore.setState({ notes: [] });
  orderMock.mockImplementation(async () => { log.push('order'); return { order_id: 'ORD-1', status: 'submitted' }; });
  deleteMock.mockResolvedValue(undefined);
});

it('1. saves BEFORE it sends the order', async () => {
  const out = await send(pos());
  expect(out.kind).toBe('placed');
  expect(log).toEqual(['persist', 'order']);
});

it('2. a refused save sends no order, deletes nothing and pushes no note', async () => {
  persistReply = () => Promise.resolve({
    ok: false, status: 422, json: async () => ({ detail: 'Refused: total_exposure_limit_reached' }),
  });
  const out = await send(pos());
  expect(out.kind).toBe('refused');
  expect(out.kind === 'refused' && out.message).toMatch(/No order was sent — .*total_exposure_limit_reached/);
  expect(orderMock).not.toHaveBeenCalled();
  expect(deleteMock).not.toHaveBeenCalled();
  expect(notes()).toHaveLength(0);
});

it('3. an unreachable Portfolio sends no order and leaves a SAVE-UNCONFIRMED note', async () => {
  global.fetch = jest.fn().mockRejectedValue(new Error('offline')) as unknown as typeof fetch;
  const p = pos();
  const out = await send(p);
  expect(out.kind).toBe('unconfirmed');
  expect(orderMock).not.toHaveBeenCalled();
  expect(deleteMock).toHaveBeenCalledWith(p.recId);
  expect(notes()).toEqual([expect.objectContaining({ recId: p.recId, kind: 'save-unconfirmed' })]);
  expect(rows()).toHaveLength(0);
});

it('4. a resize sends the APPROVED quantity, books it, and scales the rungs (Q2)', async () => {
  persistReply = (body) => echo({ ...body, adjustedQty: 100 });
  const out = await send(pos({}, 200, [66, 66, 68]));
  expect(orderMock).toHaveBeenCalledWith(expect.objectContaining({ quantity: 100 }));
  expect(out).toEqual(expect.objectContaining({ kind: 'placed', qty: 100 }));
  expect(out.kind === 'placed' && out.message).toMatch(/sized it to 100 shares/);
  const row = rows()[0]!;
  expect(row.contracts).toBe(100);
  expect(row.targets.map((t) => t.contractsToSell)).toEqual([33, 33, 34]);
  expect(row.sourceLabel).toBe('IBKR Paper — Limit (ID: ORD-1)');
});

describe('5. a provably pre-submit failure deletes the saved row', () => {
  const cases: [string, () => Promise<unknown>][] = [
    ['422', () => Promise.reject(new Error('API /broker/stock-order → 422: bad'))],
    ['503 credentials', () => Promise.reject(new Error('API /broker/stock-order → 503: Broker credentials unavailable: x'))],
    ['Unknown broker', () => Promise.reject(new Error('API /broker/stock-order → 400: Unknown broker foo'))],
    ['live trading via', () => Promise.reject(new Error('API /broker/stock-order → 400: live trading via x is disabled'))],
    ['IBKR confirm 502', () => Promise.reject(new Error('API /broker/stock-order → 502: IBKR did not place the order: q'))],
    ['status Rejected', () => Promise.resolve({ order_id: 'X', status: 'Rejected' })],
  ];
  it.each(cases)('%s', async (_name, reply) => {
    orderMock.mockImplementation(reply);
    const p = pos();
    const out = await send(p);
    expect(out.kind).toBe('removed');
    expect(deleteMock).toHaveBeenCalledWith(p.recId);
    expect(rows()).toHaveLength(0);
    expect(notes()).toHaveLength(0);
  });
});

describe('6. anything else keeps the row with an ORDER-UNKNOWN note', () => {
  const cases: [string, () => Promise<unknown>][] = [
    ['Tastytrade limit-only 400', () => Promise.reject(new Error('API /broker/stock-order → 400: TastytradePaperAdapter only supports limit orders'))],
    ['Tradier 502', () => Promise.reject(new Error('API /broker/stock-order → 502: Tradier paper order failed: HTTP 401'))],
    ['TypeError', () => Promise.reject(new TypeError('Failed to fetch'))],
    ['empty order_id', () => Promise.resolve({ order_id: '', status: 'submitted' })],
    ['Inactive', () => Promise.resolve({ order_id: 'X9', status: 'Inactive' })],
    ['plain Error', () => Promise.reject(new Error('boom'))],
  ];
  it.each(cases)('%s', async (_name, reply) => {
    orderMock.mockImplementation(reply);
    persistReply = (body) => echo({ ...body, adjustedQty: 100 });
    const p = pos({}, 200, [66, 66, 68]);
    const out = await send(p);
    expect(out.kind).toBe('unknown');
    expect(deleteMock).not.toHaveBeenCalled();
    expect(notes()).toEqual([expect.objectContaining({ recId: p.recId, kind: 'order-unknown' })]);
    const row = rows()[0]!;
    expect(row.recId).toBe(p.recId);
    // Q2: the kept row carries the scaled rungs too.
    expect(row.contracts).toBe(100);
    expect(row.targets.map((t) => t.contractsToSell)).toEqual([33, 33, 34]);
  });

  it('pushes the note BEFORE the row is added', async () => {
    orderMock.mockRejectedValue(new Error('boom'));
    const seen: number[] = [];
    const unsub = usePortfolioStore.subscribe((s) => { if (s.positions.length) seen.push(notes().length); });
    await send(pos());
    unsub();
    expect(seen[0]).toBe(1);
  });
});

it('7. a stock already tracked is refused locally: no save, no order', async () => {
  usePortfolioStore.setState({ positions: [pos({ recId: 'OLD' })] });
  const out = await send(pos());
  expect(out.kind).toBe('blocked');
  expect(log).toEqual([]);
});

it('8. a 2xx whose body did not parse sends no order', async () => {
  persistReply = () => Promise.resolve({ ok: true, status: 201, json: async () => { throw new Error('bad json'); } });
  const out = await send(pos());
  expect(out.kind).toBe('unconfirmed');
  expect(orderMock).not.toHaveBeenCalled();
});

it('9. a pre-submit failure whose delete fails leaves a NOT-REMOVED note', async () => {
  orderMock.mockRejectedValue(new Error('API /broker/stock-order → 422: bad'));
  deleteMock.mockRejectedValue(new Error('API /api/portfolio/x → 500: db down'));
  const p = pos();
  const out = await send(p);
  expect(out.kind).toBe('not-removed');
  expect(notes()).toEqual([expect.objectContaining({ recId: p.recId, kind: 'not-removed' })]);
});

it('14. an Alpaca ORDER-UNKNOWN note names Alpaca, never IBKR (R1)', async () => {
  orderMock.mockRejectedValue(new Error('API /broker/stock-order → 502: Alpaca paper order failed: connection error'));
  await send(pos({ sourceLabel: 'Alpaca Paper — Limit (ID: pending)' }), 'alpaca_paper');
  const n = notes()[0]!;
  expect(directSendNoteText(n)).toContain('Alpaca Paper');
  expect(removeConfirmText(n)).toContain('Alpaca Paper');
  expect(directSendNoteText(n) + removeConfirmText(n)).not.toMatch(/IBKR/);
});

it('Tastytrade + Market is refused before anything is saved', async () => {
  const out = await send(pos(), 'tastytrade_paper', 'MKT');
  expect(out.kind).toBe('blocked');
  expect(log).toEqual([]);
});
