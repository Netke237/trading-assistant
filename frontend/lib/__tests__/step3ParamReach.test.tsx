/**
 * STEP3-PARAM-REACH — what a scan result records is what Steps 5-7 reuse:
 *  - contextFromScanRequest: a result restored into an empty browser rebuilds
 *    the direction / hold days it was produced from (StoreHydration).
 *  - rrOverridesForPlan: Step 7's recompute-plan reprices with the scan's
 *    Reward/Risk overrides, not Step-3 values edited after the scan.
 *  - missingCardContracts / withCardContract: Step 6 lists the card's own
 *    contract when max_price or limit cut it.
 */
import '@testing-library/jest-dom';
import { render, waitFor } from '@testing-library/react';
import { contextFromScanRequest, resultMatchesContext } from '@/lib/scanContextFromResult';
import { rrOverridesForPlan } from '@/lib/tradeCardOverride';
import { missingCardContracts, withCardContract } from '@/lib/step6CardContract';
import { useScanStore } from '@/lib/scanStore';
import { StoreHydration } from '@/components/StoreHydration';
import { api } from '@/lib/api';
import type { OptionContract, TradeCardData } from '@/types/domain';

jest.mock('@/lib/api', () => ({
  api: {
    getLastScan: jest.fn(),
    getLastScanStatus: jest.fn(),
    getLastStockScan: jest.fn(),
    getLastStockScanStatus: jest.fn(),
    getLastStockScanRequest: jest.fn(),
  },
  getLastDataRefresh: jest.fn(() => Promise.resolve({ last_refresh: null })),
  API_BASE_URL: 'http://localhost:8000',
}));

const m = (f: unknown) => f as jest.Mock;

const RC = {
  universe: ['SP500'], direction: 'Bearish', horizon: 'Position',
  horizon_preset: 'Quarterly', hold_min_days: 45, hold_max_days: 60,
};

describe('contextFromScanRequest', () => {
  it('rebuilds the context Step 3 would have written', () => {
    expect(contextFromScanRequest(RC)).toEqual({
      universe: 'SP500', direction: 'Bearish', horizon: 'Position (45–60d)',
      horizonPreset: 'Quarterly', holdMin: 45, holdMax: 60,
    });
  });

  // Never from the result: the Stocks scan posts [context.universe], so
  // 'Custom' would be scanned as a ticker (round 1) and 'NDX100' would move
  // every later Stocks scan to NDX100 (round 2). Always the null default.
  it.each([[['AAPL', 'MSFT']], [['AAPL']], [[]], [['Custom']], [['NDX100']], [['SECTOR:XLE']]])(
    'universe %j restores as SP500', (universe) => {
      expect(contextFromScanRequest({ ...RC, universe })?.universe).toBe('SP500');
    });

  it('a Custom preset keeps its own hold days', () => {
    expect(contextFromScanRequest({ ...RC, horizon_preset: 'Custom', hold_min_days: 30, hold_max_days: 70 }))
      .toMatchObject({ horizonPreset: 'Custom', holdMin: 30, holdMax: 70, horizon: 'Position (30–70d)' });
  });

  it.each([
    ['no record', null],
    ['no hold days', { ...RC, hold_min_days: null, hold_max_days: null }],
    ['one hold bound', { ...RC, hold_max_days: null }],
    ['inverted hold days', { ...RC, hold_min_days: 60, hold_max_days: 45 }],
    ['fractional hold days', { ...RC, hold_min_days: 4.5 }],
    ['negative hold days', { ...RC, hold_min_days: -1 }],
    ['unknown direction', { ...RC, direction: 'Neutral' }],
    ['unknown scoring horizon', { ...RC, horizon: 'Quarterly' }],
    ['unknown preset key', { ...RC, horizon_preset: 'Weekly' }],
    ['no preset key', { ...RC, horizon_preset: null }],
  ])('%s → null (context left as it is)', (_label, rc) => {
    expect(contextFromScanRequest(rc as never)).toBeNull();
  });
});

describe('resultMatchesContext', () => {
  const CTX = { direction: 'Bearish', horizonPreset: 'Quarterly', holdMin: 45, holdMax: 60 } as const;

  it('matches when direction, preset and hold days agree', () => {
    expect(resultMatchesContext(RC, CTX)).toBe(true);
  });

  it.each([
    ['direction', { ...CTX, direction: 'Bullish' }],
    ['preset', { ...CTX, horizonPreset: 'SemiAnnual' }],
    ['min hold', { ...CTX, holdMin: 40 }],
    ['max hold', { ...CTX, holdMax: 61 }],
  ])('a different %s does not match', (_l, ctx) => {
    expect(resultMatchesContext(RC, ctx as never)).toBe(false);
  });

  it('no record, or no context, cannot be checked and counts as matching', () => {
    expect(resultMatchesContext(null, CTX)).toBe(true);
    expect(resultMatchesContext(undefined, CTX)).toBe(true);
    expect(resultMatchesContext(RC, null)).toBe(true);
  });

  // Round 2: what the scan posted is the SANITISED hold days.
  it('compares against the sanitised context hold days', () => {
    expect(resultMatchesContext(RC, { ...CTX, holdMin: 44.6, holdMax: 60.2 })).toBe(true);
  });
});

