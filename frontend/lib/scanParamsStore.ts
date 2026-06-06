import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export interface ScanParams {
  pullbackTolerancePct: number;   // fraction: 0.04 = 4%
  pullbackEmaPeriod:    number;   // EMA to pull back to (e.g. 50)
  pullbackTrendEma:     number;   // trend-confirmation EMA (e.g. 100)
  maCrossoverLookback:  number;   // bars
  breakoutVolumeMult:   number;   // multiplier
  btMinTrades:          number;   // count
  btMinWinRate:         number;   // fraction: 0.45 = 45%
}

const DEFAULTS: ScanParams = {
  pullbackTolerancePct: 0.04,
  pullbackEmaPeriod:    50,
  pullbackTrendEma:     100,
  maCrossoverLookback:  10,
  breakoutVolumeMult:   1.1,
  btMinTrades:          10,
  btMinWinRate:         0.45,
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
      version: 2,
      migrate: (state: unknown, v: number) => {
        if (v < 2) return { ...DEFAULTS, ...(state as Partial<ScanParams>) };
        return state as ScanParams;
      },
    },
  ),
);

export { DEFAULTS as SCAN_PARAM_DEFAULTS };
