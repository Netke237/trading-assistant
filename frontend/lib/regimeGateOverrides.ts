/*
 * ONE reading of the Step-3 "Regime Gate" controls, shared by every path that
 * needs it — the options scan request, the stocks scan request, and the
 * auto-trade arm payload.
 *
 * It exists because of a measured defect, not for tidiness. Piece 2's round-1
 * audit (2026-09-19) found the fire path deciding a headwind refusal from
 * different inputs than the scan that produced the card had used, and the fix
 * (AUTOTRADE-GATE-INPUTS-FRESH-PER-SYMBOL-2026-09-19) snapshots these two
 * thresholds onto the armed trade so scan and fire judge it by the same rule.
 * A snapshot is only worth anything if it is read the SAME WAY the scan read
 * it, so the reading lives in one function rather than three.
 *
 * `undefined` means "not set" and the backend falls through to
 * scoring_rules.yaml — which is what an untouched Step-3 control means. Note
 * that executionParamDefaults seeds these at the YAML values (-15 / -40), so
 * in practice the numbers are usually present and equal to the defaults; the
 * undefined branch is for a store written before the keys existed.
 */

export interface RegimeGateOverrides {
  regime_headwind_caution_pct?: number;
  regime_headwind_reject_pct?: number;
}

/** Keys this module owns. Exported so request builders can strip them out of
 *  the score-`overrides` dict they send alongside — these are TOP-LEVEL request
 *  fields, and the stock scorer has no use for them. */
export const REGIME_GATE_OVERRIDE_KEYS = [
  'regime_headwind_caution_pct',
  'regime_headwind_reject_pct',
] as const;

export function regimeGateOverridesFrom(
  scanOverrides: Record<string, number | boolean | string> | null | undefined,
): RegimeGateOverrides {
  const o = scanOverrides ?? {};
  return {
    regime_headwind_caution_pct:
      typeof o.regime_headwind_caution_pct === 'number' ? o.regime_headwind_caution_pct : undefined,
    regime_headwind_reject_pct:
      typeof o.regime_headwind_reject_pct === 'number' ? o.regime_headwind_reject_pct : undefined,
  };
}
