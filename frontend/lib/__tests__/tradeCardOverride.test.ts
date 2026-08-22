import {
  applyPickedContract, contractKeyFor, mergePlan, resolveBasketCards, withCachedEstimate,
  cacheStructural, cacheFirstPassage,
  type CachedFirstPassage, type CachedStructural,
} from '../tradeCardOverride';
import type { TradeCardData, OptionContract } from '@/types/domain';

function makeCard(overrides: Partial<TradeCardData> = {}): TradeCardData {
  return {
    symbol: 'AAPL',
    company: 'Apple Inc',
    price: 318.73,
    direction: 'Bullish',
    status: 'PASS',
    stockScore: 47,
    stockConfidence: 'CAUTION',
    stockBreakdown: { trend: 100, pullback: 45, trigger: 10, event: 5, volatility: 50 },
    contract: 'AAPL|330|2027-01-15|C',
    contractScore: 84,
    contractConfidence: 'PASS',
    contractBreakdown: { dteFit: 40, delta: 97, ivAttractiveness: 68, liquidity: 73, spread: 71 },
    contractDetails: {
      strike: 330, expiry: '2027-01-15', right: 'C', mid: 21.62,
      delta: 0.50, theta: -0.08, ivRank: 0, ivPercentile: 0, dte: 185,
    },
    entry: { limit: 19.98, maxFill: 20.58, orderType: 'Limit' },
    exit: { invalidation: 294.47, premiumStop: 11.99, timeStopDays: 74, target: 344.23, targets: [] },
    rrRatio: 1.1,
    rrModel: 'BS repriced (IV-derived)',
    finalStatus: 'PASS',
    ...overrides,
  };
}

function makeOption(overrides: Partial<OptionContract> = {}): OptionContract {
  return {
    id: 'AAPL|375|2027-01-15|C', symbol: 'AAPL', strike: 375, expiry: '2027-01-15', right: 'C',
    dte: 185, dteTotal: 185, price: 7.47, delta: 0.24, theta: -0.06, ivRank: 68, ivPercentile: 0,
    spread: 0.25, volume: 811, score: 60, contractConfidence: 'PASS',
    ...overrides,
  };
}

describe('applyPickedContract', () => {
  it('returns the card unchanged when nothing is picked', () => {
    const card = makeCard();
    expect(applyPickedContract(card, undefined)).toBe(card);
  });

  it('returns the card unchanged when the pick matches the auto-picked contract', () => {
    const card = makeCard();
    const picked = makeOption({ id: card.contract });
    expect(applyPickedContract(card, picked)).toBe(card);
  });

  it('swaps in the picked contract details and flags _userOverride', () => {
    const card = makeCard();
    const picked = makeOption();   // 375C — different from the card's auto-picked 330C
    const result = applyPickedContract(card, picked);

    expect(result._userOverride).toBe(true);
    expect(result.contract).toBe('AAPL|375|2027-01-15|C');
    expect(result.contractDetails?.strike).toBe(375);
    expect(result.contractDetails?.mid).toBe(7.47);
    // The bug this whole fix set out to kill: Entry/Exit must NOT be silently
    // carried over from the auto-pick — applyPickedContract deliberately leaves
    // them untouched (recomputation is a separate, async step), so a caller that
    // renders `result.entry`/`result.exit` directly without recomputing would
    // still show the WRONG numbers. This is exactly why resolveBasketCards below
    // withholds an overridden card until its plan is merged.
    expect(result.entry).toBe(card.entry);
  });

  it('carries the picked contract\'s own contractConfidence, not one re-derived from its score', () => {
    // score=60 would be 'PASS' under stock-scale thresholds (>=55) but the
    // contract-scale backend classification (>=65 PASS, >=45 CAUTION) says
    // CAUTION — proves this is a direct field copy, not statusForScore(score).
    const card = makeCard();
    const picked = makeOption({ score: 60, contractConfidence: 'CAUTION' });
    const result = applyPickedContract(card, picked);
    expect(result.contractConfidence).toBe('CAUTION');
  });
});

describe('contractKeyFor', () => {
  it('builds a stable symbol|strike|expiry|right key', () => {
    expect(contractKeyFor(makeCard())).toBe('AAPL|330|2027-01-15|C');
  });

  it('returns null when contract details are incomplete', () => {
    expect(contractKeyFor(makeCard({ contractDetails: undefined }))).toBeNull();
  });
});

