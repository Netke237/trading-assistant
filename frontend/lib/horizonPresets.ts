/*
 * Single source of truth for the holding-horizon presets.
 *
 * The button expresses a HOLDING PERIOD. The contract DTE window is derived from
 * it as `hold * DTE_HOLDING_MULTIPLIER`. The backend performs the authoritative
 * derivation (and the expiry selection) and returns the enforced window in
 * ScanResult.dte_window — the preview below is for display only, before a scan
 * has run.
 */

export type HorizonKey =
  | 'Intraday' | 'Swing' | 'Position'
  | 'Quarterly' | 'SemiAnnual' | 'Annual'
  | 'Custom';

/** The three horizons the backend scorer understands. */
export type ScoringHorizon = 'Intraday' | 'Swing' | 'Position';

export interface HorizonPreset {
  key:            HorizonKey;
  label:          string;
  hint:           string;
  holdMin:        number;
  holdMax:        number;
  scoringHorizon: ScoringHorizon;
}

/** Kept in sync with backend/config/contract_rules.yaml: dte_holding_multiplier.
 *  Display-only — the backend is authoritative and echoes the enforced window
 *  back in ScanResult.dte_window. If the two ever drift, only the preview text
 *  shown before a scan runs is affected, not enforcement. */
export const DTE_HOLDING_MULTIPLIER = 2.0;
export const DTE_EXIT_BUFFER_DAYS = 21;
export const DTE_MIN_WINDOW_SPAN_DAYS = 35;

export const HORIZON_PRESETS: HorizonPreset[] = [
  { key: 'Intraday',   label: 'Intraday',    hint: '0–2 days',     holdMin: 0,   holdMax: 2,   scoringHorizon: 'Intraday' },
  { key: 'Swing',      label: 'Swing',       hint: '5–15 days',    holdMin: 5,   holdMax: 15,  scoringHorizon: 'Swing'    },
  { key: 'Position',   label: 'Position',    hint: '15–45 days',   holdMin: 15,  holdMax: 45,  scoringHorizon: 'Position' },
  { key: 'Quarterly',  label: 'Quarterly',   hint: '45–60 days',   holdMin: 45,  holdMax: 60,  scoringHorizon: 'Position' },
  { key: 'SemiAnnual', label: 'Semi-annual', hint: '90–105 days',  holdMin: 90,  holdMax: 105, scoringHorizon: 'Position' },
  { key: 'Annual',     label: 'Annual',      hint: '165–200 days', holdMin: 165, holdMax: 200, scoringHorizon: 'Position' },
  { key: 'Custom',     label: 'Custom',      hint: 'Set range',    holdMin: 5,   holdMax: 15,  scoringHorizon: 'Swing'    },
];

export function presetByKey(key: HorizonKey): HorizonPreset {
  const found = HORIZON_PRESETS.find((p) => p.key === key);
  return found ?? HORIZON_PRESETS[1];   // Swing
}

/** Custom has no fixed scoring horizon — derive it from the upper hold bound. */
export function scoringHorizonForHold(holdMax: number): ScoringHorizon {
  if (holdMax <= 4)  return 'Intraday';
  if (holdMax <= 20) return 'Swing';
  return 'Position';
}

/**
 * Which row of PARAM_DEFAULTS_PER_HORIZON (frontend/lib/executionParamDefaults.ts)
 * to read for a given horizon selection. Custom has no fixed row of its own — it
 * must resolve to whichever scoring horizon the current hold-days range actually
 * falls into, same boundaries as scoringHorizonForHold. Every other key passes
 * through unchanged, preserving its own distinct table row (e.g. Quarterly stays
 * Quarterly, even though it happens to share values with Position today).
 */
export function resolveParamsHorizon(hz: HorizonKey, holdMax: number): HorizonKey {
  return hz === 'Custom' ? scoringHorizonForHold(holdMax) : hz;
}

/** A holding period with its own backend strategy parameters (STOCKS-HORIZON-T1).
 *  Same names and order as backend app/services/horizon_profiles.py TUNED_HORIZONS. */
export type TunedHorizon = 'Swing' | 'Position' | 'Quarterly' | 'SemiAnnual' | 'Annual';
export const TUNED_HORIZONS: readonly TunedHorizon[] = ['Swing', 'Position', 'Quarterly', 'SemiAnnual', 'Annual'];

