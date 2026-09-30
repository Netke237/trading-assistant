// Per-horizon event-proximity reject/caution day windows, fetched from the backend
// (/api/config/event-thresholds) — the horizons.<horizon>.event block of
// backend/config/scoring_rules.yaml, the same reject_days/caution_days
// score_stock()'s _rule_event grades the "event" rule with for options-mode scans.
// (Stock-mode scans zero this rule's weight — informational-only there.)
//
// THIS STORE HOLDS ONLY VALIDATED BACKEND VALUES (decision
// DOCC-3-THRESHOLD-STORES-REFUSE-2026-09-29). There is no hardcoded fallback: a
// failed or malformed fetch clears `thresholds` to null and sets status 'failed',
// and every reader must then show no verdict (Step 5 grades NO_DATA). A backend
// that now says the config is broken outranks a record fetched a minute ago.
//
// Pages fetch on mount (Step 5); there is no app-start bootstrap. `seq` makes
// only the latest request write, so a slow earlier response — success or
// failure — can never overwrite a newer one.
import { create } from 'zustand';
import { api } from '@/lib/api';

export type ThresholdHorizon = 'Intraday' | 'Swing' | 'Position';
export const THRESHOLD_HORIZONS: readonly ThresholdHorizon[] = ['Intraday', 'Swing', 'Position'];
export type ThresholdsStatus = 'idle' | 'loading' | 'ready' | 'failed';

export interface HorizonEventThresholds {
  reject_days:  number;
  caution_days: number;
}

export interface EventThresholdsState {
  /** ONLY ever a validated backend payload. null = none in hand. */
  thresholds: Record<ThresholdHorizon, HorizonEventThresholds> | null;
  status:     ThresholdsStatus;
  error:      string | null;
  fetch:      () => Promise<void>;
}

export function messageOf(e: unknown): string {
  if (e instanceof Error) return e.message;
  return String(e);
}

export function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

/** Throws Error naming the path, e.g. "Swing.caution_days: expected a number". */
export function parseEventThresholds(raw: unknown): Record<ThresholdHorizon, HorizonEventThresholds> {
  if (!isPlainObject(raw)) throw new Error('event thresholds: expected an object');
  const out = {} as Record<ThresholdHorizon, HorizonEventThresholds>;
  for (const h of THRESHOLD_HORIZONS) {
    const block = raw[h];
    if (!isPlainObject(block)) throw new Error(`${h}: missing or not an object`);
    const num = (k: 'reject_days' | 'caution_days'): number => {
      const v = block[k];
      if (typeof v !== 'number' || !Number.isFinite(v)) throw new Error(`${h}.${k}: expected a number`);
      if (v < 0) throw new Error(`${h}.${k}: must be >= 0`);
      return v;
    };
    const reject_days = num('reject_days');
    const caution_days = num('caution_days');
    if (reject_days > caution_days) {
      throw new Error(`${h}: reject_days (${reject_days}) exceeds caution_days (${caution_days})`);
    }
    out[h] = { reject_days, caution_days };
  }
  return out;
}

let seq = 0;

export const useEventThresholdsStore = create<EventThresholdsState>((set) => ({
  thresholds: null,
  status:     'idle',
  error:      null,
  fetch: async () => {
    const my = ++seq;
    set({ status: 'loading' });   // thresholds kept: the last good record stays on screen
    try {
      const data = await api.getEventThresholds();
      if (my !== seq) return;
      set({ thresholds: parseEventThresholds(data), status: 'ready', error: null });
    } catch (e) {
      if (my !== seq) return;
      set({ thresholds: null, status: 'failed', error: messageOf(e) });
    }
  },
}));

export function getEventWindow(
  horizonKey: ThresholdHorizon,
  thresholds: Record<ThresholdHorizon, HorizonEventThresholds>,
): HorizonEventThresholds {
  return thresholds[horizonKey];
}
