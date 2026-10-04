// Per-horizon IV thresholds, fetched from the backend (/api/config/iv-thresholds).
//
// THIS STORE HOLDS ONLY VALIDATED BACKEND VALUES (decision
// DOCC-3-THRESHOLD-STORES-REFUSE-2026-09-29). There is no hardcoded fallback: a
// failed or malformed fetch clears `thresholds` to null and sets status
// 'failed'; readers then show no IV verdict. Status, `seq` race guard and
// failure semantics mirror eventThresholdsStore.ts. Pages fetch on mount (Step 5,
// the Step 7 rail, Settings); there is no app-start bootstrap.
//
// `null` on a key has exactly ONE meaning: the validated payload says there is no
// gate on that basis for that horizon. A key that is ABSENT is refused by
// parseIvThresholds, never read as null.
//
// TWO SETS, because the figure being judged can be either of two quantities
// (PHASE-A-NULL-IVRANK-2026-09-06):
//   abs_*   judge ABSOLUTE implied volatility 0-100 — the set that applies on
//           any chain where neither IBKR nor tastytrade supplied a percentile,
//           i.e. the default configuration.
//   rank_*  judge an IV RANK. UNMEASURED — seeded from the absolute set.
// There is deliberately no unqualified `pass_max`: a caller must say which
// quantity it is about to judge, which is exactly what the old name did not.
//
// SETTINGS OVERRIDE LAYER. Settings' IV edit is a session-only override of
// abs_pass_max on Swing/Position, held in `overrides` — separate from the
// fetched record, so fetch() never touches it and it survives a re-fetch.
// Readers apply it via effectiveIvThresholds(). ZUSTAND v5: select
// `thresholds` and `overrides` with two separate selectors and call
// effectiveIvThresholds inside useMemo — a selector that returns a fresh object
// re-renders forever.
import { create } from 'zustand';
import { api } from '@/lib/api';
import type { IvBasis } from '@/lib/ivBasis';
import {
  THRESHOLD_HORIZONS, isPlainObject, messageOf,
  type ThresholdHorizon, type ThresholdsStatus,
} from '@/lib/eventThresholdsStore';

export interface HorizonIvThresholds {
  abs_pass_max:     number | null;
  abs_caution_max:  number | null;
  rank_pass_max:    number | null;
  rank_caution_max: number | null;
}

export type IvOverrideHorizon = 'Swing' | 'Position';
export type IvOverrides = Partial<Record<IvOverrideHorizon, { abs_pass_max: number }>>;

export interface IvThresholdsState {
  /** ONLY ever a validated backend payload. null = none in hand. */
  thresholds: Record<ThresholdHorizon, HorizonIvThresholds> | null;
  status:     ThresholdsStatus;
  error:      string | null;
  overrides:  IvOverrides;
  fetch:              () => Promise<void>;
  setAbsPassOverride: (h: IvOverrideHorizon, v: number) => void;
  clearOverrides:     () => void;
}

const IV_KEYS = ['abs_pass_max', 'abs_caution_max', 'rank_pass_max', 'rank_caution_max'] as const;

/** Throws Error naming the path, e.g. "Swing.abs_pass_max: missing". */
export function parseIvThresholds(raw: unknown): Record<ThresholdHorizon, HorizonIvThresholds> {
  if (!isPlainObject(raw)) throw new Error('IV thresholds: expected an object');
  const out = {} as Record<ThresholdHorizon, HorizonIvThresholds>;
  for (const h of THRESHOLD_HORIZONS) {
    const block = raw[h];
    if (!isPlainObject(block)) throw new Error(`${h}: missing or not an object`);
    const rec = {} as HorizonIvThresholds;
    for (const k of IV_KEYS) {
      if (!(k in block)) throw new Error(`${h}.${k}: missing`);
      const v = block[k];
      if (v === null) { rec[k] = null; continue; }
      if (typeof v !== 'number' || !Number.isFinite(v)) throw new Error(`${h}.${k}: expected a number or null`);
      if (v < 0 || v > 100) throw new Error(`${h}.${k}: ${v} is outside [0, 100]`);
      rec[k] = v;
    }
    for (const basis of ['abs', 'rank'] as const) {
      const p = rec[`${basis}_pass_max`];
      const c = rec[`${basis}_caution_max`];
      if (p === null && c !== null) {
        throw new Error(`${h}.${basis}_pass_max: null (no gate) but ${basis}_caution_max is ${c}`);
      }
      if (p !== null && c !== null && p > c) {
        throw new Error(`${h}.${basis}_pass_max (${p}) exceeds ${basis}_caution_max (${c})`);
      }
    }
    out[h] = rec;
  }
  return out;
}

