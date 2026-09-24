/*
 * ONE reading of the Step-3 "Regime Gate" controls, shared by both scan
 * request builders (options and stocks). The auto-trade arm payload does NOT
 * read Step 3: it reads the thresholds the card's own scan RESOLVED, off
 * `card.regimeGate`, through `regimeGateFromCard` at the bottom of this file.
 *
 * It exists because of a measured defect, not for tidiness. Piece 2's round-1
 * audit (2026-09-19) found the fire path deciding a headwind refusal from
 * different inputs than the scan that produced the card had used, and the fix
 * (AUTOTRADE-GATE-INPUTS-FRESH-PER-SYMBOL-2026-09-19) snapshots these two
 * thresholds onto the armed trade so scan and fire judge it by the same rule.
 * That snapshot first read the live Step-3 store at arm time; arm-door round 1
 * (F1) showed that store need not hold what the card's scan used, so the scan
 * now echoes its resolved rule onto every card and the arm reads that.
 *
 * `undefined` means "not set" and the backend falls through to
 * scoring_rules.yaml — which is what an untouched Step-3 control means. (Step
 * 3 also deletes a key whose typed value equals its default, so an untouched
 * or reset control is absent here, not present at the YAML value.)
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

/** The thresholds a CARD'S OWN SCAN resolved, in the arm payload's shape.
 *
 *  The arm path's reader. `regimeGateOverridesFrom` above reads the LIVE
 *  Step-3 store, which is right for building a scan request and wrong for
 *  arming a card that already exists: that store is not persisted, survives a
 *  threshold edit and "Reset to defaults" without invalidating the scan, and
 *  so need not hold what the card's scan ran with (arm-door round 1, F1).
 *
 *  Returns null when the card carries no snapshot at all -- the caller must
 *  REFUSE to arm, not fall back to the live store, or F1 comes straight back.
 *  A null value inside the snapshot stays undefined (omitted): the resolved
 *  block had no such key, the scan read scoring_rules.yaml, and omitting is
 *  how the arm request says "read scoring_rules.yaml". */
export function regimeGateFromCard(
  card: { regimeGate?: { headwindCautionPct?: number | null; headwindRejectPct?: number | null } | null },
): RegimeGateOverrides | null {
  const g = card.regimeGate;
  if (g == null) return null;
  return {
    regime_headwind_caution_pct:
      typeof g.headwindCautionPct === 'number' ? g.headwindCautionPct : undefined,
    regime_headwind_reject_pct:
      typeof g.headwindRejectPct === 'number' ? g.headwindRejectPct : undefined,
  };
}

/** Tooltip for an Arm button greyed because the card carries no snapshot. */
export const MISSING_REGIME_GATE_SNAPSHOT_TITLE =
  'This card was scanned before scan results recorded their regime-gate rule. Re-run the scan to arm it.';
