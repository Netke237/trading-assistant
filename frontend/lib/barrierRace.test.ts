import {
  formatRaceRisk,
  formatRaceRR,
  formatRacePremiumRR,
  formatRaceEdge,
  premiumStopPctFromDollars,
  premiumStopSourceNote,
  weightPercents,
  money,
} from './barrierRace';
import type { BarrierRaceOutcome } from '@/types/domain';

/** A known row — genuinely `_run()`'s output for the reference contract, not a
 *  hand-written approximation of it: AAPL-shaped long call, $185 spot / $190
 *  strike / 30 DTE / $5.20 premium, stop at $176, 60% premium stop, T1 = +20%,
 *  seed 42.
 *
 *  It used to be hand-written, and carried values the backend cannot emit — an
 *  `edgePerContract` of -193.28 when every edge is a whole number of dollars by
 *  construction, and four shares that were all exact two-decimal values, which
 *  are precisely the ones on which a rounding disagreement is impossible. A
 *  fixture that cannot exhibit the failure cannot test for it. */
const ROW: BarrierRaceOutcome = {
  targetPct: 0.20,
  targetOptionPrice: 6.24,
  pTargetFirst: 0.2685,
  pStockStopFirst: 0.0,
  pPremiumStopFirst: 0.6865,
  pNeither: 0.045,
  daysTarget: 7,
  daysStockStop: null,
  daysPremiumStop: 20,
  daysAnyPathReachedStop: 26,
  // Allocated by the backend, summing to exactly 1.00. Note 0.045 -> 0.04:
  // JavaScript's toFixed(2) agrees, and the Python imitation this replaced
  // gave 0.05, which is what stopped the chain adding up.
  weightTargetFirst: 0.27,
  weightStockStopFirst: 0.0,
  weightPremiumStopFirst: 0.69,
  weightNeither: 0.04,
  terminalMean: 3.64,
  rewardDollar: 1.04,
  repriceDaysStockStop: 26,
  stopRepricedValue: 0.03,
  riskStockStop: 5.17,
  riskPremiumStop: 3.12,
  rrStockStop: 0.20116054158607352,
  rrPremiumStop: 0.33333333333333337,
  edgePerContract: -193.0,
};

const PREMIUM = 5.20;

describe('money', () => {
  it('puts the minus outside the dollar sign', () => {
    expect(money(5.2)).toBe('$5.20');
    expect(money(-1.2)).toBe('-$1.20');
    expect(money(0)).toBe('$0.00');
  });
});

describe('formatRaceRisk', () => {
  it('prints the chain, and the chain adds up', () => {
    expect(formatRaceRisk(ROW, PREMIUM)).toBe(
      '$5.20 premium - $0.03 at the stop '
      + '(repriced at 26d — the median day any path reaches the stop) = $5.17',
    );
  });

  it('shows a fractional reprice horizon when the DTE clamp bound', () => {
    // 2.25d, not "2.3d": the printed input must BE the one the arithmetic used.
    expect(formatRaceRisk({ ...ROW, repriceDaysStockStop: 2.25 }, PREMIUM)).toContain(
      'repriced at 2.25d',
    );
  });

  it('names where the horizon came from, so it is not a third unexplained day count', () => {
    // The card already shows two other day counts for the stop: the table's
    // "to stock stop" column (conditional on the stop winning the race) and
    // the barriers block's "median ~26d" (unconditional). This chain uses the
    // unconditional one, and printing a bare "26d" beside a column reading "—"
    // left the user to guess which of three numbers it was.
    expect(formatRaceRisk(ROW, PREMIUM)).toContain('the median day any path reaches the stop');
    const noStop = formatRaceRisk(
      { ...ROW, daysAnyPathReachedStop: null, repriceDaysStockStop: 7 }, PREMIUM,
    );
    expect(noStop).toContain('the preset default; no path reached the stop');
  });

  it('says so rather than printing a broken chain when the reprice failed', () => {
    const s = formatRaceRisk({ ...ROW, stopRepricedValue: null, riskStockStop: null }, PREMIUM);
    expect(s).toContain('could not reprice');
    expect(s).not.toContain('=');
  });
});

describe('formatRaceRR', () => {
  it('prints reward over risk and the resulting ratio', () => {
    expect(formatRaceRR(ROW)).toBe('$1.04 / $5.17 = 0.20x');
  });

  it('preserves the sign of a negative reward rather than nulling it to an em dash', () => {
    // M2 parity with the backend's reward_risk.py, inherited from the readout
    // this replaced: a target priced BELOW the premium paid is a real loss the
    // trader should see, not an indistinguishable "not yet computed".
    const s = formatRaceRR({ ...ROW, rewardDollar: -2.00, rrStockStop: -0.3868 });
    expect(s).toBe('-$2.00 / $5.17 = -0.39x');
  });

  it('renders an em dash, never a negative or infinite ratio, when risk is not positive', () => {
    // Still worth more at the stop than it cost, so there is no risk to divide
    // by. Reachable when the quote's IV cannot be solved.
    const s = formatRaceRR({ ...ROW, riskStockStop: -70.8, rrStockStop: null });
    expect(s).toContain('worth more there than it cost');
    expect(s).not.toMatch(/-?\d+\.\d+x/);
  });

  it('gives the right reason when the stop could not be repriced at all', () => {
    // A DIFFERENT state from "worth more than it cost", and it used to print
    // that sentence — directly under formatRaceRisk's "could not reprice at the
    // stop", two adjacent lines explaining one state incompatibly.
    const s = formatRaceRR({ ...ROW, stopRepricedValue: null, riskStockStop: null, rrStockStop: null });
    expect(s).toContain('could not reprice at the stop');
    expect(s).not.toContain('worth more there than it cost');
  });
});

