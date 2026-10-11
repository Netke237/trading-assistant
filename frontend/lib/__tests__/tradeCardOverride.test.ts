import {
  applyPickedContract, contractKeyFor, mergePlan, resolveBasketCards, withCachedEstimate,
  cacheStructural, cacheFirstPassage, cacheExitPlan,
  scoreEvidenceFor,
  type CachedFirstPassage, type CachedStructural, type CachedExitPlan,
} from '../tradeCardOverride';
import type { TradeCardData, OptionContract, ExitPlan, StockExplanation, ContractExplanation } from '@/types/domain';
import { useScanStore } from '../scanStore';

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

function stockEvidence(card: TradeCardData): StockExplanation {
  return {
    version: 1, symbol: card.symbol, direction: card.direction, horizon: 'Position',
    scoring_mode: 'options', iv_basis: 'absolute', evaluated_at: '2026-10-04T00:00:00Z',
    score: card.stockScore, status: card.stockConfidence, raw_status: card.stockConfidence,
    unrounded_score: card.stockScore, rounding: 'python_round_ties_to_even',
    pass_threshold: 55, caution_threshold: 35, weights: {}, components: {}, caps: [], gate_config: {},
  };
}

function contractEvidence(id: string, score: number, status: ContractExplanation['status']): ContractExplanation {
  return {
    version: 1, contract_id: id, evaluated_at: '2026-10-04T00:00:00Z', outcome: 'aggregate',
    score, status, unrounded_score: score, rounded_score: score, pass_threshold: 65,
    caution_threshold: 45, weights: {}, components: {}, largest_losses: [], blockers: [],
    reject_reasons: [], soft_flags: [], soft_fail_count: 0, max_soft_fail_count: 3,
  };
}

describe('score evidence identity and persistence', () => {
  const absent = { state: 'not_captured', message: 'Not captured — re-run scan' };

  it.each([undefined, null])('marks legacy evidence %s explicitly without changing any numbers', (missing) => {
    const card = makeCard({ stockExplanation: missing, contractExplanation: missing });
    const original = JSON.stringify(card);
    expect(scoreEvidenceFor(card)).toEqual({ stock: absent, contract: absent });
    expect(JSON.stringify(card)).toBe(original);
  });

  it('keeps each snapshot paired through override, recompute and basket construction', () => {
    const card = makeCard();
    card.stockExplanation = stockEvidence(card);
    card.contractExplanation = contractEvidence(card.contract, card.contractScore, card.contractConfidence);
    const picked = makeOption();
    picked.explanation = contractEvidence(picked.id, picked.score, picked.contractConfidence);
    const resolved = applyPickedContract(card, picked);
    const plan = { entry: { ...card.entry, limit: picked.price }, exit: card.exit,
      rrRatio: 2.1, rrModel: card.rrModel };
    const merged = mergePlan(resolved, plan);
    expect(merged.stockExplanation).toBe(card.stockExplanation);
    expect(merged.contractExplanation).toBe(picked.explanation);
    expect(scoreEvidenceFor(merged)).toEqual({
      stock: { state: 'captured', explanation: card.stockExplanation },
      contract: { state: 'captured', explanation: picked.explanation },
    });
    const key = contractKeyFor(resolved)!;
    const basket = resolveBasketCards([card.symbol], { [card.symbol]: card },
      { [card.symbol]: picked.id }, { [card.symbol]: [picked] },
      { [card.symbol]: { key, plan } });
    expect(basket.pending).toBe(false);
    expect(basket.cards[0].contractExplanation).toBe(picked.explanation);
    expect(basket.cards[0].stockExplanation).toBe(card.stockExplanation);
    const legacyPick = applyPickedContract(card, makeOption());
    expect(legacyPick.contractExplanation).toBeUndefined();
    expect(scoreEvidenceFor(mergePlan(legacyPick, plan)).contract).toEqual(absent);
    expect(scoreEvidenceFor(card).contract.state).toBe('captured'); // switching back restores A's evidence
  });

  it('refuses evidence for another result or contract without replacing scores', () => {
    const card = makeCard();
    card.stockExplanation = { ...stockEvidence(card), score: card.stockScore + 1 };
    card.contractExplanation = contractEvidence('OTHER|375|2027-01-15|C', card.contractScore, card.contractConfidence);
    expect(scoreEvidenceFor(card)).toEqual({ stock: absent, contract: absent });
    expect(card.stockScore).toBe(47);
    expect(card.contractScore).toBe(84);
  });

  it.each([true, false])('round-trips captured=%s evidence through actual store storage and hydration', async (captured) => {
    const previous = useScanStore.getState();
    const card = makeCard();
    if (captured) {
      card.stockExplanation = stockEvidence(card);
      card.contractExplanation = contractEvidence(card.contract, card.contractScore, card.contractConfidence);
    }
    const result = { scan_id: 'evidence-scan', timestamp: '2026-10-04T00:00:00Z', candidates: [card], rejected: [] };
    try {
      useScanStore.getState().setScanResult(result);
      useScanStore.getState().setPickedContract(card.symbol, 'AAPL|375|2027-01-15|C');
      const saved = localStorage.getItem('bamendjou-scan-store')!;
      expect(JSON.parse(saved).state.scanResult).toEqual(result);
      useScanStore.setState({ scanResult: null, pickedContracts: {} });
      localStorage.setItem('bamendjou-scan-store', saved);
      await useScanStore.persist.rehydrate();
      expect(useScanStore.getState().scanResult).toEqual(result);
      expect(useScanStore.getState().pickedContracts[card.symbol]).toBe('AAPL|375|2027-01-15|C');
      const restored = useScanStore.getState().scanResult!.candidates[0];
      expect(scoreEvidenceFor(restored)).toEqual(scoreEvidenceFor(card));
      const legacyPick = applyPickedContract(restored, makeOption());
      expect(scoreEvidenceFor(legacyPick).contract).toEqual(absent);
      if (!captured) expect(restored.stockExplanation).toBeUndefined();
    } finally {
      useScanStore.setState(previous, true);
    }
  });
});

