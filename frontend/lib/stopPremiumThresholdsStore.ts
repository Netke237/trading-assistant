// Fetches per-horizon stop-vs-premium gate thresholds from the backend at app
// start. Falls back to YAML-mirroring values if the fetch fails — same
// fetch-with-fallback shape as eventThresholdsStore / ivThresholdsStore.
//
// Single source of truth: these must match backend/config/scoring_rules.yaml's
// horizons.<horizon>.stop_premium block. Fetching them (rather than keeping a
// second hardcoded copy here) is what stops the gate on screen from drifting
// away from the YAML the operator actually edits.
//
// `override` is the per-run layer: Step 3's Execution Parameters can set a pair
// for the current scan without touching the YAML default. It is deliberately
// NOT persisted — a threshold you loosened for one scan should not silently
// still be loose next week. Clearing it falls straight back to the fetched
// per-horizon value.
import { create } from 'zustand';
import { api } from '@/lib/api';

export interface HorizonStopPremiumThresholds {
  /** Loss-at-stop as a fraction of premium. Below it the contract PASSes; at or
   *  above it, CAUTION. One threshold, two outcomes — the gate never REJECTs and
   *  never paints red, because it sorts candidates rather than refusing them. */
  pass_max_fraction: number;
}

export interface StopPremiumThresholdsState {
  thresholds:    Record<string, HorizonStopPremiumThresholds>;
  override:      HorizonStopPremiumThresholds | null;
  loaded:        boolean;
  fetch:         () => Promise<void>;
  setThresholds: (t: Record<string, HorizonStopPremiumThresholds>) => void;
  setOverride:   (o: HorizonStopPremiumThresholds | null) => void;
}

export const FALLBACK: Record<string, HorizonStopPremiumThresholds> = {
  Intraday: { pass_max_fraction: 0.85 },
  Swing:    { pass_max_fraction: 0.80 },
  Position: { pass_max_fraction: 0.70 },
};

export const useStopPremiumThresholdsStore = create<StopPremiumThresholdsState>((set) => ({
  thresholds: FALLBACK,
  override:   null,
  loaded:     false,
  fetch: async () => {
    try {
      const data = await api.getStopPremiumThresholds();
      set({ thresholds: data, loaded: true });
    } catch {
      set({ loaded: true }); // keep fallback values
    }
  },
  setThresholds: (t) => set({ thresholds: t }),
  setOverride:   (o) => set({ override: o }),
}));

/** Resolves the threshold the gate should actually use: a live per-run override wins
 *  over the horizon's fetched value, which wins over the bundled fallback. The
 *  final `FALLBACK.Swing` is for an unrecognised horizon key — Swing rather than
 *  the loosest value, so an unknown horizon fails toward caution. */
export function getStopPremiumThresholds(
  horizonKey: string,
  thresholds: Record<string, HorizonStopPremiumThresholds>,
  override?: HorizonStopPremiumThresholds | null,
): HorizonStopPremiumThresholds {
  return override ?? thresholds[horizonKey] ?? FALLBACK[horizonKey] ?? FALLBACK.Swing;
}