describe('weightPercents', () => {
  it('scales the backend allocation, so the four labels sum to exactly 100', () => {
    // The allocation happens once, in the backend, and weights the edge. This
    // only scales it — there is no second rounding here to disagree with the
    // first. The T35% row of the reference contract, whose raw shares
    // (0.138 / 0 / 0.785 / 0.077) render as 14 + 0 + 79 + 8 = 101% if each is
    // rounded on its own.
    const row = {
      ...ROW,
      weightTargetFirst: 0.14,
      weightStockStopFirst: 0.0,
      weightPremiumStopFirst: 0.78,
      weightNeither: 0.08,
    };
    expect(weightPercents(row)).toEqual([14, 0, 78, 8]);
    expect(weightPercents(row).reduce((a, b) => a + b, 0)).toBe(100);
  });

  it('is the SAME four numbers the edge chain prints', () => {
    // The point of taking these from the backend. A largest-remainder
    // allocation done here fixed the row sum but left the chain below printing
    // an independently-rounded multiplier for the same outcome on ~48% of real
    // rows — the table reading "Neither 49%" beside a chain reading "+ 0.48 x".
    const labels = weightPercents(ROW);
    const chain = formatRaceEdge(ROW, PREMIUM);
    labels.forEach((label) => {
      expect(chain).toContain(`${(label / 100).toFixed(2)} x`);
    });
  });

  it('survives the binary-float tail in the scaling', () => {
    // 0.14 * 100 is 14.000000000000002.
    expect(weightPercents({ ...ROW, weightTargetFirst: 0.14 })[0]).toBe(14);
    expect(weightPercents({ ...ROW, weightTargetFirst: 0.29 })[0]).toBe(29);
  });
});

describe('formatRacePremiumRR', () => {
  it('labels itself as the constant it is, showing the dollars as inputs', () => {
    const s = formatRacePremiumRR(ROW);
    expect(s).toContain('legs $1.04 and $3.12');
    expect(s).toContain('0.33x, which is your target % over your stop %');
    // No slash between the two dollar amounts: it reads as a division to the
    // one audience this card is for, and the quotient is not the ratio.
    expect(s).not.toContain('$1.04 / $3.12');
  });

  it('does not print a division between two roundings that does not produce the ratio', () => {
    // THE POINT. On a $1.03 premium the legs quantize to $0.21 and $0.62, whose
    // quotient is 0.34x, not the 0.33x this column IS by definition. The old
    // wording printed "$0.21 / $0.62 = 0.33x", asserting an identity that is
    // false by up to 14% on sub-$1 premiums — on the one column whose entire
    // purpose is to disclose that it tells you nothing.
    //
    // (The previous test here claimed to check this "regardless of the
    // premium" and then varied no premium at all: it asserted the fixture's own
    // hard-coded 0.3333 was close to 0.20/0.60. A tautology under a title that
    // promised a property.)
    const small = formatRacePremiumRR(
      { ...ROW, rewardDollar: 0.21, riskPremiumStop: 0.62, rrPremiumStop: 1 / 3 },
    );
    expect(small).toContain('legs $0.21 and $0.62');
    expect(small).toContain('0.33x, which is your target % over your stop %');
    expect(small).not.toContain('$0.21 / $0.62');
    // And no "20% / 60% = 0.33x" either. Both percentages render at 0dp while
    // premiumStopPct is an arbitrary float (a scan-time dollar stop over the
    // premium quoted now), so on a third of realistic combinations the printed
    // division does not produce the printed ratio: a $0.20 stop on a $0.70
    // premium prints "10% / 29%", which is 0.34, beside a true 0.35.
    expect(small).not.toMatch(/\d+% \/ \d+% =/);
  });

  it('says so plainly when there is no premium-stop risk to divide by', () => {
    // A DEFENSIVE guard, not a reachable wire state. rrPremiumStop is null only
    // when premium_stop_pct is non-positive, which the endpoint rejects
    // (Field(gt=0, lt=1)) and the scoring default cannot produce. The 5c/5%
    // case people reach for here does NOT hit it: the backend takes the ratio
    // from the definition, so it returns the honest 4.00x even when the dollar
    // risk leg quantizes to $0.00 (see the backend test of the same scenario).
    const s = formatRacePremiumRR(
      { ...ROW, rewardDollar: 0.01, riskPremiumStop: 0, rrPremiumStop: null },
    );
    expect(s).toContain('no premium-stop risk to divide by');
    expect(s).not.toMatch(/=\s*0\.00x/);
  });
});