describe('mergePlan', () => {
  it('overwrites entry/exit/rr from the plan, keeps everything else', () => {
    const card = applyPickedContract(makeCard(), makeOption());
    const plan = {
      entry: { limit: 7.47, maxFill: 7.69, orderType: 'Limit' as const },
      exit: { invalidation: 300.06, premiumStop: 4.48, timeStopDays: 74, target: 344.23, targets: [] },
      rrRatio: 1.71,
      rrModel: 'BS repriced (IV-derived)' as const,
    };
    const merged = mergePlan(card, plan);
    expect(merged.entry.limit).toBe(7.47);
    expect(merged.exit.premiumStop).toBe(4.48);   // matches the selected 375C's premium, not the auto-pick's
    expect(merged.contractDetails?.strike).toBe(375);   // unrelated fields preserved
  });
});

describe('resolveBasketCards', () => {
  const AAPL = makeCard({ symbol: 'AAPL', contract: 'AAPL|330|2027-01-15|C' });
  const MSFT = makeCard({ symbol: 'MSFT', contract: 'MSFT|400|2026-09-18|C', contractDetails: { ...AAPL.contractDetails!, strike: 400 } });
  const cardIndex = { AAPL, MSFT };

  it('includes a non-overridden basket card as-is', () => {
    const { cards, pending } = resolveBasketCards(['AAPL'], cardIndex, {}, {}, {});
    expect(pending).toBe(false);
    expect(cards).toHaveLength(1);
    expect(cards[0].contract).toBe('AAPL|330|2027-01-15|C');
  });

  it('THE FIX: an overridden basket contract with a ready plan carries the OVERRIDE\'s entry/exit, not the auto-pick\'s', () => {
    const picked = makeOption();   // AAPL 375C — overrides the auto-picked 330C
    const pickedContracts = { AAPL: picked.id };
    const contractsBySymbol = { AAPL: [picked] };
    const plan = {
      entry: { limit: 7.47, maxFill: 7.69, orderType: 'Limit' as const },
      exit: { invalidation: 300.06, premiumStop: 4.48, timeStopDays: 74, target: 344.23, targets: [] },
      rrRatio: 1.71,
      rrModel: 'BS repriced (IV-derived)' as const,
    };
    const plansBySymbol = { AAPL: { key: 'AAPL|375|2027-01-15|C', plan } };

    const { cards, pending } = resolveBasketCards(['AAPL'], cardIndex, pickedContracts, contractsBySymbol, plansBySymbol);

    expect(pending).toBe(false);
    expect(cards).toHaveLength(1);
    expect(cards[0].contract).toBe('AAPL|375|2027-01-15|C');   // the selected contract
    expect(cards[0].exit.premiumStop).toBe(4.48);              // its OWN recomputed premium stop
    expect(cards[0].exit.premiumStop).not.toBe(AAPL.exit.premiumStop);   // not the auto-pick's 11.99
  });

  it('THE BUG THIS PREVENTS: an overridden basket contract with NO ready plan is excluded and flips pending', () => {
    const picked = makeOption();
    const pickedContracts = { AAPL: picked.id };
    const contractsBySymbol = { AAPL: [picked] };

    // No plansBySymbol entry at all — recompute hasn't resolved yet.
    const { cards, pending } = resolveBasketCards(['AAPL'], cardIndex, pickedContracts, contractsBySymbol, {});

    expect(pending).toBe(true);
    expect(cards).toHaveLength(0);   // never silently falls back to the auto-pick's stale plan
  });

  it('excludes a plan cached for a DIFFERENT (stale) contract key and flips pending', () => {
    const picked = makeOption();
    const pickedContracts = { AAPL: picked.id };
    const contractsBySymbol = { AAPL: [picked] };
    // Cached plan is keyed for a different strike — e.g. the user changed their
    // pick again after the first recompute landed, but the second hasn't yet.
    const stalePlan = {
      entry: { limit: 1, maxFill: 1, orderType: 'Limit' as const },
      exit: { invalidation: 1, premiumStop: 1, timeStopDays: 1, target: 1, targets: [] },
      rrRatio: 1, rrModel: 'BS repriced (IV-derived)' as const,
    };
    const plansBySymbol = { AAPL: { key: 'AAPL|360|2027-01-15|C', plan: stalePlan } };

    const { cards, pending } = resolveBasketCards(['AAPL'], cardIndex, pickedContracts, contractsBySymbol, plansBySymbol);

    expect(pending).toBe(true);
    expect(cards).toHaveLength(0);
  });

  it('handles a mixed basket: one non-overridden, one overridden+ready, one overridden+pending', () => {
    const AMZN = makeCard({ symbol: 'AMZN', contract: 'AMZN|240|2026-07-24|C' });
    const mixedIndex = { ...cardIndex, AMZN };
    const picked = makeOption();   // overrides AAPL only
    const pickedContracts = { AAPL: picked.id };
    const contractsBySymbol = { AAPL: [picked] };
    const plan = {
      entry: { limit: 7.47, maxFill: 7.69, orderType: 'Limit' as const },
      exit: { invalidation: 300.06, premiumStop: 4.48, timeStopDays: 74, target: 344.23, targets: [] },
      rrRatio: 1.71, rrModel: 'BS repriced (IV-derived)' as const,
    };
    const plansBySymbol = { AAPL: { key: 'AAPL|375|2027-01-15|C', plan } };

    // MSFT overridden but no plan yet -> basket should be pending overall.
    const msftPicked = makeOption({ id: 'MSFT|410|2026-09-18|C', symbol: 'MSFT', strike: 410 });
    const { cards, pending } = resolveBasketCards(
      ['AAPL', 'MSFT', 'AMZN'],
      mixedIndex,
      { AAPL: picked.id, MSFT: msftPicked.id },
      { AAPL: [picked], MSFT: [msftPicked] },
      plansBySymbol,
    );

    expect(pending).toBe(true);   // MSFT's override has no plan yet
    const symbolsIncluded = cards.map((c) => c.symbol);
    expect(symbolsIncluded).toEqual(['AAPL', 'AMZN']);   // MSFT withheld, not silently sent stale
  });

  it('skips a basket symbol with no matching card', () => {
    const { cards, pending } = resolveBasketCards(['NOPE'], cardIndex, {}, {}, {});
    expect(cards).toHaveLength(0);
    expect(pending).toBe(false);
  });
});

