// Fetches per-horizon event-proximity reject/caution day windows from the backend
// at app start. Falls back to YAML-mirroring values if the fetch fails.
//
// Single source of truth: these values must match backend/config/scoring_rules.yaml's
// horizons.<horizon>.event block — the same reject_days/caution_days score_stock()'s
// _rule_event uses to grade the "event" rule for options-mode scans. Fetching them
// (instead of hardcoding a second copy here) is what keeps the Step 5 gate (options-only)
// in sync with the gate that already shaped the candidate's score. (Stock-mode scans zero
// this rule's weight — these numbers are informational-only there, not a live gate.)
import { create } from 'zustand';
import { api } from '@/lib/api';

export interface HorizonEventThresholds {
  reject_days:  number;
  caution_days: number;
}

export interface EventThresholdsState {
  thresholds:    Record<string, HorizonEventThresholds>;
  loaded:        boolean;
  fetch:         () => Promise<void>;
  setThresholds: (t: Record<string, HorizonEventThresholds>) => void;
}

export const FALLBACK: Record<string, HorizonEventThresholds> = {
  Intraday: { reject_days: 1,  caution_days: 3  },
  Swing:    { reject_days: 21, caution_days: 45 },
  Position: { reject_days: 30, caution_days: 60 },
};

export const useEventThresholdsStore = create<EventThresholdsState>((set) => ({
  thresholds: FALLBACK,
  loaded:     false,
  fetch: async () => {
    try {
      const data = await api.getEventThresholds();
      set({ thresholds: data, loaded: true });
    } catch {
      set({ loaded: true }); // keep fallback values
    }
  },
  setThresholds: (t) => set({ thresholds: t }),
}));

export function getEventWindow(
  horizonKey: string,
  thresholds: Record<string, HorizonEventThresholds>,
): HorizonEventThresholds {
  return thresholds[horizonKey] ?? FALLBACK[horizonKey] ?? FALLBACK.Swing;
}
