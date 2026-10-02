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
import { contextFromScanRequest } from '@/lib/scanContextFromResult';
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

  it('a list of symbols (Custom or Watchlist) is Custom', () => {
    expect(contextFromScanRequest({ ...RC, universe: ['AAPL', 'MSFT'] })?.universe).toBe('Custom');
    expect(contextFromScanRequest({ ...RC, universe: ['AAPL'] })?.universe).toBe('Custom');
    expect(contextFromScanRequest({ ...RC, universe: [] })?.universe).toBe('Custom');
  });

  it('a named sector universe keeps its name', () => {
    expect(contextFromScanRequest({ ...RC, universe: ['SECTOR:XLE'] })?.universe).toBe('SECTOR:XLE');
  });

  it('an unknown or absent preset key with hold days is Custom', () => {
    expect(contextFromScanRequest({ ...RC, horizon_preset: 'Weekly' })?.horizonPreset).toBe('Custom');
    expect(contextFromScanRequest({ ...RC, horizon_preset: null })?.horizonPreset).toBe('Custom');
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
  ])('%s → null (context left as it is)', (_label, rc) => {
    expect(contextFromScanRequest(rc as never)).toBeNull();
  });
});

describe('rrOverridesForPlan', () => {
  const LIVE = { rr_bullish_target_pct: 0.5, rr_bearish_target_pct: 0.4, fast_ema: 12 };

  it('sends the scan\'s recorded overrides, not live Step-3 values', () => {
    expect(rrOverridesForPlan({ rr_overrides: { rr_bullish_target_pct: 0.12 } }, LIVE))
      .toEqual({ rr_bullish_target_pct: 0.12 });
  });

  it('a scan that overrode none sends none, even with live edits', () => {
    expect(rrOverridesForPlan({ rr_overrides: {} }, LIVE)).toEqual({});
  });

  it.each([
    ['absent', {}],
    ['null', { rr_overrides: null }],
  ])('a result with the record %s falls back to live scanOverrides', (_l, result) => {
    expect(rrOverridesForPlan(result, LIVE)).toEqual({ rr_bullish_target_pct: 0.5, rr_bearish_target_pct: 0.4 });
  });

  it('no result at all falls back to live scanOverrides', () => {
    expect(rrOverridesForPlan(null, LIVE)).toEqual({ rr_bullish_target_pct: 0.5, rr_bearish_target_pct: 0.4 });
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

  it('truncates a fractional strike as the backend does', () => {
    const c = card({ contractDetails: { strike: 182.5, expiry: '2026-12-18', right: 'C' } as never });
    expect(missingCardContracts([c], [[]], 'C')[0]?.strike).toBe(182);
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

  it('appends only the row whose id is the card\'s contract', () => {
    const rows = [row('a')];
    const out = withCardContract(rows, [row('XOM|182|2026-12-18|C'), row(ID)], ID);
    expect(out.map((r) => r.id)).toEqual(['a', ID]);
    expect(rows.map((r) => r.id)).toEqual(['a']);
    expect(withCardContract(rows, [row('zzz')], ID).map((r) => r.id)).toEqual(['a']);
    expect(withCardContract([row(ID)], [row(ID)], ID)).toHaveLength(1);
  });
});

describe('StoreHydration restores the context of a recovered options result', () => {
  async function hydrate(result: unknown, persistedContext: unknown = null) {
    useScanStore.setState({ scanResult: null, context: null } as never);
    localStorage.clear();
    if (persistedContext) {
      localStorage.setItem('bamendjou-scan-store', JSON.stringify({
        version: 17, state: { context: persistedContext, scanResult: null },
      }));
    }
    for (const f of Object.values(api)) m(f).mockReset();
    m(api.getLastScan).mockResolvedValue(result);
    m(api.getLastStockScan).mockResolvedValue(null);
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

  it('a persisted context is never overwritten', async () => {
    const ctx = { universe: 'DOW30', direction: 'Bullish', horizon: 'Swing (5–15d)',
      horizonPreset: 'Swing', holdMin: 5, holdMax: 15 };
    await hydrate(RESULT(RC), ctx);
    expect(useScanStore.getState().context).toEqual(ctx);
  });
});
