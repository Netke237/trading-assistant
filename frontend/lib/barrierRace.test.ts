import {
  formatRaceRisk,
  formatRaceRR,
  formatRacePremiumRR,
  formatRaceEdge,
  premiumStopPctFromDollars,
  premiumStopSourceNote,
  money,
} from './barrierRace';
import type { BarrierRaceOutcome } from '@/types/domain';

/** A known row, taken from a real run of the reference contract:
 *  AAPL-shaped long call, $185 spot / $190 strike / 30 DTE / $5.20 premium,
 *  stop at $176, 60% premium stop, T1 = +20%. */
const ROW: BarrierRaceOutcome = {
  targetPct: 0.20,
  targetOptionPrice: 6.24,
  pTargetFirst: 0.27,
  pStockStopFirst: 0.00,
  pPremiumStopFirst: 0.68,
  pNeither: 0.05,
  daysTarget: 7,
  daysStockStop: null,
  daysPremiumStop: 20,
  terminalMean: 3.64,
  rewardDollar: 1.04,
  repriceDaysStockStop: 7,
  stopRepricedValue: 0.18,
  riskStockStop: 5.02,
  riskPremiumStop: 3.12,
  rrStockStop: 0.2072,
  rrPremiumStop: 0.3333,
  // The four printed terms sum to exactly this, per share: 0.27 x 1.04
  // - 0.00 x 5.02 - 0.68 x 3.12 + 0.05 x -1.56 = -1.9188. The fixture used to
  // say -193.28, so the very test asserting "the card prints a chain you can
  // check" pinned a chain that does not add up — 1.4c per share out.
  edgePerContract: -191.88,
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
      '$5.20 premium - $0.18 at the stop (repriced at 7d) = $5.02',
    );
  });

  it('shows a fractional reprice horizon when the DTE clamp bound', () => {
    expect(formatRaceRisk({ ...ROW, repriceDaysStockStop: 2.25 }, PREMIUM)).toContain(
      '(repriced at 2.3d)',
    );
  });

  it('says so rather than printing a broken chain when the reprice failed', () => {
    const s = formatRaceRisk({ ...ROW, stopRepricedValue: null, riskStockStop: null }, PREMIUM);
    expect(s).toContain('could not reprice');
    expect(s).not.toContain('=');
  });
});

describe('formatRaceRR', () => {
  it('prints reward over risk and the resulting ratio', () => {
    expect(formatRaceRR(ROW)).toBe('$1.04 / $5.02 = 0.21x');
  });

  it('preserves the sign of a negative reward rather than nulling it to an em dash', () => {
    // M2 parity with the backend's reward_risk.py, inherited from the readout
    // this replaced: a target priced BELOW the premium paid is a real loss the
    // trader should see, not an indistinguishable "not yet computed".
    const s = formatRaceRR({ ...ROW, rewardDollar: -2.00, rrStockStop: -0.3984 });
    expect(s).toBe('-$2.00 / $5.02 = -0.40x');
  });

  it('renders an em dash, never a negative or infinite ratio, when risk is not positive', () => {
    // A deep-ITM contract on a tight stop: still worth more at the stop than
    // it cost, so there is no risk to divide by.
    const s = formatRaceRR({ ...ROW, riskStockStop: -70.8, rrStockStop: null });
    expect(s).toContain('—');
    expect(s).not.toMatch(/-?\d+\.\d+x/);
  });
});

describe('formatRacePremiumRR', () => {
  it('labels itself as the constant it is, showing the dollars as inputs', () => {
    const s = formatRacePremiumRR(ROW, 0.60);
    expect(s).toContain('$1.04 / $3.12');
    expect(s).toContain('20% / 60% = 0.33x on every contract');
  });

  it('does not claim the two rounded dollar legs divide to the constant', () => {
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
      0.60,
    );
    expect(small).toContain('$0.21 / $0.62');
    expect(small).toContain('20% / 60% = 0.33x on every contract');
    expect(small).not.toContain('$0.62 = 0.33x');
  });

  it('says so plainly when there is no premium-stop risk to divide by', () => {
    // A 5c contract with a 5% stop puts the risk leg at $0.00 in cents.
    const s = formatRacePremiumRR(
      { ...ROW, rewardDollar: 0.01, riskPremiumStop: 0, rrPremiumStop: null }, 0.05,
    );
    expect(s).toContain('no premium-stop risk to divide by');
    expect(s).not.toMatch(/=\s*0\.00x/);
  });
});

describe('premiumStopSourceNote', () => {
  it('credits the editable field when the field is what set the barrier', () => {
    expect(premiumStopSourceNote(0.60, 3.12, 5.20))
      .toBe('60% of premium, from the editable field above');
  });

  it('says the default was used when the field could not set the barrier', () => {
    // The field holds a DOLLAR amount fixed at SCAN time; the premium below is
    // the one quoted now. A contract that has since fallen makes the fraction
    // >= 1, nothing is sent, and the backend applies its own default — while
    // the card used to state unconditionally that the level came "from the
    // editable field above".
    const s = premiumStopSourceNote(0.60, 3.00, 2.50);
    expect(s).toContain('the default');
    expect(s).toContain('$3.00');
    expect(s).toContain('$2.50');
    expect(s).not.toContain('from the editable field above');
  });

  it('says the default was used when no premium stop is set at all', () => {
    expect(premiumStopSourceNote(0.60, null, 5.20))
      .toContain('because no premium stop is set above');
  });
});

describe('formatRaceEdge', () => {
  it('prints all four signed contributions, per share and per contract', () => {
    expect(formatRaceEdge(ROW, PREMIUM)).toBe(
      '0.27 x $1.04 - 0.00 x $5.02 - 0.68 x $3.12 + 0.05 x -$1.56 = -$1.92  ->  -$191.88 per contract',
    );
  });

  it('keeps the fourth term positive when those paths end above the premium paid', () => {
    // Signed, not a loss. Writing it as "- p x loss" would be wrong here.
    const s = formatRaceEdge({ ...ROW, terminalMean: 8.00 }, PREMIUM);
    expect(s).toContain('+ 0.05 x $2.80');
  });

  it('prints a negative stock-stop risk leg as the gain it is, and says why', () => {
    // A deep-ITM contract on a tight stop can be worth MORE at the stop than it
    // cost. Subtracting that negative leg adds to the edge, which is correct
    // signed EV but read as an unexplained "- 0.00 x -$70.80" beside an R:R
    // column showing an em dash, with nothing connecting the two.
    const s = formatRaceEdge(
      { ...ROW, riskStockStop: -70.80, rrStockStop: null, pStockStopFirst: 0.12 }, PREMIUM,
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
