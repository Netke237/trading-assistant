/*
 * Pure stocks-mode scan-request resolution, extracted from stockScan.ts's
 * runStockScan() (Part 3 of the scheduler-timezone-awareness plan) so the
 * exact same request-building logic can be reused by the profile-based
 * scan-schedule resolver (scanScheduleResolve.ts).
 */
import type { ScanParams } from '@/lib/scanParamsStore';
import type { ConfidenceGate } from '@/lib/settingsStore';
import { atrMultForHorizon } from '@/lib/settingsStore';
import { regimeGateOverridesFrom } from '@/lib/regimeGateOverrides';
import { sanitizeHoldDays, type TunedHorizon } from '@/lib/horizonPresets';
import { assertStrategyScanOverrides } from '@/lib/strategyScanValidation';
import type { CapUnit } from '@/lib/universeStore';

// Keys from scanStore.scanOverrides that stock_scorer.py reads via the overrides dict.
// Options-only params (max_delta, min_dte, etc.) and the two IV ceilings
// (iv_abs_pass_max, iv_rank_pass_max) are excluded.
export const SCORE_WEIGHT_KEYS = new Set([
  'weight_trend',
  'weight_pullback',
  'weight_trigger',
  'weight_event',
  'weight_vol',
]);

export function normalizeWeightOverride(val: number | boolean | string): number | boolean | string {
  if (typeof val !== 'number' || !Number.isFinite(val)) return val;
  return Math.max(0, val / 100.0);
}

const STOCKS_SCORER_KEYS = new Set([
  'weight_trend', 'weight_pullback', 'weight_trigger', 'weight_event', 'weight_vol',
  'trend_method', 'ma_type', 'fast_ema', 'slow_ema',
  'additive_ma_type', 'additive_ma_period', 'additive_slope_lookback',
  'additive_adx_period', 'additive_adx_pass', 'additive_adx_caution',
  'additive_price_max', 'additive_slope_max', 'additive_adx_max',
  'rs_period', 'rs_pass_threshold', 'rs_caution_threshold', 'rs_benchmark',
  'swing_high_lookback_bars', 'atr_caution_max',
  'macd_fast', 'macd_slow', 'macd_signal', 'rsi_floor',
  'event_reject_days', 'event_caution_days',
  'rr_target_r_multiple',
  'rr_bullish_invalidation_pct', 'rr_bearish_invalidation_pct',
]);

export interface ResolvedStockScanContext {
  universe: string[];
  direction: string;
  /** Scoring horizon string, e.g. "Swing" (space-split, no "(Nd)" suffix). */
  horizon: string;
  strategy: string;
  /** Strategy fields are overrides: `null` = follow the backend profile and
   *  is not sent (STOCKS-HORIZON-T1 H5). */
  params: ScanParams;
  /** The tuned horizon whose backend profile this scan reads — set by every
   *  builder from tunedParamsHorizon(context preset, context holdMax); null
   *  (Intraday, or no context) sends none. */
  paramsHorizon: TunedHorizon | null;
  requireReversal: boolean;
  scanOverrides: Record<string, number | boolean | string>;
  confidenceGate: ConfidenceGate;
  /** $ account size — riskStore.limits.portfolioValue, live or captured. */
  accountSize: number;
  /** Fraction — riskStore.limits.maxLossPerTradePct, live or captured. */
  riskPct: number;
  /** The hold that produced the scan (ScanContext.holdMin/holdMax, or a
   *  schedule profile's), never the preset table, whose Custom row is a fixed
   *  15. Sent as `hold_max_days` through sanitizeHoldDays, exactly as the
   *  options scan sends it: the backend's earnings veto window is
   *  max(reject_days, hold_max_days) (STOCKS-HORIZON-P0B B6). Required keys;
   *  `undefined` only when there is no scan context at all, and then no hold
   *  is sent and the backend uses the scoring horizon's preset hold. */
  holdMinDays: number | undefined;
  holdMaxDays: number | undefined;
  minPriceRaw?: string;
  maxPriceRaw?: string;
  minCapRaw?: string;
  maxCapRaw?: string;
  capUnit?: CapUnit;
}

