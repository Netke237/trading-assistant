import type { RegimeState, RegimeModel } from '@/types/alerts';

export const REGIME_STATES_OMM: RegimeState[] = ['any', 'Bull', 'Bear', 'Choppy'];
// Must match the state labels backend/app/services/regime_hmm.py::_assign_labels
// can actually produce — offering Bull/Bear/Sideways here would let a user save a
// condition that can never fire (the HMM model never emits those labels).
export const REGIME_STATES_HMM: RegimeState[] = ['any', 'Trending', 'Choppy', 'Mean-reverting'];
// The 3 real states backend/app/services/regime_hmm_daily.py::compute_directional_hmm
// can produce (Bull/Bear/Sideways, per its label_by_state mapping) — dropdown order
// here is cosmetic (Bull-first, matching REGIME_STATES_OMM's own Bull-before-Bear
// convention above) and intentionally does NOT mirror label_by_state's internal
// Bear/Sideways/Bull ordering, which is irrelevant to a user-facing picklist.
export const REGIME_STATES_HMM_DIRECTIONAL: RegimeState[] = ['any', 'Bull', 'Bear', 'Sideways'];
// When model === 'any', the backend checks the condition against every available
// model's snapshot (see backend/app/services/alert_evaluator.py::_evaluate_regime_condition),
// so the state list here must be the union of all three models' real states. Derived
// (not hand-maintained) so it can't silently drift if any model's own list changes.
export const REGIME_STATES_ANY: RegimeState[] = Array.from(
  new Set([...REGIME_STATES_OMM, ...REGIME_STATES_HMM, ...REGIME_STATES_HMM_DIRECTIONAL]),
);
export const REGIME_MODELS: RegimeModel[] = ['any', 'OMM', 'HMM', 'HMM_directional'];

export function regimeStatesFor(model: RegimeModel): RegimeState[] {
  if (model === 'OMM') return REGIME_STATES_OMM;
  if (model === 'HMM') return REGIME_STATES_HMM;
  if (model === 'HMM_directional') return REGIME_STATES_HMM_DIRECTIONAL;
  return REGIME_STATES_ANY;
}
