import {
  stopJustification,
  targetCompareState,
  targetCompareLabel,
} from '@/lib/exitPlanLabels';

/** These sentences moved out of TradeCard when the stocks arithmetic plan
 *  arrived. What this file defends is the reason for the move: the options
 *  `ExitPlan['stop']` / `ExitPlanTargetRow` and the stocks `StockExitPlanStop` /
 *  `StockExitPlanTargetRow` carry the same fields under the same names, so one
 *  implementation must serve both — two copies would drift and explain one
 *  card's stop differently from the other's for identical numbers. */

describe('stopJustification', () => {
  it('names the ATR floor when no structural level was found nearby', () => {
    expect(stopJustification({
      source: 'atr_widened', structuralPrice: null, atrFloorPrice: 144, distanceDollar: null,
    })).toBe('No structural stop found nearby — stop set at the ATR floor of $144.00');
  });

  it('says how much a structural stop cleared the floor by when it is used as-is', () => {
    expect(stopJustification({
      source: 'structural', structuralPrice: 140, atrFloorPrice: 144, distanceDollar: 4,
    })).toBe('Using structural — it already clears the ATR floor by $4.00, no widening needed');
  });

  it('says a structural stop was inside the floor and got widened', () => {
    expect(stopJustification({
      source: 'atr_widened', structuralPrice: 147, atrFloorPrice: 144, distanceDollar: 3,
    })).toBe(
      'Structural stop $147.00 was inside the ATR floor — widened to $144.00 for a minimum-distance stop',
    );
  });

  it('falls back to $0.00 rather than NaN when the distance is missing on a structural stop', () => {
    expect(stopJustification({
      source: 'structural', structuralPrice: 140, atrFloorPrice: 144, distanceDollar: null,
    })).toContain('$0.00');
  });

  it('reads the same for a stocks stop as for an options one with the same numbers', () => {
    // The whole point of the extraction, asserted rather than assumed. The two
    // objects below are the minimum each card's type supplies.
    const optionsStop = {
      source: 'atr_widened' as const, structuralPrice: 147, atrFloorPrice: 144,
      distanceDollar: 3, contractPrice: 1.2, rrModel: 'Delta approximation',
    };
    const stocksStop = {
      source: 'atr_widened' as const, structuralPrice: 147, atrFloorPrice: 144,
      distanceDollar: 3, riskPerShare: 6, probability: 0.34, expectedDays: 6,
    };
    expect(stopJustification(optionsStop)).toBe(stopJustification(stocksStop));
  });
});

describe('targetCompareState', () => {
  const base = { tpSource: 'arithmetic' as const, qualityReasons: [] as string[] };

  it('is "none" when nothing structural lies ahead', () => {
    expect(targetCompareState({ ...base, structuralPrice: null })).toBe('none');
  });

  it('is "within" on a snap', () => {
    expect(targetCompareState({
      ...base, structuralPrice: 170, tpSource: 'structural_snap',
    })).toBe('within');
  });

  it('is "beyond" when the target overshoots the next real level', () => {
    expect(targetCompareState({
      ...base, structuralPrice: 170, qualityReasons: ['target_beyond_structural'],
    })).toBe('beyond');
  });

  it('is "before" — its own state, not folded into "beyond" — outside tolerance but short of the level', () => {
    // FOUR states, not three. "outside the snap band but still short of the
    // structural level" and "past the structural level" mean opposite things
    // about the target's realism, so they get different labels.
    expect(targetCompareState({
      ...base, structuralPrice: 170, qualityReasons: ['stop_widened'],
    })).toBe('before');
  });
});

describe('targetCompareLabel', () => {
  it('has a distinct sentence for every state', () => {
    const states = ['none', 'within', 'before', 'beyond'] as const;
    const labels = states.map(targetCompareLabel);
    expect(new Set(labels).size).toBe(states.length);
    for (const label of labels) expect(label.length).toBeGreaterThan(0);
  });
});
