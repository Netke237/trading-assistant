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

// Q7's re-derived lines, moved with the gate's basis (docs/superpowers/plans/
// 2026-09-02-gate-basis-spec.md §1). PASS means at least 20% / 30% / 40% of the
// premium is still there when the stop hits.
export const FALLBACK: Record<string, HorizonStopPremiumThresholds> = {
  Intraday: { pass_max_fraction: 0.80 },
  Swing:    { pass_max_fraction: 0.70 },
  Position: { pass_max_fraction: 0.60 },
};

/** ROUND 1 finding 1. The lines the DELTA-LINEAR estimator was calibrated with.
 *
 *  `FALLBACK` above carries Q7's re-derived numbers, which belong to the
 *  Black-Scholes basis in `backend/app/scoring/stop_cost.py`. That gate is
 *  correct and its thresholds are pinned by spec test 7. But the TradeCard
 *  badge still computes its loss with `risk.ts`'s linear estimator, which the
 *  spec measures as 17-29 points pessimistic on the same contract -- so grading
 *  a linear figure against a BS line flips real verdicts: on the spec's own
 *  reference chain a K=215 call at a $190 stop reads 78% linear (CAUTION at
 *  0.70) where the BS gate reads 59% (PASS). Two bases need two sets of lines.
 *
 *  B2 replaces the badge with the server's `stopCost`, at which point this map
 *  and `risk.ts`'s linear estimator are both deleted and everything reads
 *  `FALLBACK`. Until then the card uses this. */
export const LINEAR_BASIS_FALLBACK: Record<string, HorizonStopPremiumThresholds> = {
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
