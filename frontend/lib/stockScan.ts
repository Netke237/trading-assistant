import { api } from '@/lib/api';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';
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
      bt_min_trades:          p.btMinTrades,
      bt_min_win_rate:        p.btMinWinRate,
      account_size: 50_000,
      risk_pct: 0.01,
      shortlist_max_candidates: p.stockShortlistMax,
    });
    store.setStockScanResult(result);
    store.setScanState('COMPLETED');
    return result;
  } catch {
    store.setScanState('FAILED');
    return null;
  }
}