/** Matches backend `StockScanRequest` (backend/app/schemas/stock_scan.py) field-for-field. */
export interface StockScanRequestBody {
  universe: string[];
  direction: string;
  horizon: string;
  strategy: string;
  pullback_tolerance_pct?: number;
  pullback_ema_period?: number;
  pullback_trend_ema?: number;
  pullback_ma_type?: 'EMA' | 'SMA';
  pullback_require_reversal?: boolean;
  ma_crossover_fast?: number;
  ma_crossover_slow?: number;
  ma_crossover_lookback?: number;
  breakout_volume_mult?: number;
  rsi_period?: number;
  rsi_oversold?: number;
  rsi_overbought?: number;
  rsi_trend_sma?: number;
  require_choppy_regime?: boolean;
  bt_min_trades?: number;
  bt_min_win_rate?: number;
  // Both have backend defaults (account_size=50_000.0, risk_pct=0.01 — see
  // backend/app/schemas/stock_scan.py) so are optional on the wire; the
  // resolver functions in this repo always set them explicitly, but other
  // callers (e.g. step-4-prebreakout's ad-hoc pullback/fib scan requests)
  // legitimately omit them and rely on those defaults.
  account_size?: number;
  risk_pct?: number;
  min_price?: number;
  max_price?: number;
  min_cap_usd?: number;
  max_cap_usd?: number;
  shortlist_max_candidates?: number;
  overrides?: Record<string, number | boolean | string>;
  confidence_caution_below?: number;
  confidence_reject_below?: number;
  confidence_atr_mult_target?: number;
  confidence_atr_mult_stop?: number;
  regime_headwind_caution_pct?: number;
  regime_headwind_reject_pct?: number;
  fundamentals_caution_above?: number;
  fundamentals_reject_above?: number;
  mean_reversion_variants?: string[];
  mean_reversion_min_confirmations?: number;
  vwap_lookback?: number;
  vwap_deviation_pct?: number;
  /** Step-3 "Min stock score" (P3a); sent only when set. */
  min_stock_score?: number;
  /** The scan's hold (B6). Optional on the wire: step-4-prebreakout's ad-hoc
   *  requests omit it, and the backend then uses the horizon's preset hold. */
  hold_max_days?: number;
  /** STOCKS-HORIZON-T1 H5: which tuned horizon's backend profile the
   *  strategy fields default to. Absent for Intraday. */
  params_horizon?: TunedHorizon;
}

/** `{ [key]: value }` when the override is set, else nothing. */
function parseFilterNumber(raw?: string): number | undefined {
  if (raw === undefined || raw.trim() === '') return undefined;
  const num = Number(raw);
  return Number.isFinite(num) ? num : undefined;
}

function override<K extends string, V>(key: K, value: V | null | undefined): Partial<Record<K, V>> {
  return value === null || value === undefined ? {} : ({ [key]: value } as Record<K, V>);
}

