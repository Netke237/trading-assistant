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
  // `positionFromOrder` and `buildPaperPosition` are module-private to the
  // Step 7 page, so what is asserted here is the rule they BOTH apply: one
  // shared converter, against each path's own resolved entry price. These two
  // paths already disagree about stop re-anchoring; a second field they
  // disagree on would mean the premium stop a position is armed at depends on
  // which button was pressed.
  const dollarStop = 3.12;
  const cardMid = 5.20;

  it('produces one fraction for the same card in both paths', () => {
    // buildPaperPosition: livePrice ?? cd.mid ?? entry.limit  (no live price)
    // positionFromOrder:  cd.mid ?? entry.limit
    // Same inputs, same resolved mid, therefore the same fraction.
    const fromPaper = premiumStopPctFromDollars(dollarStop, cardMid);
    const fromOrder = premiumStopPctFromDollars(dollarStop, cardMid);
    expect(fromPaper).toBeCloseTo(0.60);
    expect(fromOrder).toBe(fromPaper);
  });

  it('tracks the live fill price when one is supplied, because entryPrice does too', () => {
    // Not a disagreement: the stored fraction must be relative to the
    // entryPrice actually persisted, since the alert compares
    // `opt_price <= entry_price * (1 - pct)`. A fill at 4.00 with the same
    // $3.12 dollar stop is a deeper fraction of that smaller premium.
    expect(premiumStopPctFromDollars(dollarStop, 4.00)).toBeCloseTo(0.78);
  });

  it('refuses a dollar stop at or above the whole premium', () => {
    // A total loss is unreachable-by-definition rather than a stop, and the
    // backend bounds the fraction at (0, 1) — refuse here rather than post a
    // value the API will 422.
    expect(premiumStopPctFromDollars(5.20, cardMid)).toBeUndefined();
    expect(premiumStopPctFromDollars(6.00, cardMid)).toBeUndefined();
  });

  it('treats an unset or non-positive stop as inherit-the-global', () => {
    expect(premiumStopPctFromDollars(null, cardMid)).toBeUndefined();
    expect(premiumStopPctFromDollars(undefined, cardMid)).toBeUndefined();
    expect(premiumStopPctFromDollars(0, cardMid)).toBeUndefined();
    expect(premiumStopPctFromDollars(-1, cardMid)).toBeUndefined();
  });

  it('round-trips against the threshold the alert will compare', () => {
    // The closing of the loop: the dollar stop the user typed on the card, the
    // fraction persisted, and the price the backend fires at are one decision.
    const pct = premiumStopPctFromDollars(dollarStop, cardMid)!;
    expect(premiumStopThresholdPrice(cardMid, pct)).toBeCloseTo(cardMid - dollarStop);
  });
});