describe('withCachedEstimate', () => {
  const estimate = {
    estimate: {
      targets: [{ pct: 0.2, stockPrice: 340, optionPrice: 25.94, probability: 0.62, expectedDays: 12 }],
      invalidation: { probability: 0.18, expectedDays: 40 },
    },
    context: { premium: 21.62, delta: 0.5, targetPct: { t1: 0.2, t2: 0.35, t3: 0.5 } },
  };
  const structural = {
    stop: { price: 294.5, source: 'order_block' as const, confidence: 71, distancePct: 7.6 },
    stockPrice: 318.9,
  };

  it('returns the same card reference when nothing is cached', () => {
    const card = makeCard();
    expect(withCachedEstimate(card, undefined, undefined)).toBe(card);
  });

  it('returns undefined for an undefined card', () => {
    expect(withCachedEstimate(undefined, estimate, structural)).toBeUndefined();
  });

  it('splices both cached results into exit without touching the rest of exit', () => {
    const card = makeCard();
    const out = withCachedEstimate(card, estimate, structural)!;
    expect(out.exit.firstPassage).toBe(estimate.estimate);
    expect(out.exit.firstPassageContext).toBe(estimate.context);
    expect(out.exit.structuralStop).toBe(structural.stop);
    expect(out.exit.structuralStopStockPrice).toBe(318.9);
    // Untouched plan fields.
    expect(out.exit.invalidation).toBe(card.exit.invalidation);
    expect(out.exit.premiumStop).toBe(card.exit.premiumStop);
    expect(out.entry).toBe(card.entry);
    // The input card is never mutated.
    expect(card.exit.firstPassage).toBeUndefined();
  });

  it('splices only the half that is cached', () => {
    const out = withCachedEstimate(makeCard(), undefined, structural)!;
    expect(out.exit.structuralStop).toBe(structural.stop);
    expect(out.exit.firstPassage).toBeUndefined();
    expect(out.exit.firstPassageContext).toBeUndefined();
  });

  it('preserves a cached "checked, nothing found" structural result as null, not absent', () => {
    const out = withCachedEstimate(makeCard(), undefined, { stop: null, stockPrice: 318.9 })!;
    expect(out.exit.structuralStop).toBeNull();
    expect(out.exit.structuralStopStockPrice).toBe(318.9);
  });

  it('preserves _userOverride on an overridden card', () => {
    const overridden = { ...makeCard(), _userOverride: true };
    const out = withCachedEstimate(overridden, estimate, undefined)!;
    expect(out._userOverride).toBe(true);
  });

  it('splices a null context as null rather than inventing a targetPct', () => {
    // TradeCard falls back to the settings default when firstPassageContext is
    // absent; it must see an explicit null here, not a fabricated trio.
    const out = withCachedEstimate(makeCard(), { estimate: estimate.estimate, context: null }, undefined)!;
    expect(out.exit.firstPassage).toBe(estimate.estimate);
    expect(out.exit.firstPassageContext).toBeNull();
  });
});

