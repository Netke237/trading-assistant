// Per-horizon strategy parameter profiles (STOCKS-HORIZON-T1 H5), fetched from
// GET /api/config/strategy-profiles (backend routers/config.py, H4):
//   {strategy: {"Bullish"|"Bearish": {baseline: {...},
//     horizons: {<TunedHorizon>: {params: {...}, source: "tuned"|"baseline"}}}}}
// `params` is what a stock scan with that params horizon reads before request
// overrides. The Step-4 strategy panel shows these values; an edit there is an
// override (lib/scanParamsStore.ts).
//
// THIS STORE HOLDS ONLY A VALIDATED BACKEND PAYLOAD. No hardcoded fallback
// (decision T1-PROFILES-NO-FALLBACK-2026-10-09): a failed or malformed fetch
// clears `profiles` to null and sets status 'failed'; the panel then says the
// scan uses the backend's values and shows overrides only. No persist(): a
// stored profile would be a stale copy of a backend file the tuner rewrites.
// Modelled on eventThresholdsStore.ts, including the `seq` guard: only the
// latest request writes.
import { create } from 'zustand';
import { api } from '@/lib/api';
import { TUNED_HORIZONS, type TunedHorizon } from '@/lib/horizonPresets';
import type { OverrideField, ScanParams } from '@/lib/scanParamsStore';
import { isPlainObject, messageOf } from '@/lib/eventThresholdsStore';

export const TUNED_STRATEGIES = [
  'pullback_ema', 'breakout_base', 'ma_crossover',
  'mean_reversion_rsi', 'mean_reversion_bb', 'mean_reversion_multi',
] as const;
export type TunedStrategy = typeof TUNED_STRATEGIES[number];
export type ProfileDirection = 'Bullish' | 'Bearish';
const DIRECTIONS: readonly ProfileDirection[] = ['Bullish', 'Bearish'];
export type ProfileSource = 'tuned' | 'baseline';

export type ProfileParams = Record<string, unknown>;
export interface HorizonProfile { params: ProfileParams; source: ProfileSource }
export interface DirectionProfiles {
  baseline: ProfileParams;
  horizons: Record<TunedHorizon, HorizonProfile>;
}
export type StrategyProfiles = Record<TunedStrategy, Record<ProfileDirection, DirectionProfiles>>;
export type ProfilesStatus = 'idle' | 'loading' | 'ready' | 'failed';

export interface StrategyProfilesState {
  /** ONLY ever a validated backend payload. null = none in hand. */
  profiles: StrategyProfiles | null;
  status:   ProfilesStatus;
  error:    string | null;
  fetch:    () => Promise<void>;
}

/** Where each panel override field reads its profile value: strategy and key
 *  path inside that strategy's params. The RSI fields read the standalone RSI
 *  profile; their overrides also apply to multi's RSI variant (backend
 *  _SIGNAL_KWARGS). */
const FIELD_SOURCES: Record<OverrideField, { strategy: TunedStrategy; path: string[] }> = {
  pullbackTolerancePct:    { strategy: 'pullback_ema',         path: ['tolerance'] },
  pullbackEmaPeriod:       { strategy: 'pullback_ema',         path: ['ema_period'] },
  pullbackTrendEma:        { strategy: 'pullback_ema',         path: ['trend_ema'] },
  pullbackMaType:          { strategy: 'pullback_ema',         path: ['ma_type'] },
  maCrossoverFast:         { strategy: 'ma_crossover',         path: ['fast'] },
  maCrossoverSlow:         { strategy: 'ma_crossover',         path: ['slow'] },
  maCrossoverLookback:     { strategy: 'ma_crossover',         path: ['lookback'] },
  breakoutVolumeMult:      { strategy: 'breakout_base',        path: ['volume_mult'] },
  rsiPeriod:               { strategy: 'mean_reversion_rsi',   path: ['rsi_period'] },
  rsiOversold:             { strategy: 'mean_reversion_rsi',   path: ['rsi_oversold'] },
  rsiOverbought:           { strategy: 'mean_reversion_rsi',   path: ['rsi_overbought'] },
  rsiTrendSma:             { strategy: 'mean_reversion_rsi',   path: ['trend_sma'] },
  requireChoppyRegime:     { strategy: 'mean_reversion_rsi',   path: ['require_choppy_regime'] },
  meanReversionVariants:   { strategy: 'mean_reversion_multi', path: ['variants'] },
  meanReversionMinConfirm: { strategy: 'mean_reversion_multi', path: ['min_confirmations'] },
  vwapLookback:            { strategy: 'mean_reversion_multi', path: ['variant_params', 'mean_reversion_vwap_daily', 'vwap_lookback'] },
  vwapDeviationPct:        { strategy: 'mean_reversion_multi', path: ['variant_params', 'mean_reversion_vwap_daily', 'vwap_deviation_pct'] },
};