describe('rrOverridesForPlan', () => {
  const LIVE = { rr_target_r_multiple: 3, fast_ema: 12 };

  it('sends the scan\'s recorded overrides, not live Step-3 values', () => {
    expect(rrOverridesForPlan({ rr_overrides: { rr_target_r_multiple: 2.5 } }, LIVE))
      .toEqual({ rr_target_r_multiple: 2.5 });
  });

  it('a scan that overrode none sends none, even with live edits', () => {
    expect(rrOverridesForPlan({ rr_overrides: {} }, LIVE)).toEqual({});
  });

  it.each([
    ['absent', {}],
    ['null', { rr_overrides: null }],
  ])('a result with the record %s falls back to live scanOverrides', (_l, result) => {
    expect(rrOverridesForPlan(result, LIVE)).toEqual({ rr_target_r_multiple: 3 });
  });

  it('no result at all falls back to live scanOverrides', () => {
    expect(rrOverridesForPlan(null, LIVE)).toEqual({ rr_target_r_multiple: 3 });
  });
});

describe('missingCardContracts / withCardContract', () => {
  const ID = 'XOM|190|2026-12-18|C';
  const card = (over: Partial<TradeCardData> = {}) => ({
    symbol: 'XOM', contract: ID,
    contractDetails: { strike: 190, expiry: '2026-12-18', right: 'C' },
    ...over,
  }) as TradeCardData;
  const row = (id: string) => ({ id }) as OptionContract;

  it('asks only for a card whose contract is not in its rows', () => {
    expect(missingCardContracts([card()], [[row(ID)]], 'C')).toEqual([]);
    expect(missingCardContracts([card()], [[row('other')]], 'C'))
      .toEqual([{ index: 0, id: ID, expiry: '2026-12-18', strike: 190 }]);
    expect(missingCardContracts([card()], [undefined], 'C')).toHaveLength(1);
  });

  // EXACT-STRIKE ES-3: the backend matches strikes exactly, so the rescue
  // asks for the card's exact strike (182, not 182.5, would return the wrong
  // row or nothing).
  it('sends a fractional strike exactly', () => {
    const c = card({ contract: 'XOM|182.5|2026-12-18|C',
      contractDetails: { strike: 182.5, expiry: '2026-12-18', right: 'C' } as never });
    expect(missingCardContracts([c], [[]], 'C')[0]?.strike).toBe(182.5);
    expect(missingCardContracts([c], [[]], 'C'))
      .toEqual([{ index: 0, id: 'XOM|182.5|2026-12-18|C', expiry: '2026-12-18', strike: 182.5 }]);
  });

  it('skips a card of the other right, or with no contract details', () => {
    expect(missingCardContracts([card()], [[]], 'P')).toEqual([]);
    expect(missingCardContracts([card({ contractDetails: undefined })], [[]], 'C')).toEqual([]);
    expect(missingCardContracts([card({ contract: '' })], [[]], 'C')).toEqual([]);
  });

  it('keeps each request on its own candidate index', () => {
    const other = card({ symbol: 'CVX', contract: 'CVX|150|2026-12-18|C',
      contractDetails: { strike: 150, expiry: '2026-12-18', right: 'C' } as never });
    expect(missingCardContracts([card(), other], [[row(ID)], []], 'C').map((r) => r.index)).toEqual([1]);
  });

  // Ids carry the exact strike, so 182 and 182.5 are different ids.
  it('appends a 182.5 card\'s own row, never the 182 row', () => {
    const HALF = 'XOM|182.5|2026-12-18|C';
    const rows = [row('a')];
    expect(withCardContract(rows, [row('XOM|182|2026-12-18|C'), row(HALF)], HALF).map((r) => r.id))
      .toEqual(['a', HALF]);
    expect(withCardContract(rows, [row('XOM|182|2026-12-18|C')], HALF).map((r) => r.id)).toEqual(['a']);
  });

  it('appends only a row with the card\'s id, never another id', () => {
    const rows = [row('a')];
    const out = withCardContract(rows, [row('XOM|182|2026-12-18|C'), row(ID)], ID);
    expect(out.map((r) => r.id)).toEqual(['a', ID]);
    expect(rows.map((r) => r.id)).toEqual(['a']);
    expect(withCardContract(rows, [row('zzz')], ID).map((r) => r.id)).toEqual(['a']);
    expect(withCardContract([row(ID)], [row(ID)], ID)).toHaveLength(1);
  });
});

