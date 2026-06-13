import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export interface ScanParams {
  pullbackTolerancePct: number;   // fraction: 0.08 = 8%
  pullbackEmaPeriod:    number;   // EMA to pull back to (e.g. 50)
  pullbackTrendEma:     number;   // trend-confirmation EMA (e.g. 100)
  pullbackMaType:       'EMA' | 'SMA';
  maCrossoverFast:      number;   // fast MA period
  maCrossoverSlow:      number;   // slow MA period
  maCrossoverLookback:  number;   // bars
  breakoutVolumeMult:   number;   // multiplier
  rsiPeriod:            number;   // RSI look-back period
  rsiOversold:          number;   // RSI oversold threshold (e.g. 30)
  rsiTrendSma:          number;   // trend-confirmation SMA (e.g. 200)
  btMinTrades:          number;   // count
  btMinWinRate:         number;   // fraction: 0.45 = 45%
  eventFilter: 'include' | 'avoid' | 'only_pre_event';
  stockShortlistMax:    number;   // max stock candidates returned
}

const DEFAULTS: ScanParams = {
  pullbackTolerancePct: 0.08,
  pullbackEmaPeriod:    50,
  pullbackTrendEma:     100,
  pullbackMaType:       'EMA' as const,
  maCrossoverFast:      20,
  maCrossoverSlow:      50,
  maCrossoverLookback:  10,
  breakoutVolumeMult:   1.1,
  rsiPeriod:            14,
  rsiOversold:          30,
  rsiTrendSma:          200,
  btMinTrades:          5,
  btMinWinRate:         0.45,
  eventFilter:          'include' as const,
  stockShortlistMax:    10,
};

interface ScanParamsStore extends ScanParams {
  setParam: <K extends keyof ScanParams>(key: K, value: ScanParams[K]) => void;
  resetToDefaults: () => void;
}

export const useScanParamsStore = create<ScanParamsStore>()(
  persist(
    (set) => ({
      ...DEFAULTS,
      setParam: (key, value) => set({ [key]: value }),
      resetToDefaults: () => set({ ...DEFAULTS }),
    }),
    {
      name: 'bamendjou:scan-params',
      version: 7,
      migrate: (state: unknown, v: number) => {
        if (v < 2) return { ...DEFAULTS, ...(state as Partial<ScanParams>) };
        if (v < 4) return { ...DEFAULTS, ...(state as Partial<ScanParams>), pullbackMaType: 'EMA' as const };
        if (v < 5) return { ...DEFAULTS, ...(state as Partial<ScanParams>), eventFilter: 'include' as const };
        if (v < 6) return { ...DEFAULTS, ...(state as Partial<ScanParams>), pullbackTolerancePct: 0.08, btMinTrades: 5 };
        if (v < 7) return { ...DEFAULTS, ...(state as Partial<ScanParams>), stockShortlistMax: 10 };
        return state as ScanParams;
      },
    },
  ),
);

export { DEFAULTS as SCAN_PARAM_DEFAULTS };
