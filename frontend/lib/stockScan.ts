import { api } from '@/lib/api';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';
import { useSettingsStore } from '@/lib/settingsStore';
import type { StockScanResult } from '@/types/stockDomain';

/** Optional per-run param overrides (the page passes its locally-edited params). */
export interface StockScanParamOverrides {
  pullbackTolerancePct?: number;
  pullbackEmaPeriod?: number;
  pullbackTrendEma?: number;
  pullbackMaType?: 'EMA' | 'SMA';
  maCrossoverFast?: number;
  maCrossoverSlow?: number;
  maCrossoverLookback?: number;
  breakoutVolumeMult?: number;
  rsiPeriod?: number;
  rsiOversold?: number;
  rsiTrendSma?: number;
  requireChoppyRegime?: boolean;
  btMinTrades?: number;
  btMinWinRate?: number;
  stockShortlistMax?: number;
}

/**
 * Run a stock scan with `strategy`, reading universe/direction/horizon from
 * scanStore.context and parameters from scanParamsStore (overridable per-run).
 * Writes result + scanState into scanStore. Returns the result or null on error.
 */
export async function runStockScan(
  strategy: string,
  overrides: StockScanParamOverrides = {},
): Promise<StockScanResult | null> {
  const store = useScanStore.getState();
  const saved = useScanParamsStore.getState();
  const p = { ...saved, ...overrides };

  const context = store.context;
  const requireReversal =
    (store.scanOverrides.pullback_require_reversal as boolean | undefined) ?? false;
  const { confidenceGate } = useSettingsStore.getState();

  // Keys from scanStore.scanOverrides that stock_scorer.py reads via the overrides dict.
  // Options-only params (max_delta, min_dte, etc.) and iv_rank_pass_max are excluded.
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
    // Reward/Risk params — forwarded in overrides dict; handled by the options pipeline only.
    'rr_bullish_target_pct', 'rr_bearish_target_pct',
    'rr_bullish_invalidation_pct', 'rr_bearish_invalidation_pct',
  ]);

  const rawOverrides = store.scanOverrides;
  const stocksOverrides = Object.fromEntries(
    Object.entries(rawOverrides).filter(([k]) => STOCKS_SCORER_KEYS.has(k))
  );

  store.setActiveStrategy(strategy);
  store.setStockScanResult(null);
  store.setScanState('SCANNING');

  try {
    const result = await api.postStockScan({
      universe:  context?.universe ? [context.universe] : ['SP500'],
      direction: context?.direction ?? 'Bullish',
      horizon:   (context?.horizon ?? 'Swing (5–15d)').split(' ')[0],
      strategy,
      pullback_tolerance_pct:    p.pullbackTolerancePct,
      pullback_ema_period:       p.pullbackEmaPeriod,
      pullback_trend_ema:        p.pullbackTrendEma,
      pullback_ma_type:          p.pullbackMaType,
      pullback_require_reversal: requireReversal,
      ma_crossover_fast:      p.maCrossoverFast,
      ma_crossover_slow:      p.maCrossoverSlow,
      ma_crossover_lookback:  p.maCrossoverLookback,
      breakout_volume_mult:   p.breakoutVolumeMult,
      rsi_period:             p.rsiPeriod,
      rsi_oversold:           p.rsiOversold,
      rsi_trend_sma:          p.rsiTrendSma,
      require_choppy_regime:  p.requireChoppyRegime ?? false,
      bt_min_trades:          p.btMinTrades,
      bt_min_win_rate:        p.btMinWinRate,
      account_size: 50_000,
      risk_pct: 0.01,
      shortlist_max_candidates: p.stockShortlistMax,
      overrides: stocksOverrides,
      confidence_caution_below: confidenceGate.enabled ? confidenceGate.cautionBelow : undefined,
      confidence_reject_below:  confidenceGate.enabled ? confidenceGate.rejectBelow  : undefined,
      confidence_atr_mult:      confidenceGate.enabled ? confidenceGate.atrMult       : undefined,
      regime_headwind_caution_pct: typeof rawOverrides.regime_headwind_caution_pct === 'number' ? rawOverrides.regime_headwind_caution_pct : undefined,
      regime_headwind_reject_pct:  typeof rawOverrides.regime_headwind_reject_pct  === 'number' ? rawOverrides.regime_headwind_reject_pct  : undefined,
      fundamentals_caution_above:  typeof rawOverrides.fundamentals_caution_above  === 'number' ? rawOverrides.fundamentals_caution_above  : undefined,
      fundamentals_reject_above:   typeof rawOverrides.fundamentals_reject_above   === 'number' ? rawOverrides.fundamentals_reject_above   : undefined,
    });
    store.setStockScanResult(result);
    store.setScanState('COMPLETED');
    return result;
  } catch {
    store.setScanState('FAILED');
    return null;
  }
}