/**
 * Which tuned horizon's strategy parameters a stock scan reads (the request's
 * `params_horizon`). A tuned preset is itself; Intraday has none; Custom has
 * none when its hold scores as Intraday, else the tuned horizon whose preset
 * holdMax is nearest `holdMax` (a tie goes to the shorter horizon). Mirrors
 * backend horizon_profiles.tuned_params_horizon. Deliberately separate from
 * resolveParamsHorizon, which feeds the options parameter table.
 */
export function tunedParamsHorizon(hz: HorizonKey, holdMax: number): TunedHorizon | null {
  if ((TUNED_HORIZONS as readonly string[]).includes(hz)) return hz as TunedHorizon;
  if (hz !== 'Custom' || scoringHorizonForHold(holdMax) === 'Intraday') return null;
  let best: TunedHorizon = TUNED_HORIZONS[0];
  for (const h of TUNED_HORIZONS.slice(1)) {
    if (Math.abs(holdMax - presetByKey(h).holdMax) < Math.abs(holdMax - presetByKey(best).holdMax)) best = h;
  }
  return best;
}

/**
 * Display-only preview of the window the backend will enforce.
 * Mirrors backend/app/scoring/dte_window.py exactly.
 */
export function previewDteWindow(holdMin: number, holdMax: number): [number, number] {
  const lo = Math.max(1, Math.round(holdMin * DTE_HOLDING_MULTIPLIER), holdMax + DTE_EXIT_BUFFER_DAYS);
  const hi = Math.max(lo + DTE_MIN_WINDOW_SPAN_DAYS, Math.round(holdMax * DTE_HOLDING_MULTIPLIER));
  return [lo, hi];
}

/**
 * The derived display string kept on ScanContext.horizon for backward
 * compatibility with the ~19 read sites (including stock-mode) that expect a
 * string starting with one of 'Intraday' | 'Swing' | 'Position'.
 */
export function horizonDisplayString(scoringHorizon: ScoringHorizon, holdMin: number, holdMax: number): string {
  return `${scoringHorizon} (${holdMin}–${holdMax}d)`;
}

/** Upgrade a v9 stringly-typed horizon ("Custom (60–185d)") to structured state. */
export function migrateLegacyHorizon(horizon: string | undefined): {
  horizonPreset: HorizonKey; holdMin: number; holdMax: number;
} {
  if (horizon?.startsWith('Custom')) {
    const m = horizon.match(/(\d+)\s*[–-]\s*(\d+)/);
    if (m) return { horizonPreset: 'Custom', holdMin: Number(m[1]), holdMax: Number(m[2]) };
    return { horizonPreset: 'Custom', holdMin: 5, holdMax: 15 };
  }
  for (const p of HORIZON_PRESETS) {
    if (p.key !== 'Custom' && horizon?.startsWith(p.key)) {
      return { horizonPreset: p.key, holdMin: p.holdMin, holdMax: p.holdMax };
    }
  }
  const swing = presetByKey('Swing');
  return { horizonPreset: 'Swing', holdMin: swing.holdMin, holdMax: swing.holdMax };
}

/**
 * Round and order-clamp hold days right before they leave the browser (postScan /
 * getContracts). The Step 3 range inputs already round on every keystroke, but a
 * value read straight from a persisted store (e.g. a stale entry written before
 * that input-level rounding existed) could still carry a non-integer or inverted
 * pair — hold_min_days/hold_max_days are strict ints on both backend endpoints,
 * so an unrounded value here would 422 instead of just displaying wrong.
 */
export function sanitizeHoldDays(holdMin: number, holdMax: number): { hold_min_days: number; hold_max_days: number } {
  const lo = Math.max(0, Math.round(holdMin));
  const hi = Math.max(lo, Math.round(holdMax));
  return { hold_min_days: lo, hold_max_days: hi };
}

/** The scoring horizon behind a display label like "Position (45–60d)".
 *
 * The same ternary is written inline in five places today (step-4-ranking,
 * step-5-vol-events, the step-7 context rail, cardToRow, ScanLog). This is the
 * shared version — new callers use it; the existing five are deliberately left
 * alone rather than refactored as a side effect of an unrelated feature. */
export function scoringHorizonFromLabel(label: string | null | undefined): ScoringHorizon {
  if (label?.startsWith('Intraday')) return 'Intraday';
  if (label?.startsWith('Position')) return 'Position';
  return 'Swing';
}
