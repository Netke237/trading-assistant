import { applyPickedContract, contractKeyFor, mergePlan, resolveBasketCards } from '../tradeCardOverride';
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
    spread: 0.25, volume: 811, score: 60,
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
