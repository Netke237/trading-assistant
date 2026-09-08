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
//
// AS OF B2 THIS STORE HAS NO PRODUCTION READER. The TradeCard badge was its
// only consumer and now renders the server's `stopCost`, which carries the
// verdict AND the `passMaxFraction` it was decided on — the gate is applied
// where the arithmetic is, so there is nothing left for the client to grade.
// Kept rather than deleted because the endpoint it fetches is live and this is
// the shape a Step-3 per-run override would need; note that such an override
// would now have to travel to the endpoint (`horizon_preset` is already sent),
// not be applied here. `setOverride` has had no caller since it was written —
// recorded by Phase B round 2, and left alone deliberately: it is below the
// audit gate floor, and over-fixing sub-floor items inside an audit target is
// the behaviour audit_rule v2 exists to stop. Logged against main instead.
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

/** Resolves the threshold the gate should use: a live per-run override wins over
 *  the horizon's fetched value, which wins over the bundled fallback. The final
 *  `FALLBACK.Swing` is for an unrecognised horizon key — Swing rather than the
 *  loosest value, so an unknown horizon fails toward caution.
 *
 *  B2 CLOSED THE FALLTHROUGH HAZARD ROUND 2 RECORDED HERE, by removing its
 *  cause rather than by adding a guard. While `LINEAR_BASIS_FALLBACK` existed,
 *  a caller passing it as `thresholds` for an unknown key fell PAST it onto
 *  `FALLBACK.Swing` — a line belonging to the other basis. There is now one
 *  basis and one set of lines, so every tier of this chain is the same ruler
 *  and the tail can only pick a different NUMBER, never a different question. */
export function getStopPremiumThresholds(
  horizonKey: string,
  thresholds: Record<string, HorizonStopPremiumThresholds>,
  override?: HorizonStopPremiumThresholds | null,
): HorizonStopPremiumThresholds {
  return override ?? thresholds[horizonKey] ?? FALLBACK[horizonKey] ?? FALLBACK.Swing;
}