describe('StoreHydration restores the context of a recovered options result', () => {
  async function hydrate(result: unknown, persistedContext: unknown = null,
                         opts: { mode?: string; stock?: unknown; stockDelay?: Promise<unknown> } = {}) {
    useScanStore.setState({ scanResult: null, stockScanResult: null, context: null, screenerMode: 'options' } as never);
    localStorage.clear();
    if (persistedContext || opts.mode) {
      localStorage.setItem('bamendjou-scan-store', JSON.stringify({
        version: 17,
        state: { context: persistedContext ?? null, scanResult: null, screenerMode: opts.mode ?? 'options' },
      }));
    }
    for (const f of Object.values(api)) m(f).mockReset();
    m(api.getLastScan).mockResolvedValue(result);
    if (opts.stockDelay) m(api.getLastStockScan).mockReturnValue(opts.stockDelay);
    else m(api.getLastStockScan).mockResolvedValue(opts.stock ?? null);
    m(api.getLastScanStatus).mockResolvedValue({ status: 'idle', updated_at: null });
    m(api.getLastStockScanStatus).mockResolvedValue({ status: 'idle', updated_at: null, strategy: null });
    render(<StoreHydration />);
    await waitFor(() => expect(api.getLastStockScanStatus).toHaveBeenCalled());
  }
  const RESULT = (rc: unknown) => ({
    scan_id: 'S', timestamp: '2026-10-02T10:00:00+00:00', candidates: [], rejected: [],
    ...(rc !== undefined ? { request_context: rc } : {}),
  });

  afterEach(() => localStorage.clear());

  it('an empty browser gets the result\'s direction and hold days, and keeps the result', async () => {
    await hydrate(RESULT(RC));
    const s = useScanStore.getState();
    expect(s.scanResult?.scan_id).toBe('S');
    expect(s.context).toMatchObject({ direction: 'Bearish', horizonPreset: 'Quarterly', holdMin: 45, holdMax: 60 });
  });

  it('a result from before the record leaves the context null', async () => {
    await hydrate(RESULT(undefined));
    expect(useScanStore.getState().scanResult?.scan_id).toBe('S');
    expect(useScanStore.getState().context).toBeNull();
  });

  // Round 1 SHOULD-FIX: setContext cleared the result when Step 3 changed,
  // so a reload must not bring that result back under the new context.
  it('a persisted context the result was not produced for → the result is not restored', async () => {
    const ctx = { universe: 'DOW30', direction: 'Bullish', horizon: 'Swing (5–15d)',
      horizonPreset: 'Swing', holdMin: 5, holdMax: 15 };
    await hydrate(RESULT(RC), ctx);
    expect(useScanStore.getState().scanResult).toBeNull();
    expect(useScanStore.getState().context).toEqual(ctx);
  });

  it('a persisted context the result matches → restored, context untouched', async () => {
    const ctx = { universe: 'DOW30', direction: 'Bearish', horizon: 'Position (45–60d)',
      horizonPreset: 'Quarterly', holdMin: 45, holdMax: 60 };
    await hydrate(RESULT(RC), ctx);
    expect(useScanStore.getState().scanResult?.scan_id).toBe('S');
    expect(useScanStore.getState().context).toEqual(ctx);
  });

  it('a result from before the record is restored under any persisted context, as before', async () => {
    const ctx = { universe: 'SP500', direction: 'Bullish', horizon: 'Swing (5–15d)',
      horizonPreset: 'Swing', holdMin: 5, holdMax: 15 };
    await hydrate(RESULT(undefined), ctx);
    expect(useScanStore.getState().scanResult?.scan_id).toBe('S');
  });

  // Round 4: ScanContext is shared with Stocks mode.
  it('in Stocks mode defers recorded options recovery rather than using default context', async () => {
    await hydrate(RESULT(RC), null, { mode: 'stocks' });
    expect(useScanStore.getState().scanResult).toBeNull();
    expect(useScanStore.getState().context).toBeNull();
  });

  it('with a stock result held defers recorded options recovery and preserves stocks', async () => {
    await hydrate(RESULT(RC), null, {
      stock: { scan_id: 'K', timestamp: '2026-10-02T09:00:00+00:00', candidates: [], rejected: [] },
    });
    expect(useScanStore.getState().stockScanResult?.scan_id).toBe('K');
    expect(useScanStore.getState().scanResult).toBeNull();
    expect(useScanStore.getState().context).toBeNull();
  });

  it('an unusable recorded context does not publish a result under defaults', async () => {
    await hydrate(RESULT({ ...RC, horizon_preset: 'Unknown' }));
    expect(useScanStore.getState().scanResult).toBeNull();
    expect(useScanStore.getState().context).toBeNull();
  });

  // Round 4: Step 6 fetches as soon as the candidates change, so the result
  // and its rebuilt context must land in the same store update tick.
  it('the restored result never appears without its context, even when the stock fetch is slow', async () => {
    let releaseStock: (v: unknown) => void = () => {};
    const seen: Array<{ result: boolean; context: boolean }> = [];
    const unsub = useScanStore.subscribe((st) => {
      if (st.scanResult) seen.push({ result: true, context: st.context !== null });
    });
    const done = hydrate(RESULT(RC), null, { stockDelay: new Promise((r) => { releaseStock = r; }) });
    await new Promise((r) => setTimeout(r, 20));
    releaseStock(null);
    await done;
    unsub();
    expect(seen.length).toBeGreaterThan(0);
    expect(seen.every((x) => x.context)).toBe(true);
  });
});
