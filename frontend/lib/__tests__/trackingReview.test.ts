/**
 * #582 (TC-REVIEW-07) — the store half of the basket's server review.
 *
 * `previewPosition` asks for exactly the body the create sends; a reviewed
 * `addPosition` sends that same body with `X-Review-Fingerprint`, adopts the
 * complete saved row at once, treats a 412 as review-required (nothing saved),
 * resolves a 409 by recId, never by the contract alone, and a pending retry
 * carries the ORIGINAL fingerprint so it can never approve a new resolution.
 */
import { act } from '@testing-library/react';
import { usePortfolioStore, previewPosition, parsePreview, REVIEW_FINGERPRINT_HEADER } from '@/lib/portfolioStore';
import { reviewLines, savedDifferences, type TrackingPreview } from '@/lib/trackingReview';
import type { PortfolioPosition } from '@/types/domain';

const originalFetch = global.fetch;

function request(o: Partial<PortfolioPosition> = {}): PortfolioPosition {
  return {
    symbol: 'AAA', contract: 'AAA 150C 05/15', direction: 'Bullish',
    entryDate: '2026-11-08', expiry: '2026-05-15', dteRemaining: 24, dteTotal: 24,
    entryPrice: 2.5, currentPrice: 2.5, pnlDollar: 0, pnlPct: 0,
    stop: 140, stopIsUserSet: false, structuralStop: 138, exitPlan: null, maxLossOverride: null,
    premiumStopDollar: 1.5, premiumStopPct: 0.6,
    targets: [{ stockPrice: 160, targetPrice: 160, contractsToSell: 2 }],
    status: 'PASS', ivRank: 45, iv: 0.3, delta: 0.45, theta: -0.09, vega: 0.2,
    contracts: 2, source: 'manual', orderedAt: '2026-11-08T10:00:00', recId: 'REC-AAA',
    tradeCardSnapshot: { why: 'card' },
    pickedMethod: 'monte_carlo', pickedRowStockPrice: 165, pickedRowOptionPrice: 4.1,
    pickedStopBasis: 'stock', pickedAt: '2026-11-08T09:00:00.000Z',
    scanStockPrice: 150,
    ...o,
  } as PortfolioPosition;
}

/** The row the server would store: re-quoted, re-anchored (+1), fraction derived. */
function savedRow(o: Record<string, unknown> = {}) {
  return {
    id: 'uuid-1', recId: 'REC-AAA', symbol: 'AAA', contract: 'AAA 150C 05/15', direction: 'Bullish',
    entryPrice: 2.8, qty: 2, entryDate: '2026-11-08', stop: 141, structuralStop: 139,
    exitPlan: null, maxLossOverride: null, premiumStopPct: 1.5 / 2.8,
    activeTpMethod: 'monte_carlo', resolvedTpPrice: 165, resolvedTpUpdatedAt: '2026-11-08T10:00:01+00:00',
    pickedMethod: 'monte_carlo', pickedRowStockPrice: 165, pickedRowOptionPrice: 4.1,
    pickedStopBasis: 'stock', pickedAt: '2026-11-08T09:00:00.000Z', holdMaxDays: null,
    alertOverrides: {}, targets: [{ stockPrice: 161, targetPrice: 161, contractsToSell: 2 }],
    dteTotal: 24, createdAt: '2026-11-08T10:00:01',
    ...o,
  };
}

function previewOf(row = savedRow(), fingerprint = 'v1:reviewed'): TrackingPreview {
  return parsePreview({
    fingerprint, position: { ...row, id: '', createdAt: '' }, entryFromLiveQuote: true,
    inheritedPremiumStopPct: null,
    differences: [
      { field: 'entryPrice', requested: 2.5, effective: 2.8, reason: 'live_quote' },
      { field: 'stop', requested: 140, effective: 141, reason: 'reanchored' },
    ],
  })!;
}

