/*
 * strategyProfilesStore (STOCKS-HORIZON-T1 H5) holds ONLY a validated
 * GET /api/config/strategy-profiles payload. No fallback
 * (T1-PROFILES-NO-FALLBACK-2026-10-09): a failed or malformed fetch clears it.
 */
import {
  useStrategyProfilesStore, parseStrategyProfiles, profileView,
} from '@/lib/strategyProfilesStore';
import { api } from '@/lib/api';
import { profilesPayload, withTuned } from '@/lib/testFixtures/strategyProfiles';

jest.mock('@/lib/api', () => ({ api: { getStrategyProfiles: jest.fn() } }));
const get = api.getStrategyProfiles as jest.Mock;
const state = () => useStrategyProfilesStore.getState();

beforeEach(() => {
  get.mockReset();
  useStrategyProfilesStore.setState({ profiles: null, status: 'idle', error: null });
});

describe('parseStrategyProfiles', () => {
  it('accepts the backend payload', () => {
    const parsed = parseStrategyProfiles(profilesPayload());
    expect(parsed.pullback_ema.Bullish.horizons.Quarterly.params.tolerance).toBe(0.04);
    expect(parsed.mean_reversion_multi.Bearish.horizons.Annual.source).toBe('baseline');
  });

  const broken = (mutate: (p: ReturnType<typeof profilesPayload>) => void) => {
    const p = profilesPayload();
    mutate(p);
    return p;
  };

  it.each([
    ['a non-object',           'nope', /expected an object/],
    ['a missing strategy',     broken((p) => { delete (p as Record<string, unknown>).ma_crossover; }), /^ma_crossover: /],
    ['a missing direction',    broken((p) => { delete (p.breakout_base as Record<string, unknown>).Bearish; }), /^breakout_base\.Bearish: /],
    ['a missing baseline',     broken((p) => { delete (p.pullback_ema.Bullish as Record<string, unknown>).baseline; }), /^pullback_ema\.Bullish\.baseline: /],
    ['a missing horizon',      broken((p) => { delete p.pullback_ema.Bullish.horizons.SemiAnnual; }), /^pullback_ema\.Bullish\.horizons\.SemiAnnual: /],
    ['an unknown source',      broken((p) => { (p.ma_crossover.Bearish.horizons.Swing as { source: string }).source = 'guess'; }), /^ma_crossover\.Bearish\.horizons\.Swing\.source: /],
    ['params not an object',   broken((p) => { (p.ma_crossover.Bearish.horizons.Swing as { params: unknown }).params = [1]; }), /^ma_crossover\.Bearish\.horizons\.Swing\.params: /],
    ['a string period',        broken((p) => { p.ma_crossover.Bullish.horizons.Position.params.fast = '20'; }), /^ma_crossover\.Bullish\.horizons\.Position\.params\.fast: /],
    ['a non-boolean choppy',   broken((p) => { p.mean_reversion_rsi.Bullish.baseline.require_choppy_regime = 1; }), /^mean_reversion_rsi\.Bullish\.baseline\.require_choppy_regime: /],
    ['variants not strings',   broken((p) => { p.mean_reversion_multi.Bullish.horizons.Swing.params.variants = [1]; }), /^mean_reversion_multi\.Bullish\.horizons\.Swing\.params\.variants: /],
    ['a string vwap lookback', broken((p) => {
      (p.mean_reversion_multi.Bearish.horizons.Annual.params.variant_params as Record<string, Record<string, unknown>>)
        .mean_reversion_vwap_daily.vwap_lookback = 'x';
    }), /^mean_reversion_multi\.Bearish\.horizons\.Annual\.params\.variant_params\.mean_reversion_vwap_daily\.vwap_lookback: /],
  ])('refuses %s, naming the path', (_n, payload, msg) => {
    expect(() => parseStrategyProfiles(payload)).toThrow(msg);
  });
});

describe('useStrategyProfilesStore', () => {
  it('a good payload gives ready and the parsed profiles', async () => {
    get.mockResolvedValue(profilesPayload());
    await state().fetch();
    expect(state().status).toBe('ready');
    expect(state().profiles?.ma_crossover.Bullish.baseline.fast).toBe(20);
    expect(state().error).toBeNull();
  });

  it('a failed fetch leaves profiles null and status failed (no fallback)', async () => {
    get.mockResolvedValue(profilesPayload());
    await state().fetch();
    get.mockRejectedValue(new Error('GET /api/config/strategy-profiles → 500'));
    await state().fetch();
    expect(state().profiles).toBeNull();
    expect(state().status).toBe('failed');
    expect(state().error).toContain('500');
  });

  it('a malformed payload is a failure too', async () => {
    get.mockResolvedValue({ pullback_ema: {} });
    await state().fetch();
    expect([state().profiles, state().status]).toEqual([null, 'failed']);
  });

  it('only the latest request writes', async () => {
    let resolveFirst!: (v: unknown) => void;
    get.mockReturnValueOnce(new Promise((r) => { resolveFirst = r; }));
    const first = state().fetch();
    get.mockRejectedValueOnce(new Error('later failure'));
    await state().fetch();
    resolveFirst(profilesPayload());
    await first;
    expect(state().status).toBe('failed');
    expect(state().profiles).toBeNull();
  });
});

describe('profileView', () => {
  it('reads the panel values for direction x params horizon, with the tuned tag', () => {
    const profiles = parseStrategyProfiles(
      withTuned(profilesPayload(), 'pullback_ema', 'Bullish', 'Quarterly', { tolerance: 0.06, ema_period: 35 }),
    );
    const v = profileView(profiles, 'Bullish', 'Quarterly');
    expect(v.values.pullbackTolerancePct).toBe(0.06);
    expect(v.values.pullbackEmaPeriod).toBe(35);
    expect(v.values.maCrossoverFast).toBe(20);
    expect(v.values.vwapLookback).toBe(20);
    expect(v.values.meanReversionVariants).toEqual(['mean_reversion_rsi', 'mean_reversion_bb', 'mean_reversion_vwap_daily']);
    expect(v.sources.pullback_ema).toBe('tuned');
    expect(v.sources.ma_crossover).toBe('baseline');
  });

  it('a null params horizon (Intraday) reads the direction baseline', () => {
    const profiles = parseStrategyProfiles(
      withTuned(profilesPayload(), 'pullback_ema', 'Bullish', 'Swing', { tolerance: 0.06 }),
    );
    const v = profileView(profiles, 'Bullish', null);
    expect(v.values.pullbackTolerancePct).toBe(0.04);
    expect(v.sources.pullback_ema).toBe('baseline');
  });
});
