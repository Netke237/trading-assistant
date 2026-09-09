/** Shared prose for an exit plan's stop and target rows.
 *
 *  These are CLIENT-COMPOSED sentences built from the raw numbers the backend
 *  returns (`source`, `structuralPrice`, `atrFloorPrice`, `distanceDollar`,
 *  `tpSource`, `qualityReasons`) — not backend text fields.
 *
 *  They live here rather than inside TradeCard because the stocks arithmetic
 *  plan (`/api/stocks/exit-plan`, piece 6) reports the SAME fields under the
 *  SAME names, having been built from the same `compute_final_stop` and
 *  `compute_target_row`. Two copies of this prose would eventually explain one
 *  card's stop differently from the other's for identical numbers.
 *
 *  Both signatures are STRUCTURAL — the minimum set of fields each sentence
 *  reads — so the options `ExitPlan['stop']` / `ExitPlanTargetRow` and the
 *  stocks `StockExitPlanStop` / `StockExitPlanTargetRow` both satisfy them
 *  without either card's type having to know about the other's.
 */

/** The stop row's one-sentence justification — three cases, and no fourth:
 *  nothing structural found nearby, structural used as-is, or structural found
 *  but too tight and widened out to the ATR floor. */
export function stopJustification(stop: {
  source: 'structural' | 'atr_widened';
  structuralPrice: number | null;
  atrFloorPrice: number;
  distanceDollar: number | null;
}): string {
  if (stop.structuralPrice == null) {
    return `No structural stop found nearby — stop set at the ATR floor of $${stop.atrFloorPrice.toFixed(2)}`;
  }
  if (stop.source === 'structural') {
    const cleared = stop.distanceDollar != null ? stop.distanceDollar.toFixed(2) : '0.00';
    return `Using structural — it already clears the ATR floor by $${cleared}, no widening needed`;
  }
  return `Structural stop $${stop.structuralPrice.toFixed(2)} was inside the ATR floor — widened to $${stop.atrFloorPrice.toFixed(2)} for a minimum-distance stop`;
}

/** FOUR explicit states per target row, not three — "outside tolerance but
 *  still short of the structural level" gets its own label rather than folding
 *  into the "beyond" warning bucket, because the two mean opposite things about
 *  the target's realism. */
export type TargetCompareState = 'none' | 'within' | 'before' | 'beyond';

export function targetCompareState(t: {
  structuralPrice: number | null;
  tpSource: 'arithmetic' | 'structural_snap';
  qualityReasons: string[];
}): TargetCompareState {
  if (t.structuralPrice == null) return 'none';
  if (t.tpSource === 'structural_snap') return 'within';
  return t.qualityReasons.includes('target_beyond_structural') ? 'beyond' : 'before';
}

export function targetCompareLabel(state: TargetCompareState): string {
  switch (state) {
    case 'none':
      return 'No structural level found ahead — nothing to compare against.';
    case 'within':
      return 'Within tolerance — snapped onto the structural level.';
    case 'before':
      return 'Outside tolerance — using arithmetic price, sits before the next structural level.';
    case 'beyond':
      return 'Target sits beyond the next real structural level.';
  }
}