let seq = 0;

export const useIvThresholdsStore = create<IvThresholdsState>((set) => ({
  thresholds: null,
  status:     'idle',
  error:      null,
  overrides:  {},
  fetch: async () => {
    const my = ++seq;
    set({ status: 'loading' });   // thresholds kept; overrides never touched
    try {
      const data = await api.getIvThresholds();
      if (my !== seq) return;
      set({ thresholds: parseIvThresholds(data), status: 'ready', error: null });
    } catch (e) {
      if (my !== seq) return;
      set({ thresholds: null, status: 'failed', error: messageOf(e) });
    }
  },
  setAbsPassOverride: (h, v) =>
    set((s) => ({ overrides: { ...s.overrides, [h]: { abs_pass_max: v } } })),
  clearOverrides: () => set({ overrides: {} }),
}));

/** Pure. null when `thresholds` is null. The override is NOT applied to a
 *  horizon whose fetched abs_pass_max is null (no gate there: an override must
 *  not invent one). An override above abs_caution_max raises the pass ceiling
 *  only; the caution ceiling is unchanged, so that band is empty. */
export function effectiveIvThresholds(
  t: Record<ThresholdHorizon, HorizonIvThresholds> | null,
  overrides: IvOverrides,
): Record<ThresholdHorizon, HorizonIvThresholds> | null {
  if (t === null) return null;
  const out = { ...t };
  for (const h of ['Swing', 'Position'] as const) {
    const o = overrides[h];
    if (o !== undefined && t[h].abs_pass_max !== null) {
      out[h] = { ...t[h], abs_pass_max: o.abs_pass_max };
    }
  }
  return out;
}

/** The active override for `h` and the YAML value it replaces, or null when no
 *  override is applied there (none set, no record, or no gate in the YAML). */
export function ivOverrideFor(
  h: ThresholdHorizon,
  t: Record<ThresholdHorizon, HorizonIvThresholds> | null,
  overrides: IvOverrides,
): { value: number; yaml: number } | null {
  if (t === null || h === 'Intraday') return null;
  const o = overrides[h];
  const yaml = t[h].abs_pass_max;
  if (o === undefined || yaml === null) return null;
  return { value: o.abs_pass_max, yaml };
}

/** The pass ceiling for the quantity actually in hand.
 *
 *  Basis 'none' returns null — there is no figure, so there is no threshold to
 *  apply, and callers must treat that as "unknown", never as a pass.
 */
export function getIvPassMax(
  horizonKey: ThresholdHorizon,
  thresholds: Record<ThresholdHorizon, HorizonIvThresholds>,
  basis: IvBasis,
): number | null {
  if (basis === 'none') return null;
  const k = basis === 'rank' ? 'rank_pass_max' : 'abs_pass_max';
  return thresholds[horizonKey][k];
}

export function getIvCautionMax(
  horizonKey: ThresholdHorizon,
  thresholds: Record<ThresholdHorizon, HorizonIvThresholds>,
  basis: IvBasis,
): number | null {
  if (basis === 'none') return null;
  const k = basis === 'rank' ? 'rank_caution_max' : 'abs_caution_max';
  return thresholds[horizonKey][k];
}