export function buildStockScanRequestBody(ctx: ResolvedStockScanContext): StockScanRequestBody {
  const p = ctx.params;
  assertStrategyScanOverrides({
    pullbackTolerancePct: p.pullbackTolerancePct,
    maCrossoverLookback: p.maCrossoverLookback,
    breakoutVolumeMult: p.breakoutVolumeMult,
  });

  const rawOverrides = ctx.scanOverrides;
  const stocksOverrides: Record<string, number | boolean | string> = Object.fromEntries(
    Object.entries(rawOverrides)
      .filter(([k]) => STOCKS_SCORER_KEYS.has(k))
      .map(([k, v]) => [k, SCORE_WEIGHT_KEYS.has(k) ? normalizeWeightOverride(v) : v]),
  );

  const confidenceGate = ctx.confidenceGate;
  const hasFullAtrOverride =
    typeof rawOverrides.confidence_atr_mult_target === 'number' &&
    typeof rawOverrides.confidence_atr_mult_stop === 'number';
  const atrPair = hasFullAtrOverride
    ? { target: rawOverrides.confidence_atr_mult_target as number, stop: rawOverrides.confidence_atr_mult_stop as number }
    : atrMultForHorizon(confidenceGate, ctx.horizon);
  // No usable hold (no context, or a legacy persisted one) sends none, so the
  // backend falls back to the horizon's preset hold rather than null/NaN.
  const holdMax = ctx.holdMaxDays === undefined
    ? undefined
    : sanitizeHoldDays(ctx.holdMinDays ?? 0, ctx.holdMaxDays).hold_max_days;
  const minPrice = parseFilterNumber(ctx.minPriceRaw);
  const maxPrice = parseFilterNumber(ctx.maxPriceRaw);
  const capMultiplier = ctx.capUnit === 'M' ? 1e6 : 1e9;
  const minCap = parseFilterNumber(ctx.minCapRaw);
  const maxCap = parseFilterNumber(ctx.maxCapRaw);

  return {
    universe: ctx.universe,
    direction: ctx.direction,
    horizon: ctx.horizon,
    strategy: ctx.strategy,
    ...(minPrice !== undefined ? { min_price: minPrice } : {}),
    ...(maxPrice !== undefined ? { max_price: maxPrice } : {}),
    ...(minCap !== undefined ? { min_cap_usd: minCap * capMultiplier } : {}),
    ...(maxCap !== undefined ? { max_cap_usd: maxCap * capMultiplier } : {}),
    // Strategy fields: only the overrides the user set (STOCKS-HORIZON-T1
    // H5); every other field takes the backend profile for params_horizon.
    ...override('pullback_tolerance_pct', p.pullbackTolerancePct),
    ...override('pullback_ema_period', p.pullbackEmaPeriod),
    ...override('pullback_trend_ema', p.pullbackTrendEma),
    ...override('pullback_ma_type', p.pullbackMaType),
    pullback_require_reversal: ctx.requireReversal,
    ...override('ma_crossover_fast', p.maCrossoverFast),
    ...override('ma_crossover_slow', p.maCrossoverSlow),
    ...override('ma_crossover_lookback', p.maCrossoverLookback),
    ...override('breakout_volume_mult', p.breakoutVolumeMult),
    ...override('rsi_period', p.rsiPeriod),
    ...override('rsi_oversold', p.rsiOversold),
    ...override('rsi_overbought', p.rsiOverbought),
    ...override('rsi_trend_sma', p.rsiTrendSma),
    ...override('require_choppy_regime', p.requireChoppyRegime),
    ...(ctx.paramsHorizon ? { params_horizon: ctx.paramsHorizon } : {}),
    bt_min_trades: p.btMinTrades,
    bt_min_win_rate: p.btMinWinRate,
    account_size: ctx.accountSize,
    risk_pct: ctx.riskPct,
    shortlist_max_candidates: p.stockShortlistMax,
    overrides: stocksOverrides,
    confidence_caution_below: confidenceGate.enabled
      ? (typeof rawOverrides.confidence_caution_below === 'number' && Number.isFinite(rawOverrides.confidence_caution_below)
          ? rawOverrides.confidence_caution_below
          : confidenceGate.cautionBelow)
      : undefined,
    confidence_reject_below: confidenceGate.enabled
      ? (typeof rawOverrides.confidence_reject_below === 'number' && Number.isFinite(rawOverrides.confidence_reject_below)
          ? rawOverrides.confidence_reject_below
          : confidenceGate.rejectBelow)
      : undefined,
    confidence_atr_mult_target: atrPair.target,
    confidence_atr_mult_stop: atrPair.stop,
    // Was two inline ternaries identical to these; routed through the shared
    // reader 2026-09-19 so this, the options scan and the arm snapshot cannot
    // drift apart on what the Step-3 controls say.
    ...regimeGateOverridesFrom(rawOverrides),
    fundamentals_caution_above: typeof rawOverrides.fundamentals_caution_above === 'number' ? rawOverrides.fundamentals_caution_above : undefined,
    fundamentals_reject_above: typeof rawOverrides.fundamentals_reject_above === 'number' ? rawOverrides.fundamentals_reject_above : undefined,
    min_stock_score: typeof rawOverrides.min_stock_score === 'number' ? rawOverrides.min_stock_score : undefined,
    hold_max_days: holdMax !== undefined && Number.isFinite(holdMax) ? holdMax : undefined,
    ...(ctx.strategy === 'mean_reversion_multi' ? {
      ...override('mean_reversion_variants', p.meanReversionVariants),
      ...override('mean_reversion_min_confirmations', p.meanReversionMinConfirm),
      ...override('vwap_lookback', p.vwapLookback),
      ...override('vwap_deviation_pct', p.vwapDeviationPct),
    } : {}),
  };
}