// Keys the frontend reads, checked strictly wherever they appear.
const NUMBER_KEYS = new Set([
  'tolerance', 'ema_period', 'trend_ema', 'fast', 'slow', 'lookback', 'volume_mult',
  'rsi_period', 'rsi_oversold', 'rsi_overbought', 'trend_sma', 'min_confirmations',
  'vwap_lookback', 'vwap_deviation_pct',
]);
const BOOLEAN_KEYS = new Set(['require_choppy_regime']);

function checkParams(path: string, raw: unknown, nested: boolean): ProfileParams {
  if (!isPlainObject(raw)) throw new Error(`${path}: expected an object`);
  for (const [k, v] of Object.entries(raw)) {
    const at = `${path}.${k}`;
    if (NUMBER_KEYS.has(k)) {
      if (typeof v !== 'number' || !Number.isFinite(v)) throw new Error(`${at}: expected a number`);
    } else if (BOOLEAN_KEYS.has(k)) {
      if (typeof v !== 'boolean') throw new Error(`${at}: expected a boolean`);
    } else if (k === 'ma_type') {
      if (v !== 'EMA' && v !== 'SMA') throw new Error(`${at}: expected "EMA" or "SMA"`);
    } else if (k === 'variants') {
      if (!Array.isArray(v) || !v.every((x) => typeof x === 'string')) throw new Error(`${at}: expected a list of strings`);
    } else if (k === 'variant_params' && nested) {
      if (!isPlainObject(v)) throw new Error(`${at}: expected an object`);
      for (const [variant, vp] of Object.entries(v)) checkParams(`${at}.${variant}`, vp, false);
    }
  }
  return raw;
}

/** Throws Error naming the path, e.g.
 *  "ma_crossover.Bullish.horizons.Position.params.fast: expected a number". */
export function parseStrategyProfiles(raw: unknown): StrategyProfiles {
  if (!isPlainObject(raw)) throw new Error('strategy profiles: expected an object');
  const out = {} as StrategyProfiles;
  for (const s of TUNED_STRATEGIES) {
    const block = raw[s];
    if (!isPlainObject(block)) throw new Error(`${s}: missing or not an object`);
    out[s] = {} as Record<ProfileDirection, DirectionProfiles>;
    for (const d of DIRECTIONS) {
      const dir = block[d];
      if (!isPlainObject(dir)) throw new Error(`${s}.${d}: missing or not an object`);
      const baseline = checkParams(`${s}.${d}.baseline`, dir.baseline, true);
      const hs = dir.horizons;
      if (!isPlainObject(hs)) throw new Error(`${s}.${d}.horizons: missing or not an object`);
      const horizons = {} as Record<TunedHorizon, HorizonProfile>;
      for (const h of TUNED_HORIZONS) {
        const hp = hs[h];
        const at = `${s}.${d}.horizons.${h}`;
        if (!isPlainObject(hp)) throw new Error(`${at}: missing or not an object`);
        if (hp.source !== 'tuned' && hp.source !== 'baseline') {
          throw new Error(`${at}.source: expected "tuned" or "baseline"`);
        }
        horizons[h] = { params: checkParams(`${at}.params`, hp.params, true), source: hp.source };
      }
      out[s][d] = { baseline, horizons };
    }
  }
  return out;
}

function at(params: ProfileParams, path: string[]): unknown {
  let cur: unknown = params;
  for (const k of path) {
    if (!isPlainObject(cur)) return undefined;
    cur = cur[k];
  }
  return cur;
}

export interface ProfileView {
  /** The profile value of each panel field; absent when the profile does not
   *  carry it (the signal function's own default then applies). */
  values: Partial<{ [K in OverrideField]: NonNullable<ScanParams[K]> }>;
  sources: Record<TunedStrategy, ProfileSource>;
}

/** The profile the scan reads for `direction` x `horizon` (null = the
 *  direction baseline, as for Intraday), as panel values. */
export function profileView(
  profiles: StrategyProfiles, direction: ProfileDirection, horizon: TunedHorizon | null,
): ProfileView {
  const paramsOf = (s: TunedStrategy): HorizonProfile =>
    horizon ? profiles[s][direction].horizons[horizon] : { params: profiles[s][direction].baseline, source: 'baseline' };
  const values: Record<string, unknown> = {};
  for (const [field, src] of Object.entries(FIELD_SOURCES)) {
    const v = at(paramsOf(src.strategy).params, src.path);
    if (v !== undefined && v !== null) values[field] = v;
  }
  const sources = Object.fromEntries(
    TUNED_STRATEGIES.map((s) => [s, paramsOf(s).source]),
  ) as Record<TunedStrategy, ProfileSource>;
  return { values: values as ProfileView['values'], sources };
}

let seq = 0;

export const useStrategyProfilesStore = create<StrategyProfilesState>((set) => ({
  profiles: null,
  status:   'idle',
  error:    null,
  fetch: async () => {
    const my = ++seq;
    set({ status: 'loading' });   // profiles kept: the last good record stays on screen
    try {
      const data = await api.getStrategyProfiles();
      if (my !== seq) return;
      set({ profiles: parseStrategyProfiles(data), status: 'ready', error: null });
    } catch (e) {
      if (my !== seq) return;
      set({ profiles: null, status: 'failed', error: messageOf(e) });
    }
  },
}));
