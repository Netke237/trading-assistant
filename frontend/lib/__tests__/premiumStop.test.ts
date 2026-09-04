/**
 * Piece 4 — the per-position premium stop, frontend half.
 *
 * Mirrors backend/tests/test_premium_stop_per_position.py. The two engines are
 * documented mirrors of each other: a rule proved there should have a
 * counterpart here, because a preview that disagrees with the alert that later
 * fires is worse than no preview.
 */
import {
  resolvePremiumStopPct,
  hasOwnPremiumStopPct,
  premiumStopThresholdPrice,
  formatPremiumStopPct,
  PREMIUM_STOP_PCT_FALLBACK,
} from '../premiumStop';
import { premiumStopPctFromDollars } from '../barrierRace';
import { scanPortfolio, type AlertPosition } from '../alertEngine';

// ── The resolver ────────────────────────────────────────────────────────────

describe('resolvePremiumStopPct', () => {
  it('inherits the global when the position carries no value', () => {
    expect(resolvePremiumStopPct(null, 0.60)).toBe(0.60);
    expect(resolvePremiumStopPct(undefined, 0.60)).toBe(0.60);
  });

  it('prefers the position value over the global', () => {
    expect(resolvePremiumStopPct(0.45, 0.60)).toBe(0.45);
  });

  it('moves inheriting positions when the global changes and leaves set ones alone', () => {
    // The whole point of null-means-inherit. A position stamped with the
    // global's value at creation would be frozen at it.
    expect(resolvePremiumStopPct(null, 0.60)).toBe(0.60);
    expect(resolvePremiumStopPct(null, 0.75)).toBe(0.75);
    expect(resolvePremiumStopPct(0.45, 0.60)).toBe(0.45);
    expect(resolvePremiumStopPct(0.45, 0.75)).toBe(0.45);
  });

  it('falls back when no global was supplied either', () => {
    expect(resolvePremiumStopPct(null, null)).toBe(PREMIUM_STOP_PCT_FALLBACK);
    expect(resolvePremiumStopPct(undefined, undefined)).toBe(PREMIUM_STOP_PCT_FALLBACK);
  });

  it('agrees with the Python resolver on the inherit/set contract', () => {
    // Same table as test_changing_the_global_moves_null_positions_and_leaves_set_ones_alone
    expect(hasOwnPremiumStopPct(null)).toBe(false);
    expect(hasOwnPremiumStopPct(undefined)).toBe(false);
    expect(hasOwnPremiumStopPct(0.45)).toBe(true);
  });
});

describe('premiumStopThresholdPrice', () => {
  it('is entry x (1 - pct)', () => {
    expect(premiumStopThresholdPrice(5.0, 0.60)).toBeCloseTo(2.0);
    expect(premiumStopThresholdPrice(5.0, 0.30)).toBeCloseTo(3.5);
  });
});

// ── The drawer's inherited-vs-set display ───────────────────────────────────

describe('formatPremiumStopPct', () => {
  it('marks an inherited value as global', () => {
    // An inherited value that looks set is how a user comes to believe they
    // have per-position control they do not have.
    expect(formatPremiumStopPct(null, 0.60)).toBe('60% (global)');
    expect(formatPremiumStopPct(undefined, 0.60)).toBe('60% (global)');
  });

  it('prints a set value bare', () => {
    expect(formatPremiumStopPct(0.45, 0.60)).toBe('45%');
  });

  it('distinguishes a set value that happens to equal the global', () => {
    // The two states must remain visibly different even at the same number,
    // because only one of them keeps tracking the global.
    expect(formatPremiumStopPct(0.60, 0.60)).toBe('60%');
    expect(formatPremiumStopPct(null, 0.60)).toBe('60% (global)');
  });
});

// ── The alert engine resolves PER POSITION, not once per scan ───────────────

function position(overrides: Partial<AlertPosition> = {}): AlertPosition {
  return {
    recId: 'r1', symbol: 'AAPL', contract: 'AAPL|190|2026-05-16|C',
    currentPrice: 3.4, entryPrice: 5.0, stop: null, targets: [],
    dteRemaining: 30, dteTotal: 30, pnlPct: -32, direction: 'Bullish',
    ...overrides,
  };
}

