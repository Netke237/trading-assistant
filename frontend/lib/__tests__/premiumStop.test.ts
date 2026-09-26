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
  premiumStopFiringPrice,
  premiumStopDollarToSend,
  formatPremiumStopPct,
  PREMIUM_STOP_PCT_FALLBACK,
  PREMIUM_STOP_MIN_PCT,
  PREMIUM_STOP_MAX_PCT,
  premiumStopDollarBounds,
  pythonRound4,
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

  it('hasOwnPremiumStopPct: null/undefined inherit, any number is the position\'s own (including 0)', () => {
    // The same inherit/set rule is tested separately on the Python side, in
    // test_premium_stop_per_position.py::test_changing_the_global_moves_null_positions_and_leaves_set_ones_alone.
    // This is NOT a cross-language check -- nothing here runs the Python.
    expect(hasOwnPremiumStopPct(null)).toBe(false);
    expect(hasOwnPremiumStopPct(undefined)).toBe(false);
    expect(hasOwnPremiumStopPct(0.45)).toBe(true);
    expect(hasOwnPremiumStopPct(0)).toBe(true);
  });
});

describe('premiumStopThresholdPrice', () => {
  it('is entry x (1 - pct)', () => {
    expect(premiumStopThresholdPrice(5.0, 0.60)).toBeCloseTo(2.0);
    expect(premiumStopThresholdPrice(5.0, 0.30)).toBeCloseTo(3.5);
  });
});

