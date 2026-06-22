// Fetches per-horizon IV rank thresholds from the backend at app start.
// Falls back to YAML values if the fetch fails.
import { create } from 'zustand';
import { api } from '@/lib/api';

export interface HorizonIvThresholds {
  pass_max:    number | null;
  caution_max: number | null;
}

export interface IvThresholdsState {
  thresholds:    Record<string, HorizonIvThresholds>;
  loaded:        boolean;
  fetch:         () => Promise<void>;
  setThresholds: (t: Record<string, HorizonIvThresholds>) => void;
}

export const FALLBACK: Record<string, HorizonIvThresholds> = {
  Intraday: { pass_max: null, caution_max: null },
  Swing:    { pass_max: 34,   caution_max: 55   },
  Position: { pass_max: 44,   caution_max: 65   },
};

export const useIvThresholdsStore = create<IvThresholdsState>((set) => ({
  thresholds: FALLBACK,
  loaded:     false,
  fetch: async () => {
    try {
      const data = await api.getIvThresholds();
      set({ thresholds: data, loaded: true });
    } catch {
      set({ loaded: true }); // keep fallback values
    }
  },
  setThresholds: (t) => set({ thresholds: t }),
}));

export function getIvPassMax(
  horizonKey: string,
  thresholds: Record<string, HorizonIvThresholds>,
): number | null {
  return thresholds[horizonKey]?.pass_max ?? FALLBACK[horizonKey]?.pass_max ?? null;
}

export function getIvCautionMax(
  horizonKey: string,
  thresholds: Record<string, HorizonIvThresholds>,
): number | null {
  return thresholds[horizonKey]?.caution_max ?? FALLBACK[horizonKey]?.caution_max ?? null;
}