const premiumStopAlerts = (positions: AlertPosition[], globalPct: number) =>
  scanPortfolio(positions, { premiumStopPct: globalPct })
    .filter((a) => a.alertType === 'PREMIUM_STOP');

describe('scanPortfolio premium stop resolution', () => {
  it('fires for a position whose own stop is tighter than the global', () => {
    // -32% is past this position's 30% stop, nowhere near the global 60%.
    expect(premiumStopAlerts([position({ premiumStopPct: 0.30 })], 0.60)).toHaveLength(1);
  });

  it('does not fire at the same loss for an inheriting position', () => {
    // The control: identical pnlPct, the only difference is inheritance.
    expect(premiumStopAlerts([position({ premiumStopPct: null })], 0.60)).toHaveLength(0);
  });

  it('suppresses a fire the global would have made when the position has more room', () => {
    const loss = position({ pnlPct: -65 });
    expect(premiumStopAlerts([{ ...loss, premiumStopPct: null }], 0.60)).toHaveLength(1);
    expect(premiumStopAlerts([{ ...loss, premiumStopPct: 0.70 }], 0.60)).toHaveLength(0);
  });

  it('resolves each position independently within one scan', () => {
    // The regression this piece exists to prevent: one threshold hoisted out
    // of the loop meant every open position shared a single number.
    const alerts = premiumStopAlerts([
      position({ recId: 'tight', premiumStopPct: 0.30 }),
      position({ recId: 'inherits', premiumStopPct: null }),
      position({ recId: 'loose', premiumStopPct: 0.70 }),
    ], 0.60);
    expect(alerts.map((a) => a.recId)).toEqual(['tight']);
  });
});

// ── Both send paths derive the same fraction ────────────────────────────────

describe('send-path derivation', () => {
  // The card's "Premium stop" field holds a DOLLAR loss. Both send paths now
  // carry that dollar amount straight through; the FRACTION is derived
  // server-side, in the one place the persisted entry price is known.
  //
  // Why it moved: `portfolio.py` replaces `entry_price` with the live quote
  // when there is one, and the alert compares `opt_price <= entry_price *
  // (1 - pct)` against exactly that stored value. A fraction derived here
  // against the card's mid would be re-anchored to a price the server
  // replaced -- a $3.12 stop on a $5.20 premium filling at $4.00 silently
  // becomes a $2.40 stop. An earlier version of this file asserted that drift
  // was correct; it was not, it just matched how the client happened to
  // compute it.
  const dollarStop = 3.12;
  const cardMid = 5.20;

  it('keeps the dollar amount the user typed, whatever the fill', () => {
    // The property that matters: the stop is $3.12 of premium at risk, and it
    // stays $3.12 regardless of which price the position is finally booked at.
    // The fraction is whatever reproduces that against the real entry.
    for (const entry of [cardMid, 4.00, 6.10]) {
      const pct = dollarStop / entry;
      expect(premiumStopThresholdPrice(entry, pct)).toBeCloseTo(entry - dollarStop);
    }
  });

  it('still refuses a dollar stop at or above the whole premium', () => {
    // A total loss is unreachable-by-definition rather than a stop. The
    // backend stores NULL (inherit the global) rather than a fraction >= 1.
    expect(premiumStopPctFromDollars(5.20, cardMid)).toBeUndefined();
    expect(premiumStopPctFromDollars(6.00, cardMid)).toBeUndefined();
  });

  it('treats an unset or non-positive stop as inherit-the-global', () => {
    expect(premiumStopPctFromDollars(null, cardMid)).toBeUndefined();
    expect(premiumStopPctFromDollars(undefined, cardMid)).toBeUndefined();
    expect(premiumStopPctFromDollars(0, cardMid)).toBeUndefined();
    expect(premiumStopPctFromDollars(-1, cardMid)).toBeUndefined();
  });
});