type Reply = { status: number; body?: unknown } | 'network';
function installFetch(routes: { post?: Reply[]; get?: Reply[]; preview?: Reply[] }) {
  const queues = { post: [...(routes.post ?? [])], get: [...(routes.get ?? [])], preview: [...(routes.preview ?? [])] };
  global.fetch = jest.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    const u = String(url);
    const kind = u.endsWith('/api/portfolio/preview') ? 'preview'
      : u.endsWith('/api/portfolio') && init?.method === 'POST' ? 'post'
      : u.endsWith('/api/portfolio') ? 'get' : null;
    if (!kind) throw new Error(`unexpected request ${u}`);
    const reply = queues[kind].shift();
    if (!reply || reply === 'network') throw new TypeError('Failed to fetch');
    return { ok: reply.status < 300, status: reply.status, json: async () => reply.body ?? {} };
  }) as unknown as typeof fetch;
}
const calls = () => (global.fetch as jest.Mock).mock.calls as [string, RequestInit | undefined][];
const posts = () => calls().filter(([u, i]) => u.endsWith('/api/portfolio') && i?.method === 'POST');
const headerOf = (init: RequestInit | undefined) => (init?.headers as Record<string, string> | undefined)?.[REVIEW_FINGERPRINT_HEADER];

beforeEach(() => {
  localStorage.clear();
  act(() => { usePortfolioStore.setState({ positions: [], lastSyncError: null, premiumStopDropQueue: [], lastPremiumStopDropped: null }); });
});
afterEach(() => { global.fetch = originalFetch; });

describe('#582 previewPosition', () => {
  it('asks the server about exactly the body the create sends, and writes nothing locally', async () => {
    installFetch({ preview: [{ status: 200, body: { ...previewOf(), position: { ...savedRow(), id: '', createdAt: '' } } }], post: [{ status: 201, body: savedRow() }] });
    const out = await previewPosition(request());
    expect(out.kind).toBe('ok');
    expect(usePortfolioStore.getState().positions).toHaveLength(0);
    await usePortfolioStore.getState().addPosition(request());
    const [[previewUrl, previewInit], [, createInit]] = calls();
    expect(previewUrl).toMatch(/\/api\/portfolio\/preview$/);
    expect(previewInit!.body).toBe(createInit!.body);
    expect(headerOf(previewInit)).toBeUndefined();
  });

  it('reports the create\'s own refusal as rejected and an unreachable server as network', async () => {
    installFetch({ preview: [{ status: 409, body: { detail: "Position with contract 'AAA 150C 05/15' already exists." } }, 'network'] });
    expect(await previewPosition(request())).toEqual({ kind: 'rejected', detail: "Position with contract 'AAA 150C 05/15' already exists." });
    expect(await previewPosition(request())).toEqual({ kind: 'network' });
  });
});

