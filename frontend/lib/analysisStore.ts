import { create } from 'zustand';
import { api, type StockAnalysis } from '@/lib/api';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';

export type HorizonEnum = 'Intraday' | 'Swing' | 'Position';

/** ScanContext.horizon is a display label like "Swing (5–15d)" — map to the backend enum. */
export function _horizonEnum(label: string | undefined): HorizonEnum {
  const l = (label ?? '').toLowerCase();
  if (l.startsWith('intraday')) return 'Intraday';
  if (l.startsWith('position')) return 'Position';
  return 'Swing';
}

interface AnalysisState {
  symbol: string;
  result: StockAnalysis | null;
  loading: boolean;
  error: string | null;
  analyze: (symbol: string) => Promise<void>;
}

export const useAnalysisStore = create<AnalysisState>((set) => ({
  symbol: '',
  result: null,
  loading: false,
  error: null,
  analyze: async (raw: string) => {
    const symbol = raw.trim().toUpperCase();
    if (!symbol) return;
    set({ loading: true, error: null, symbol });
    try {
      const ctx = useScanStore.getState().context;
      const p = useScanParamsStore.getState();
      const result = await api.analyzeStock({
        symbol,
        direction: ctx?.direction ?? 'Bullish',
        horizon: _horizonEnum(ctx?.horizon),
        strategy: useScanStore.getState().activeStrategy ?? 'pullback_ema',
        pullback_tolerance_pct: p.pullbackTolerancePct,
        pullback_ema_period: p.pullbackEmaPeriod,
        pullback_trend_ema: p.pullbackTrendEma,
        pullback_ma_type: p.pullbackMaType,
        ma_crossover_fast: p.maCrossoverFast,
        ma_crossover_slow: p.maCrossoverSlow,
        ma_crossover_lookback: p.maCrossoverLookback,
        breakout_volume_mult: p.breakoutVolumeMult,
        rsi_period: p.rsiPeriod,
        rsi_oversold: p.rsiOversold,
        rsi_trend_sma: p.rsiTrendSma,
      });
      set({ result, loading: false });
    } catch (e) {
      set({ result: null, loading: false, error: e instanceof Error ? e.message : 'Analysis failed' });
    }
  },
}));
