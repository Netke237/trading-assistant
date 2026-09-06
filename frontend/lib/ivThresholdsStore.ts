// Fetches per-horizon IV thresholds from the backend at app start.
// Falls back to YAML values if the fetch fails.
//
// TWO SETS, because the figure being judged can be either of two quantities
// (PHASE-A-NULL-IVRANK-2026-09-06):
//   abs_*   judge ABSOLUTE implied volatility 0-100 — the set that applies on
//           any chain where neither IBKR nor tastytrade supplied a percentile,
//           i.e. the default configuration. These carry the 34/55 and 44/65
//           numbers this gate has in fact been applying all along.
//   rank_*  judge a TRUE PERCENTILE. UNMEASURED — seeded from the absolute set.
// There is deliberately no unqualified `pass_max`: a caller must say which
// quantity it is about to judge, which is exactly what the old name did not.
import { create } from 'zustand';
import { api } from '@/lib/api';
import type { IvBasis } from '@/lib/ivBasis';

export interface HorizonIvThresholds {
  abs_pass_max:     number | null;
  abs_caution_max:  number | null;
  rank_pass_max:    number | null;
  rank_caution_max: number | null;
}

export interface IvThresholdsState {
  thresholds:    Record<string, HorizonIvThresholds>;
  loaded:        boolean;
  fetch:         () => Promise<void>;
  setThresholds: (t: Record<string, HorizonIvThresholds>) => void;
}

export const FALLBACK: Record<string, HorizonIvThresholds> = {
  Intraday: { abs_pass_max: null, abs_caution_max: null, rank_pass_max: null, rank_caution_max: null },
  Swing:    { abs_pass_max: 34,   abs_caution_max: 55,   rank_pass_max: 34,   rank_caution_max: 55   },
  Position: { abs_pass_max: 44,   abs_caution_max: 65,   rank_pass_max: 44,   rank_caution_max: 65   },
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

/** The pass ceiling for the quantity actually in hand.
 *
 *  Basis 'none' returns null — there is no figure, so there is no threshold to
 *  apply, and callers must treat that as "unknown", never as a pass.
 */
export function getIvPassMax(
  horizonKey: string,
  thresholds: Record<string, HorizonIvThresholds>,
  basis: IvBasis,
): number | null {
  if (basis === 'none') return null;
  const k = basis === 'rank' ? 'rank_pass_max' : 'abs_pass_max';
  return thresholds[horizonKey]?.[k] ?? FALLBACK[horizonKey]?.[k] ?? null;
}

export function getIvCautionMax(
  horizonKey: string,
  thresholds: Record<string, HorizonIvThresholds>,
  basis: IvBasis,
): number | null {
  if (basis === 'none') return null;
  const k = basis === 'rank' ? 'rank_caution_max' : 'abs_caution_max';
  return thresholds[horizonKey]?.[k] ?? FALLBACK[horizonKey]?.[k] ?? null;
}