describe('premiumStopFiringPrice', () => {
  it('never names a price above the threshold, across the whole ordinary range', () => {
    // ROUND 12's GATE finding was a preview that printed a price the alert
    // would not fire at, and the test guarding it pinned ONE pair that
    // happened to work. A single hand-picked pair cannot establish this
    // property: the failure depends on whether `t * 100` lands on its integer,
    // which varies pair by pair. So sweep it.
    let trapsHit = 0;
    for (let entryCents = 100; entryCents <= 1400; entryCents += 7) {
      const entry = entryCents / 100;
      for (let pctBp = 1; pctBp <= 99; pctBp += 1) {
        const pct = pctBp / 100;
        const threshold = premiumStopThresholdPrice(entry, pct);
        const printed = premiumStopFiringPrice(entry, pct);

        // THE PROPERTY: what we print is a price the engines actually fire at.
        expect(printed).toBeLessThanOrEqual(threshold);
        // ...and it is the LARGEST such 2dp price, so the preview is not
        // needlessly pessimistic — a cent more would miss.
        expect(Number((printed + 0.01).toFixed(2))).toBeGreaterThan(threshold);

        // Count how often the naive expression would have been wrong, so this
        // test fails loudly if someone "simplifies" the helper back to it.
        if (Math.floor(threshold * 100) / 100 > threshold) trapsHit++;
      }
    }
    // The trap is real and common — if this ever reads 0, the sweep has stopped
    // covering the case it exists for.
    expect(trapsHit).toBeGreaterThan(0);
  });

  it('agrees with scanPortfolio on the exact reported case', () => {
    // entry $4.00 at 7%: threshold 3.7199999999999998, naive floor prints 3.72.
    expect(premiumStopFiringPrice(4.00, 0.07)).toBe(3.71);
    const at = (currentPrice: number) =>
      premiumStopAlerts([position({ entryPrice: 4.00, currentPrice, premiumStopPct: 0.07 })], 0.60).length;
    expect(at(3.71)).toBe(1);
    expect(at(3.72)).toBe(0);
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

// currentPrice/entryPrice are what PREMIUM_STOP compares — `pnlPct` is carried
// only because AlertPosition requires it and no longer drives this alert. Both
// engines now test `opt_price <= entry * (1 - pct)`; the frontend used to test
// a pnlPct the backend had already rounded to 2dp, and the two disagreed on the
// cent at the boundary. $3.40 against a $5.00 entry is a 32% loss.
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
    // $1.75 on a $5.00 entry — a 65% loss, past the global's 60% stop ($2.00)
    // but not past this position's own 70% one ($1.50).
    const loss = position({ currentPrice: 1.75, pnlPct: -65 });
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

// ── What the send paths actually post ───────────────────────────────────────

describe('premiumStopDollarToSend — the value both send paths post', () => {
  // This block replaces one that CLAIMED to mirror the two send paths and did
  // not: it exercised premiumStopPctFromDollars and premiumStopThresholdPrice,
  // two pure helpers that are on neither path any more (the derivation moved
  // server-side). The paths agreed only because they read the same map on
  // adjacent lines, and nothing pinned that — which is why a symbol-keyed
  // cache carrying the previous contract's dollar went unnoticed.
  //
  // The argument is now the page cache's entry for this contract, which is a
  // number ONLY when the user edited the field and null while it is untouched
  // (page.tsx writes `meta.touched.premiumStop ? overlay.premiumStop : null`).
  // What is left to pin here is what the function decides given that.
  const TYPED = 2.00;    // what a user actually typed on the card
  const SEEDED = 3.12;   // round(5.20 mid x 0.60 global, 2) — nobody chose this

  it('sends nothing while the field is untouched', () => {
    // THE BUG THIS EXISTS FOR. exit.premiumStop is the GLOBAL percentage
    // rendered in dollars, and the card reports its whole overlay on every
    // patch — so bumping Contracts cached $3.12 and posted it. The server then
    // divided it by an entry price it had just replaced with the live fill:
    // a $4.00 fill stored 0.78, arming a position at a threshold nobody chose,
    // reachable only by editing an unrelated field.
    expect(premiumStopDollarToSend(null)).toBeNull();
    expect(premiumStopDollarToSend(undefined)).toBeNull();
  });

  it('sends the value the user typed', () => {
    expect(premiumStopDollarToSend(TYPED)).toBe(TYPED);
  });

  it('sends a typed value even when it equals the seed the card was showing', () => {
    // REGRESSION. The old signature took the seed and treated `cached === seed`
    // as untouched, so a user who typed $2.00, changed their mind and typed
    // $3.12 back had that explicit choice silently discarded and the position
    // handed to the global — a $2.40 stop on a $4.00 fill rather than the
    // $3.12 they were looking at. Touched-ness is tracked now, so the value
    // coinciding with the seed is irrelevant.
    expect(premiumStopDollarToSend(SEEDED)).toBe(SEEDED);
  });

  it('sends nothing for a zero or negative stop, which the schema rejects with gt=0', () => {
    // round(premium x 0.60, 2) is 0.00 for a premium under about $0.0084, and
    // a `?? null` posted that 0 and 422'd the whole create with an opaque
    // Pydantic error instead of falling back to inherit-the-global.
    expect(premiumStopDollarToSend(0)).toBeNull();
    expect(premiumStopDollarToSend(-1)).toBeNull();
    expect(premiumStopDollarToSend(NaN)).toBeNull();
    expect(premiumStopDollarToSend(Infinity)).toBeNull();
  });

});

describe('spec §8 #8 — buildPaperPosition and positionFromOrder cannot disagree', () => {
  // The two send paths take their card from DIFFERENT sources: `effectiveCard`
  // on one side, `o.card` out of `resolveBasketCards` on the other. So "they
  // read the same map on adjacent lines" was never enough to make them agree,
  // and this was the mandated test that shipped missing.
  //
  // Under the old signature they could genuinely disagree, because the value
  // was `premiumStopDollarToSend(cache[key], card.exit.premiumStop)` -- and
  // `exit.premiumStop` is a property of the CARD OBJECT, not of the contract.
  // Two objects for one contract whose seeds had diverged (a mergePlan applied
  // to one and not the other) produced two different posted stops from the
  // same cache entry. Keying the decision on tracked touched-ness removes the
  // card from the expression entirely: the posted value is now a function of
  // the contract key alone, which is what makes the two paths agree.
  const KEY = 'AAPL|190|2026-05-16|C';

  /* ROUND 9 finding 8 -- THE AGREEMENT ITSELF IS NOT TESTED HERE ANY MORE, and
   * was not before either. What stood here called
   * `premiumStopDollarToSend(cache[KEY])` twice, named the two results
   * `fromBuildPaperPosition` and `fromPositionFromOrder`, and compared them to
   * each other. One pure function, one argument, two calls: a tautology under
   * every possible mutation, in the block whose header calls it "the mandated
   * test that shipped missing". Neither function it named was imported in this
   * file, let alone invoked.
   *
   * The real property spans two page-level code paths that take their card
   * from different sources, so it can only be tested at that level. It is, in
   * step-7-trade-card/__tests__/edited-fields-sync.test.tsx ("the two send
   * paths cannot disagree"), which drives Place Limit and a basket submit
   * through the real page and compares what each stored -- verified to fail
   * when only the basket path is reverted to the card's own invalidation.
   *
   * What CAN be tested here is the property that makes that agreement possible:
   * the posted value is a function of the cache entry alone. The card object is
   * not an input, so two card objects cannot pull it apart. */
  it('the posted value depends on the cache entry alone, not on any card', () => {
    // The old signature was `premiumStopDollarToSend(cache[key], card.exit.premiumStop)`,
    // and `exit.premiumStop` is a property of the CARD OBJECT rather than of the
    // contract -- so two objects for one contract whose seeds had diverged (a
    // mergePlan applied to one and not the other) produced two different posted
    // stops from the same cache entry. Keying on tracked touched-ness removed
    // the card from the expression; this pins that it stays removed.
    const cache: Record<string, number | null> = { [KEY]: 2.0 };
    expect(premiumStopDollarToSend(cache[KEY])).toBe(2.0);
    expect(premiumStopDollarToSend(null)).toBeNull();
    expect(premiumStopDollarToSend(undefined)).toBeNull();
  });
});

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

  it('the firing price of a server-derived fraction is at or below its threshold, and within a cent of it', () => {
    // The server stores `premiumStopDollar / entry_price`, so the threshold
    // almost never lands on a whole cent. Over a sweep of fills and typed
    // dollars, the printed firing price must be a price the engines fire at
    // (firing <= threshold, no slack) and the largest such cent
    // (threshold - firing <= 0.01). Flooring `t * 100` fails the first half.
    for (let entryCents = 101; entryCents <= 1400; entryCents += 13) {
      const entry = entryCents / 100;
      for (let dollarCents = 1; dollarCents < entryCents; dollarCents += 17) {
        const pct = (dollarCents / 100) / entry;
        const threshold = premiumStopThresholdPrice(entry, pct);
        const firing = premiumStopFiringPrice(entry, pct);
        expect(firing).toBeLessThanOrEqual(threshold);
        expect(threshold - firing).toBeLessThanOrEqual(0.01 + 1e-9);
      }
    }
    // The fixed pair from the typed-dollar story still holds: $3.12 on a fill.
    for (const entry of [cardMid, 4.00, 6.10]) {
      expect(premiumStopThresholdPrice(entry, dollarStop / entry)).toBeCloseTo(entry - dollarStop);
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

// ── The dollar bounds TradeCard derives from the band ───────────────────────

describe('premiumStopDollarBounds', () => {
  /* Round 1 of the follow-up audit. TradeCard converted the band to dollars
   * with `Math.round(mid * pct * 100) / 100`, which shaves up to half a cent
   * in EITHER direction -- so the card's own boundary values fell OUTSIDE the
   * band the drawer enforces, and a stop created at the card's minimum was one
   * the drawer refused. That is the disagreement the shared band exists to
   * end, surviving at the boundary for most mids.
   *
   * A SWEEP, not a pair. The lesson from round 12: the mirror case of a
   * rounding trap is reached by different inputs than the case that exposed
   * it, so a hand-picked example proves nothing about the other direction. */
  it('returns the TIGHTEST 2dp bounds inside the band, at every cent mid from $0.02 to $50', () => {
    /* EXACT CENTS, not "somewhere inside the band". Round 2 of the audit
     * showed the inside-the-band form had no teeth: a stub returning 60% of
     * the mid for both ends -- a helper that refuses every stop between 10%
     * and 60% -- passed it clean. Asserting the exact integer keeps only one
     * implementation, and it is the integer-cent arithmetic that catches the
     * float defect below. */
    const offenders: string[] = [];
    for (let cents = 2; cents <= 5000; cents++) {
      const { min, max } = premiumStopDollarBounds(cents / 100);
      const wantMin = Math.max(1, Math.ceil(cents * PREMIUM_STOP_MIN_PCT));
      const wantMax = Math.max(wantMin, Math.floor(cents * PREMIUM_STOP_MAX_PCT));
      if (Math.round(min * 100) !== wantMin) offenders.push(`min ${min} on ${cents}c, want ${wantMin}c`);
      if (Math.round(max * 100) !== wantMax) offenders.push(`max ${max} on ${cents}c, want ${wantMax}c`);
    }
    expect(offenders.slice(0, 10)).toEqual([]);
  });

  it('does not climb a cent on the round mids where the band is exactly expressible', () => {
    /* Round 2 finding 1, the defect the first version of this helper shipped
     * with. `Math.ceil(3.00 * 0.10 * 100)` is `Math.ceil(30.000000000000004)`
     * = 31, so a $3.00 mid demanded $0.31 -- 10.33% -- where $0.30 is exactly
     * 10% and PremiumStopEditor accepts it without complaint. It bit every
     * multiple of a dime: 172 mids between $0.02 and $50, i.e. precisely the
     * round numbers a user is most likely to be looking at. */
    expect(premiumStopDollarBounds(3.00).min).toBe(0.30);
    expect(premiumStopDollarBounds(0.30).min).toBe(0.03);
    expect(premiumStopDollarBounds(17.00).max).toBe(16.83);
    // The float form, restated so the regression is legible rather than
    // asserted about a helper that no longer contains it.
    expect(Math.ceil(3.00 * PREMIUM_STOP_MIN_PCT * 100)).toBe(31);
    expect(Math.ceil(Math.round(3.00 * 100) * PREMIUM_STOP_MIN_PCT)).toBe(30);
  });

  it('rounds INWARD, so the card cannot offer a dollar the drawer refuses', () => {
    // The two mids round 1 found. Round-to-nearest gave min 9.92% on $5.24 and
    // max 99.01% on $1.01 -- both outside the band the drawer enforces.
    expect(premiumStopDollarBounds(5.24).min).toBe(0.53);
    // floor(101 x 0.99) = 99 cents. Round-to-nearest gave $1.00 -- the whole
    // mid, as a "stop".
    expect(premiumStopDollarBounds(1.01).max).toBe(0.99);
    expect(Math.round(1.01 * PREMIUM_STOP_MAX_PCT * 100) / 100).toBe(1.00);
    expect(premiumStopDollarBounds(5.24).min / 5.24).toBeGreaterThanOrEqual(PREMIUM_STOP_MIN_PCT);
    expect(premiumStopDollarBounds(1.01).max / 1.01).toBeLessThanOrEqual(PREMIUM_STOP_MAX_PCT);
  });

  it('collapses to a single legal penny at a $0.01 mid, rather than inverting', () => {
    // The one mid where 2dp cannot express the band at all. `min > max` would
    // make the field impossible to satisfy. NOTE: this matches the pre-helper
    // arithmetic exactly -- it pins the degenerate case rather than changing
    // it, and that one dollar is 100% of the mid, which produces no stop at
    // all (round_2_batch_followups R2-6).
    const { min, max } = premiumStopDollarBounds(0.01);
    expect(min).toBe(0.01);
    expect(max).toBe(0.01);
  });
});

// ── pythonRound4: the 4dp rounding the backend stores (P2-22) ──────────────
describe('pythonRound4', () => {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const table: [number, number][] = require('./fixtures/python_round4.json');

  it('matches Python round(x, 4) for every row of the generated table', () => {
    expect(table.length).toBeGreaterThan(5000);
    const mismatches = table.filter(([x, py]) => pythonRound4(x) !== py);
    expect(mismatches).toEqual([]);
  });

  it('rounds near-halves by their exact value and exact ties to even', () => {
    expect(pythonRound4(0.00035)).toBe(0.0003);
    expect(pythonRound4(2.00015)).toBe(2.0002);
    expect(pythonRound4(1.03125)).toBe(1.0312);
    expect(pythonRound4(0.40625)).toBe(0.4062);
    expect(pythonRound4(2.53125)).toBe(2.5312);
    expect(pythonRound4(1.09375)).toBe(1.0938);
  });

  it('the table actually discriminates: Math.round(x*1e4)/1e4 and plain toFixed(4) both miss rows', () => {
    const naive = table.filter(([x, py]) => Math.round(x * 1e4) / 1e4 !== py).length;
    const toFixedOnly = table.filter(([x, py]) => Number(x.toFixed(4)) !== py).length;
    expect(naive).toBeGreaterThan(0);
    expect(toFixedOnly).toBeGreaterThan(0);
  });
});