describe('applyPickedContract', () => {
  it('returns the card unchanged when nothing is picked', () => {
    const card = makeCard();
    expect(applyPickedContract(card, undefined)).toBe(card);
  });

  it('preserves the card data and copies liveness when the pick matches the auto-picked contract', () => {
    const card = makeCard();
    const picked = makeOption({ id: card.contract });
    expect(applyPickedContract(card, picked)).toEqual({ ...card, noLiveQuote: false });
    expect(applyPickedContract(card, { ...picked, noLiveQuote: true })).toEqual({ ...card, noLiveQuote: true });
  });

  it('carries the picked contract\'s BREAKDOWN across, not the auto-picked one\'s', () => {
    // ROUND 6 finding 8. The card used to show the picked contract's composite
    // score over the auto-picked contract's five component scores and detail
    // lines. Phase A made ivDetailText quantitative, so the two panels asserted
    // a specific IV percentage for a strike the user was not looking at.
    const card = makeCard();
    const picked = makeOption({
      breakdown: {
        dteFit: 88, delta: 55, ivAttractiveness: 30, liquidity: 91, spread: 44,
        ivDetail: { iv_rank: 68, iv_basis: 'rank', preferred_max: 55 },
      },
    });
    const result = applyPickedContract(card, picked);
    expect(result.contractBreakdown.ivAttractiveness).toBe(30);   // picked, not 68
    expect(result.contractBreakdown.dteFit).toBe(88);             // picked, not 40
    expect(result.contractBreakdown.ivDetail?.iv_rank).toBe(68);
    // and the composite score it sits under is the picked contract's too
    expect(result.contractScore).toBe(picked.score);
  });

  it('keeps the existing breakdown when the picked row carries none', () => {
    // Older cached /api/contracts responses and chain rows that came from the
    // scan have no breakdown. Falling back is the only option that satisfies the
    // required field; nothing is invented.
    const card = makeCard();
    const result = applyPickedContract(card, makeOption());
    expect(result.contractBreakdown).toEqual(card.contractBreakdown);
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

  // PIECE 3. `exit` is replaced WHOLESALE, and the stop is a STOCK level:
  // which contract is being traded has no bearing on where structure sits, so
  // a contract override must not move it.
  describe('the stock stop across a contract override', () => {
    const FINAL_STOP = {
      price: 169.0, source: 'final_stop' as const, stopSource: 'atr_widened' as const,
      structuralSource: 'swing_low' as const, structuralPrice: 182.0, atrFloorPrice: 169.0,
      distanceDollar: 13.0, atr: 8.0, computedAt: '2026-09-09T12:00:00+00:00',
    };
    const withStop = () => applyPickedContract(
      makeCard({ exit: { invalidation: 169.0, premiumStop: 11.99, timeStopDays: 74, target: 344.23, targets: [], finalStop: FINAL_STOP } }),
      makeOption(),
    );
    const planWith = (exit: Partial<TradeCardData['exit']>) => ({
      entry: { limit: 7.47, maxFill: 7.69, orderType: 'Limit' as const },
      exit: { invalidation: 169.0, premiumStop: 4.48, timeStopDays: 74, target: 344.23, targets: [], ...exit },
      rrRatio: 1.71,
      rrModel: 'BS repriced (IV-derived)' as const,
    });

    it('takes the block the endpoint echoed back', () => {
      const merged = mergePlan(withStop(), planWith({ finalStop: FINAL_STOP }));
      expect(merged.exit.finalStop).toEqual(FINAL_STOP);
      expect(merged.exit.invalidation).toBe(169.0);
    });

    it('KEEPS the card\'s block when the response carries none', () => {
      // Defence in depth, per the plan's part 3 — what a stale client, a proxy
      // that dropped the field, or a rolled-back backend looks like. Without
      // it the wholesale `exit` replacement drops the stop back to a flat
      // percentage for exactly the cards a user hand-picked a contract on.
      const merged = mergePlan(withStop(), planWith({ invalidation: 309.17 }));
      expect(merged.exit.finalStop).toEqual(FINAL_STOP);
      // The INVALIDATION comes back with it. Keeping the block while letting a
      // flat-fallback number through would print a structural provenance row
      // above a stop it does not describe.
      expect(merged.exit.invalidation).toBe(169.0);
    });

    it('lets the plan win when BOTH carry a block, rather than mixing them', () => {
      // A mismatched pair is worse than either half: the plan's own
      // `invalidation` was computed against the plan's block.
      const moved = { ...FINAL_STOP, price: 171.5, atrFloorPrice: 171.5 };
      const merged = mergePlan(withStop(), planWith({ invalidation: 171.5, finalStop: moved }));
      expect(merged.exit.finalStop).toEqual(moved);
      expect(merged.exit.invalidation).toBe(171.5);
    });

    it('does not invent a block for a card that never had one', () => {
      const merged = mergePlan(applyPickedContract(makeCard(), makeOption()), planWith({ invalidation: 309.17 }));
      expect(merged.exit.finalStop ?? null).toBeNull();
      expect(merged.exit.invalidation).toBe(309.17);
    });
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

  describe('exit-plan splicing (the SendToBrokerDialog max-loss gate integration bug)', () => {
    // Without this splice, a raw scan candidate never carries exit.exitPlan on
    // its own — only a user's "Compute Exit Plan" click populates it, cached
    // separately by contract key — so checkTradeRisk's max_loss_per_trade_exceeded
    // gate silently never fires for the basket "Send to broker" path even when
    // the user has looked at and pinned a candidate whose exit plan shows a
    // loss over the configured limit.
    const plan: ExitPlan = {
      computedAt: '2026-08-27T00:00:00.000Z',
      stop: {
        price: 294.5, source: 'structural', contractPrice: 11.2, rrModel: 'Heston repriced',
        structuralSource: 'order_block', structuralConfidence: 71,
        structuralPrice: 294.5, atrFloorPrice: 288.0, distanceDollar: 6.5,
      },
      targets: [],
      atr: 5.4,
    };

    it('splices a cached exit plan into a non-overridden basket card', () => {
      const exitPlanByContract: Record<string, CachedExitPlan> = { 'AAPL|330|2027-01-15|C': { plan } };

      const { cards } = resolveBasketCards(['AAPL'], cardIndex, {}, {}, {}, exitPlanByContract);

      expect(cards).toHaveLength(1);
      expect(cards[0].exit.exitPlan).toBe(plan);
    });

    it('splices the exit plan for the OVERRIDDEN contract, not the auto-pick, and after mergePlan (which replaces exit wholesale)', () => {
      const picked = makeOption();   // AAPL 375C — overrides the auto-picked 330C
      const pickedContracts = { AAPL: picked.id };
      const contractsBySymbol = { AAPL: [picked] };
      const recomputedPlan = {
        entry: { limit: 7.47, maxFill: 7.69, orderType: 'Limit' as const },
        exit: { invalidation: 300.06, premiumStop: 4.48, timeStopDays: 74, target: 344.23, targets: [] },
        rrRatio: 1.71,
        rrModel: 'BS repriced (IV-derived)' as const,
      };
      const plansBySymbol = { AAPL: { key: 'AAPL|375|2027-01-15|C', plan: recomputedPlan } };
      // Keyed for the OVERRIDDEN contract (375C) — the auto-pick's key (330C)
      // must NOT be the one that lands here.
      const exitPlanByContract: Record<string, CachedExitPlan> = { 'AAPL|375|2027-01-15|C': { plan } };

      const { cards } = resolveBasketCards(['AAPL'], cardIndex, pickedContracts, contractsBySymbol, plansBySymbol, exitPlanByContract);

      expect(cards).toHaveLength(1);
      expect(cards[0].exit.exitPlan).toBe(plan);
      expect(cards[0].exit.premiumStop).toBe(4.48);   // mergePlan's fields survived the splice too
    });

    it('leaves exit.exitPlan absent when nothing is cached for that contract (no exitPlanByContract arg — back-compat default)', () => {
      const { cards } = resolveBasketCards(['AAPL'], cardIndex, {}, {}, {});
      expect(cards[0].exit.exitPlan).toBeUndefined();
    });

    it('does not splice a plan cached under a DIFFERENT contract key', () => {
      const exitPlanByContract: Record<string, CachedExitPlan> = { 'MSFT|400|2026-09-18|C': { plan } };

      const { cards } = resolveBasketCards(['AAPL'], cardIndex, {}, {}, {}, exitPlanByContract);

      expect(cards[0].exit.exitPlan).toBeUndefined();
    });
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

  const exitPlan = {
    plan: {
      computedAt: '2026-08-26T12:00:00.000Z',
      stop: {
        price: 294.5, source: 'structural' as const, contractPrice: 11.2, rrModel: 'Heston repriced' as const,
        structuralSource: 'order_block' as const, structuralConfidence: 71,
        structuralPrice: 294.5, atrFloorPrice: 288.0, distanceDollar: 6.5,
      },
      targets: [],
      atr: 5.4,
    },
  };

  it('splices a cached exit plan into exit.exitPlan without disturbing the other two caches', () => {
    const out = withCachedEstimate(makeCard(), estimate, structural, exitPlan)!;
    expect(out.exit.exitPlan).toBe(exitPlan.plan);
    expect(out.exit.firstPassage).toBe(estimate.estimate);
    expect(out.exit.structuralStop).toBe(structural.stop);
  });

  it('returns the same card reference when only exitPlan is undefined too', () => {
    const card = makeCard();
    expect(withCachedEstimate(card, undefined, undefined, undefined)).toBe(card);
  });

  it('preserves a cached "compute failed" exit plan as null, not absent', () => {
    const out = withCachedEstimate(makeCard(), undefined, undefined, { plan: null })!;
    expect(out.exit.exitPlan).toBeNull();
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

describe('cacheExitPlan', () => {
  const planA: ExitPlan = {
    computedAt: '2026-08-26T12:00:00.000Z',
    stop: {
      price: 294.5, source: 'structural', contractPrice: 11.2, rrModel: 'Heston repriced',
      structuralSource: 'order_block', structuralConfidence: 71,
      structuralPrice: 294.5, atrFloorPrice: 288.0, distanceDollar: 6.5,
    },
    targets: [
      {
        rrRatio: 2.0, arithmeticPrice: 340.0, price: 340.0, tpSource: 'arithmetic', structuralPrice: null,
        contractPrice: 25.94, rrModel: 'Heston repriced', probability: 0.62, expectedDays: 12, qualityGood: true,
        qualityReasons: [], distanceDollar: null, toleranceDollar: 1.6,
      },
    ],
    atr: 5.4,
  };
  const KEY = 'AAPL|340|2026-01-16|C';

  it('ignores the `undefined` reset sentinel and returns the identical prev', () => {
    const prev: Record<string, CachedExitPlan> = { [KEY]: { plan: planA } };
    expect(cacheExitPlan(prev, KEY, undefined)).toBe(prev);
  });

  it('writes a `null` plan as a real overwrite — a failed re-compute must not leave a stale one cached', () => {
    const prev: Record<string, CachedExitPlan> = { [KEY]: { plan: planA } };
    const out = cacheExitPlan(prev, KEY, null);
    expect(out[KEY]).toEqual({ plan: null });
  });

  it('ignores a null key (card with no resolvable contract) rather than keying on "null"', () => {
    const out = cacheExitPlan({}, null, planA);
    expect(Object.keys(out)).toHaveLength(0);
  });

  it('writes the plan under the contract key', () => {
    const out = cacheExitPlan({}, KEY, planA);
    expect(out[KEY]!.plan).toBe(planA);
  });

  it('returns the IDENTICAL prev when unchanged (render-loop guard)', () => {
    const prev: Record<string, CachedExitPlan> = { [KEY]: { plan: planA } };
    expect(cacheExitPlan(prev, KEY, planA)).toBe(prev);
  });

  it('overwrites that contract slot on a fresh plan', () => {
    const prev: Record<string, CachedExitPlan> = { [KEY]: { plan: planA } };
    const planB: ExitPlan = { ...planA, atr: 6.1 };
    const out = cacheExitPlan(prev, KEY, planB);
    expect(out[KEY]!.plan).toBe(planB);
  });

  it('never mutates prev and never disturbs another contract', () => {
    const other = 'MSFT|300|2026-01-16|C';
    const prev: Record<string, CachedExitPlan> = { [other]: { plan: planA } };
    const out = cacheExitPlan(prev, KEY, planA);
    expect(prev[KEY]).toBeUndefined();
    expect(out[other]).toBe(prev[other]);
  });
});