describe('cacheStructural', () => {
  const stopA = { price: 294.5, source: 'order_block' as const, confidence: 71, distancePct: 7.6 };

  it('ignores the `undefined` reset sentinel and returns the identical prev', () => {
    const prev: Record<string, CachedStructural> = { AAPL: { stop: stopA, stockPrice: 318.9 } };
    // This is the reset TradeCard fires on every contract switch and at the
    // start of every re-check. If it were written through, navigating away
    // from a checked candidate would wipe its cached level.
    expect(cacheStructural(prev, 'AAPL', undefined, null)).toBe(prev);
  });

  it('leaves a previously cached level intact for an in-flight (not-yet-resolved) re-check', () => {
    // checkStructure sets stop=undefined before fetching (still in flight, no
    // answer yet) — that write must not disturb the cache. Once the fetch
    // actually resolves (success OR failure) it writes something else: a real
    // value on success, or an explicit `null` on failure (see the dedicated
    // "a failed re-check" test below) — `undefined` is never checkStructure's
    // LAST word on a request that has actually completed.
    const prev: Record<string, CachedStructural> = { AAPL: { stop: stopA, stockPrice: 318.9 } };
    const after = cacheStructural(prev, 'AAPL', undefined, null);
    expect(after.AAPL).toEqual({ stop: stopA, stockPrice: 318.9 });
  });

  it('caches a "checked, nothing found" answer — null is a result, not a sentinel', () => {
    const out = cacheStructural({}, 'AAPL', null, 318.9);
    expect(out.AAPL).toEqual({ stop: null, stockPrice: 318.9 });
  });

  it('writes a first result for a symbol', () => {
    const out = cacheStructural({}, 'AAPL', stopA, 318.9);
    expect(out.AAPL!.stop).toBe(stopA);
    expect(out.AAPL!.stockPrice).toBe(318.9);
  });

  it('returns the IDENTICAL prev when both halves are unchanged (render-loop guard)', () => {
    // This is the post-restore fire: the page splices the very same objects back
    // in, TradeCard's effect surfaces them again, and this must be a true no-op
    // or the parent re-renders -> new closure -> sync effect -> ... unbounded.
    const prev: Record<string, CachedStructural> = { AAPL: { stop: stopA, stockPrice: 318.9 } };
    expect(cacheStructural(prev, 'AAPL', stopA, 318.9)).toBe(prev);
  });

  it('does NOT bail out when only the stock price moved', () => {
    const prev: Record<string, CachedStructural> = { AAPL: { stop: stopA, stockPrice: 318.9 } };
    const out = cacheStructural(prev, 'AAPL', stopA, 320.1);
    expect(out).not.toBe(prev);
    expect(out.AAPL!.stockPrice).toBe(320.1);
  });

  it('overwrites with a re-check that returned an equal-valued but new object', () => {
    const prev: Record<string, CachedStructural> = { AAPL: { stop: stopA, stockPrice: 318.9 } };
    const stopA2 = { ...stopA };
    const out = cacheStructural(prev, 'AAPL', stopA2, 318.9);
    expect(out).not.toBe(prev);
    expect(out.AAPL!.stop).toBe(stopA2);
  });

  it('never mutates prev and never disturbs another symbol', () => {
    const prev: Record<string, CachedStructural> = { MSFT: { stop: null, stockPrice: 400 } };
    const out = cacheStructural(prev, 'AAPL', stopA, 318.9);
    expect(prev.AAPL).toBeUndefined();
    expect(out.MSFT).toBe(prev.MSFT);
  });
});