describe('#582 reviewed addPosition', () => {
  it('sends the reviewed fingerprint in a header — the body is unchanged', async () => {
    installFetch({ post: [{ status: 201, body: savedRow() }, { status: 201, body: savedRow({ recId: 'REC-B', contract: 'BBB' }) }] });
    await usePortfolioStore.getState().addPosition(request(), { review: { fingerprint: 'v1:reviewed', preview: previewOf() } });
    await usePortfolioStore.getState().addPosition(request({ recId: 'REC-B', contract: 'BBB' }));
    const [[, reviewed], [, plain]] = posts();
    expect(headerOf(reviewed)).toBe('v1:reviewed');
    expect(headerOf(plain)).toBeUndefined();
    const a = JSON.parse(String(reviewed!.body)); const b = JSON.parse(String(plain!.body));
    expect({ ...a, recId: 0, contract: 0 }).toEqual({ ...b, recId: 0, contract: 0 });
  });

  it('adopts the COMPLETE saved row immediately and keeps local-only metadata', async () => {
    installFetch({ post: [{ status: 201, body: savedRow() }] });
    const res = await usePortfolioStore.getState().addPosition(request(), { review: { fingerprint: 'v1:reviewed', preview: previewOf() } });
    expect(res.status).toBe('ok');
    const [row] = usePortfolioStore.getState().positions;
    expect(row).toMatchObject({
      entryPrice: 2.8, currentPrice: 2.8, contracts: 2, stop: 141, structuralStop: 139,
      targets: [{ stockPrice: 161, targetPrice: 161, contractsToSell: 2 }],
      premiumStopPct: 1.5 / 2.8, activeTpMethod: 'monte_carlo', resolvedTpPrice: 165,
      resolvedTpUpdatedAt: '2026-11-08T10:00:01+00:00', syncStatus: 'synced',
      // local-only metadata survives
      source: 'manual', tradeCardSnapshot: { why: 'card' }, ivRank: 45, scanStockPrice: 150,
      expiry: '2026-05-15', stopIsUserSet: false,
    });
    expect(row).not.toHaveProperty('premiumStopDollar');
    expect(row!.reviewFingerprint).toBeUndefined();
    expect(row!.syncPendingSince).toBeUndefined();
  });

  it('a 412 is review-required: nothing kept, no failure banner, the new preview returned', async () => {
    const fresh = previewOf(savedRow({ entryPrice: 3.1 }), 'v1:fresh');
    installFetch({ post: [{ status: 412, body: { detail: { code: 'review_required', message: 'changed', preview: { ...savedRow({ entryPrice: 3.1 }), fingerprint: 'v1:fresh', position: { ...savedRow({ entryPrice: 3.1 }), id: '', createdAt: '' } } } } }] });
    const res = await usePortfolioStore.getState().addPosition(request(), { review: { fingerprint: 'v1:reviewed', preview: previewOf() } });
    expect(res.status).toBe('review_required');
    expect(res.preview?.fingerprint).toBe(fresh.fingerprint);
    expect(res.preview?.position.entryPrice).toBe(3.1);
    expect(usePortfolioStore.getState().positions).toHaveLength(0);
    expect(usePortfolioStore.getState().lastSyncError).toBeNull();
  });

  it('a 409 is resolved by recId: this row\'s save is adopted', async () => {
    installFetch({ post: [{ status: 409, body: { detail: 'exists' } }], get: [{ status: 200, body: [savedRow()] }] });
    const res = await usePortfolioStore.getState().addPosition(request(), { review: { fingerprint: 'v1:reviewed', preview: previewOf() } });
    expect(res.status).toBe('ok');
    expect(res.savedDiffers).toBeUndefined();
    expect(usePortfolioStore.getState().positions[0]).toMatchObject({ recId: 'REC-AAA', stop: 141, syncStatus: 'synced' });
  });

  it('a 409 for a contract held under ANOTHER recId is not this row\'s save', async () => {
    installFetch({ post: [{ status: 409, body: { detail: 'exists' } }], get: [{ status: 200, body: [savedRow({ recId: 'REC-OTHER' })] }] });
    const res = await usePortfolioStore.getState().addPosition(request(), { review: { fingerprint: 'v1:reviewed', preview: previewOf() } });
    expect(res.status).toBe('rejected');
    expect(res.detail).toMatch(/already open under another row/);
    expect(usePortfolioStore.getState().positions).toHaveLength(0);
  });

  it('a recId-matched save with other values is adopted and reported, never claimed as this review', async () => {
    installFetch({ post: [{ status: 409 }], get: [{ status: 200, body: [savedRow({ stop: 139.5 })] }] });
    const res = await usePortfolioStore.getState().addPosition(request(), { review: { fingerprint: 'v1:reviewed', preview: previewOf() } });
    expect(res.status).toBe('ok');
    expect(res.savedDiffers).toEqual(['stop']);
    expect(usePortfolioStore.getState().positions[0]!.stop).toBe(139.5);
  });

  it('a network failure leaves a pending row that carries the ORIGINAL fingerprint into every retry', async () => {
    installFetch({ post: ['network', { status: 412, body: { detail: { code: 'review_required', preview: { fingerprint: 'v1:new', position: { ...savedRow({ entryPrice: 3.3 }), id: '', createdAt: '' } } } } }], get: [{ status: 200, body: [] }] });
    const res = await usePortfolioStore.getState().addPosition(request(), { review: { fingerprint: 'v1:reviewed', preview: previewOf() } });
    expect(res.status).toBe('pending');
    expect(usePortfolioStore.getState().positions[0]).toMatchObject({ syncStatus: 'pending', reviewFingerprint: 'v1:reviewed' });

    await act(async () => { await usePortfolioStore.getState().syncFromBackend(true); });
    const [, retry] = posts();
    expect(headerOf(retry![1])).toBe('v1:reviewed');
    // The resolution changed: the retry can never approve it.
    expect(usePortfolioStore.getState().positions).toHaveLength(0);
    expect(usePortfolioStore.getState().lastSyncError?.detail).toMatch(/changed since you reviewed/);
  });

  it('a pending reviewed row whose retry saves adopts the saved row', async () => {
    installFetch({ post: ['network', { status: 201, body: savedRow() }], get: [{ status: 200, body: [] }] });
    await usePortfolioStore.getState().addPosition(request(), { review: { fingerprint: 'v1:reviewed', preview: previewOf() } });
    await act(async () => { await usePortfolioStore.getState().syncFromBackend(true); });
    expect(usePortfolioStore.getState().positions[0]).toMatchObject({ stop: 141, entryPrice: 2.8, syncStatus: 'synced', source: 'manual' });
    expect(usePortfolioStore.getState().positions[0]!.reviewFingerprint).toBeUndefined();
  });

  it('a pending reviewed row whose contract appears under another recId is reported, not silently replaced', async () => {
    installFetch({ post: ['network'], get: [{ status: 200, body: [savedRow({ recId: 'REC-OTHER' })] }] });
    await usePortfolioStore.getState().addPosition(request(), { review: { fingerprint: 'v1:reviewed', preview: previewOf() } });
    await act(async () => { await usePortfolioStore.getState().syncFromBackend(true); });
    expect(usePortfolioStore.getState().lastSyncError?.detail).toMatch(/reviewed tracking row was not saved/);
    expect(posts()).toHaveLength(1);
  });

  it('syncToBackend re-POSTs a pending reviewed row only under its original fingerprint', async () => {
    installFetch({ post: ['network', { status: 412, body: { detail: { code: 'review_required' } } }] });
    await usePortfolioStore.getState().addPosition(request(), { review: { fingerprint: 'v1:reviewed', preview: previewOf() } });
    await usePortfolioStore.getState().syncToBackend();
    expect(headerOf(posts()[1]![1])).toBe('v1:reviewed');
    expect(usePortfolioStore.getState().positions[0]).toMatchObject({ syncStatus: 'pending', reviewFingerprint: 'v1:reviewed' });
  });

  it('no broker endpoint is ever called by tracking', async () => {
    installFetch({ post: [{ status: 201, body: savedRow() }] });
    await usePortfolioStore.getState().addPosition(request(), { review: { fingerprint: 'v1:reviewed', preview: previewOf() } });
    for (const [u] of calls()) expect(u).not.toMatch(/broker|order/);
  });
});

describe('#582 review helpers', () => {
  it('lines show requested against server-resolved, with the writer\'s reason', () => {
    const lines = reviewLines(request(), previewOf(), 0.6);
    const by = Object.fromEntries(lines.map((l) => [l.key, l]));
    expect(by.stop).toMatchObject({ requested: '$140.00 · plan level', effective: '$141.00', adjusted: true, note: 're-anchored to the live underlying' });
    expect(by.entry).toMatchObject({ requested: '$2.50/share', adjusted: true });
    expect(by.entry!.effective).toMatch(/\$2\.80\/share · save-time live quote/);
    expect(by.qty).toMatchObject({ requested: '2', effective: '2', adjusted: false });
    expect(by.targetAlert!.effective).toBe('Monte Carlo stock level · stock $165.00');
    expect(by.premiumStop!.requested).toBe('$1.50/share');
    expect(by.premiumStop!.effective).toMatch(/53\.6% of the \$2\.80 entry · fires at \$1\.30\/share/);
  });

  it('savedDifferences is empty for the reviewed row', () => {
    const p = previewOf();
    expect(savedDifferences(p.position, p)).toEqual([]);
  });
});
