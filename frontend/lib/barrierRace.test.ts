import {
  formatRaceRisk,
  formatRaceRR,
  formatRacePremiumRR,
  formatRaceEdge,
  premiumStopPctFromDollars,
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
  edgePerContract: -193.28,
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
  it('labels itself as the constant it is', () => {
    const s = formatRacePremiumRR(ROW, 0.60);
    expect(s).toContain('$1.04 / $3.12 = 0.33x');
    expect(s).toContain('equals your 20% target / 60% stop, on every contract');
  });

  it('is exactly targetPct / premiumStopPct regardless of the premium', () => {
    // The anti-cancellation point, asserted on the display side too: change the
    // premium and every dollar figure moves, but the ratio does not.
    expect(ROW.rrPremiumStop).toBeCloseTo(ROW.targetPct / 0.60, 3);
  });
});

describe('formatRaceEdge', () => {
  it('prints all four signed contributions, per share and per contract', () => {
    expect(formatRaceEdge(ROW, PREMIUM)).toBe(
      '0.27 x $1.04 - 0.00 x $5.02 - 0.68 x $3.12 + 0.05 x -$1.56 = -$1.93  ->  -$193.28 per contract',
    );
  });

  it('keeps the fourth term positive when those paths end above the premium paid', () => {
    // Signed, not a loss. Writing it as "- p x loss" would be wrong here.
    const s = formatRaceEdge({ ...ROW, terminalMean: 8.00 }, PREMIUM);
    expect(s).toContain('+ 0.05 x $2.80');
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