describe('premiumStopSourceNote', () => {
  it('marks the percentage as approximate, because it does not reproduce the level', () => {
    // appliedPct is an arbitrary float — a scan-time dollar stop over the
    // premium quoted now — so a 0dp percentage failed to reproduce the barrier
    // level printed in the next cell on 84% of rows: a $3.19 barrier labelled
    // "53% of premium" against a $6.84 premium, where 53% is $3.21.
    expect(premiumStopSourceNote(0.5336, true, 3.19, 6.84)).toContain('~53% of premium');
  });

  it('credits the editable field when the field is what set the barrier', () => {
    expect(premiumStopSourceNote(0.60, true, 3.12, 5.20))
      .toBe('~60% of premium, from the editable field above');
  });

  it('takes the decision from the caller, not from the rounded premium', () => {
    // The request divides by the RAW quoted premium; this note used to
    // re-derive the decision from the backend's cent-rounded premiumUsed. In
    // the band where the two straddle 1.0 they disagree: a 2.996 quote against
    // a $2.998 field makes the request send nothing (1.0007 -> undefined) while
    // re-deriving gives 2.998/3.00 = 0.9993, crediting a field that was ignored.
    expect(premiumStopSourceNote(0.60, false, 2.998, 3.00)).toContain('the default');
    expect(premiumStopSourceNote(0.60, true, 3.00, 3.00))
      .toBe('~60% of premium, from the editable field above');
  });

  it('says the default was used when the field could not set the barrier', () => {
    // The field holds a DOLLAR amount fixed at SCAN time; the premium below is
    // the one quoted now. A contract that has since fallen makes the fraction
    // >= 1, nothing is sent, and the backend applies its own default — while
    // the card used to state unconditionally that the level came "from the
    // editable field above".
    const s = premiumStopSourceNote(0.60, false, 3.00, 2.50);
    expect(s).toContain('the default');
    expect(s).toContain('$3.00');
    expect(s).toContain('$2.50');
    expect(s).not.toContain('from the editable field above');
  });

  it('says the default was used when no premium stop is set at all', () => {
    expect(premiumStopSourceNote(0.60, false, null, 5.20))
      .toContain('because no premium stop is set above');
  });
});

describe('formatRaceEdge', () => {
  it('prints all four signed contributions, per share and per contract', () => {
    expect(formatRaceEdge(ROW, PREMIUM)).toBe(
      '0.27 x $1.04 - 0.00 x $5.17 - 0.69 x $3.12 + 0.04 x -$1.56 = -$1.93  ->  -$193.00 per contract',
    );
  });

  it('keeps the fourth term positive when those paths end above the premium paid', () => {
    // Signed, not a loss. Writing it as "- p x loss" would be wrong here.
    const s = formatRaceEdge({ ...ROW, terminalMean: 8.00 }, PREMIUM);
    expect(s).toContain('+ 0.04 x $2.80');
  });

  it('prints a negative stock-stop risk leg as the gain it is, and says why', () => {
    // A deep-ITM contract on a tight stop can be worth MORE at the stop than it
    // cost. Subtracting that negative leg adds to the edge, which is correct
    // signed EV but read as an unexplained "- 0.00 x -$70.80" beside an R:R
    // column showing an em dash, with nothing connecting the two.
    const s = formatRaceEdge(
      { ...ROW, riskStockStop: -70.80, rrStockStop: null, weightStockStopFirst: 0.12 }, PREMIUM,
    );
    expect(s).toContain('+ 0.12 x $70.80 (worth more at the stop than it cost)');
    expect(s).not.toContain('x -$70.80');
  });

  it('renders an em dash when there is no edge to print', () => {
    expect(formatRaceEdge({ ...ROW, edgePerContract: null }, PREMIUM)).toBe('—');
  });
});

describe('premiumStopPctFromDollars', () => {
  it('converts the card dollar stop into the fraction the barrier needs', () => {
    expect(premiumStopPctFromDollars(3.12, 5.20)).toBeCloseTo(0.60, 6);
  });

  it('refuses a stop at or above the whole premium', () => {
    // pct >= 1 makes the barrier unreachable by definition rather than a stop,
    // and the backend rejects it outright — do not send a 422.
    expect(premiumStopPctFromDollars(5.20, 5.20)).toBeUndefined();
    expect(premiumStopPctFromDollars(9.00, 5.20)).toBeUndefined();
  });

  it('refuses non-positive or non-finite inputs, falling back to the backend default', () => {
    expect(premiumStopPctFromDollars(0, 5.20)).toBeUndefined();
    expect(premiumStopPctFromDollars(-1, 5.20)).toBeUndefined();
    expect(premiumStopPctFromDollars(null, 5.20)).toBeUndefined();
    expect(premiumStopPctFromDollars(undefined, 5.20)).toBeUndefined();
    expect(premiumStopPctFromDollars(NaN, 5.20)).toBeUndefined();
    expect(premiumStopPctFromDollars(3.12, 0)).toBeUndefined();
  });
});