describe('cacheFirstPassage', () => {
  const estimateA = {
    targets: [{ pct: 0.2, stockPrice: 340, optionPrice: 25.94, probability: 0.62, expectedDays: 12 }],
    invalidation: { probability: 0.18, expectedDays: 40 },
  };
  const contextA = { premium: 21.62, delta: 0.5, targetPct: { t1: 0.2, t2: 0.35, t3: 0.5 } };
  const KEY = 'AAPL|340|2026-01-16|C';

  it('ignores the `undefined` reset sentinel and returns the identical prev', () => {
    const prev: Record<string, CachedFirstPassage> = { [KEY]: { estimate: estimateA, context: contextA } };
    expect(cacheFirstPassage(prev, KEY, undefined, null)).toBe(prev);
  });

  it('writes a `null` estimate as a real overwrite — a failed re-estimate must not leave a stale one cached', () => {
    // Mirrors cacheStructural's undefined-vs-null distinction: `undefined`
    // (the previous test) is a "don't touch, still in flight" sentinel;
    // `null` is TradeCard's explicit "this refresh determined the previous
    // value can no longer be vouched for" signal, and must actually clear
    // the stale entry rather than being silently ignored like `undefined` —
    // otherwise the stale estimateA/contextA pair rides along under
    // whatever the structural cache resolves to on a later navigation.
    const prev: Record<string, CachedFirstPassage> = { [KEY]: { estimate: estimateA, context: contextA } };
    const out = cacheFirstPassage(prev, KEY, null, null);
    expect(out[KEY]).toEqual({ estimate: null, context: null });
  });

  it('ignores a null key (card with no resolvable contract) rather than keying on "null"', () => {
    const out = cacheFirstPassage({}, null, estimateA, contextA);
    expect(Object.keys(out)).toHaveLength(0);
  });

  it('writes the estimate and its context together, under the contract key', () => {
    const out = cacheFirstPassage({}, KEY, estimateA, contextA);
    expect(out[KEY]!.estimate).toBe(estimateA);
    // The context MUST travel with the estimate: TradeCard's structuralRR needs
    // firstPassageContext.premium/.delta, and targetPct rides inside it so a
    // restored estimate's rows and its % inputs can never disagree.
    expect(out[KEY]!.context).toBe(contextA);
  });

  it('returns the IDENTICAL prev when both halves are unchanged (render-loop guard)', () => {
    const prev: Record<string, CachedFirstPassage> = { [KEY]: { estimate: estimateA, context: contextA } };
    expect(cacheFirstPassage(prev, KEY, estimateA, contextA)).toBe(prev);
  });

  it('does NOT bail out when only the context changed', () => {
    // The self-correcting path: if the estimate and its context ever landed in
    // separate commits, the second fire completes the half-written entry.
    const prev: Record<string, CachedFirstPassage> = { [KEY]: { estimate: estimateA, context: null } };
    const out = cacheFirstPassage(prev, KEY, estimateA, contextA);
    expect(out).not.toBe(prev);
    expect(out[KEY]!.context).toBe(contextA);
  });

  it('overwrites that contract slot on a fresh estimate', () => {
    const prev: Record<string, CachedFirstPassage> = { [KEY]: { estimate: estimateA, context: contextA } };
    const estimateB = { ...estimateA, invalidation: { probability: 0.4, expectedDays: 9 } };
    const contextB = { ...contextA, targetPct: { t1: 0.1, t2: 0.35, t3: 0.5 } };
    const out = cacheFirstPassage(prev, KEY, estimateB, contextB);
    expect(out[KEY]!.estimate).toBe(estimateB);
    expect(out[KEY]!.context).toBe(contextB);
  });

  it('never mutates prev and never disturbs another contract', () => {
    const other = 'MSFT|300|2026-01-16|C';
    const prev: Record<string, CachedFirstPassage> = { [other]: { estimate: estimateA, context: contextA } };
    const out = cacheFirstPassage(prev, KEY, estimateA, contextA);
    expect(prev[KEY]).toBeUndefined();
    expect(out[other]).toBe(prev[other]);
  });
});
