import {
  buildSubmissionDraft, stampPosition, orderAtQuantity, targetBasisOf,
  submissionToken, isCurrentSubmission, submissionDifferences,
  type SubmissionInputs,
} from '@/lib/submissionDraft';
import type { ExitPlan, MethodPick, TradeCardData } from '@/types/domain';

/* #581 — the shared immutable submission draft. Payload BYTE parity with the
 * pre-extraction builders is pinned by the Step 7 golden suite; this file pins
 * the draft's own contract: stamping, immutability, the premium-stop basis it
 * reports, the target-alert basis it describes from the request, and the
 * review-to-submission parity contract #582/#583 reuse. */

const card = (o: Partial<TradeCardData> = {}): TradeCardData => ({
  symbol: 'AAA', company: 'AAA Inc.', price: 150, direction: 'Bullish', status: 'PASS',
  stockScore: 80, stockConfidence: 'PASS',
  stockBreakdown: { trend: 80, pullback: 80, trigger: 80, event: 80, volatility: 80 },
  contract: 'AAA 150C 05/15', contractScore: 70, contractConfidence: 'PASS',
  contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 60 },
  contractDetails: { strike: 150, expiry: '2026-05-15', right: 'C', mid: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 },
  entry: { limit: 2.5, maxFill: 2.63, orderType: 'Limit' },
  exit: { invalidation: 140, premiumStop: 1.5, timeStopDays: 10, target: 160, targets: [], finalStop: { price: 135 } as any },
  rrRatio: 2, rrModel: 'Heston repriced', finalStatus: 'PASS',
  ...o,
});

const plan = (rows: Array<[number, number]>, stop = 135): ExitPlan => ({
  computedAt: '2026-09-14T10:00:00Z',
  stop: { price: stop, source: 'atr_widened', contractPrice: 1, rrModel: 'Heston repriced', structuralSource: null, structuralConfidence: null, structuralPrice: null, atrFloorPrice: stop, distanceDollar: null } as any,
  targets: rows.map(([rrRatio, price]) => ({ rrRatio, price, arithmeticPrice: price, tpSource: 'arithmetic', structuralPrice: null, contractPrice: 5, rrModel: 'Heston repriced', probability: 0.4, expectedDays: 9, qualityGood: true, qualityReasons: [], distanceDollar: null, toleranceDollar: 1 })) as any,
  atr: 4,
} as ExitPlan);

const pick = (o: Partial<MethodPick> = {}): MethodPick => ({
  method: 'ladder', rowStockPrice: 160, rowOptionPrice: null, stopBasis: 'stock', pickedAt: '2026-09-14T10:00:00.000Z', ...o,
});

const inputs = (o: Partial<SubmissionInputs> = {}): SubmissionInputs => ({
  card: card(), contracts: 2, livePrice: 4, invalidation: 140, invalidationIsUserSet: false,
  entryLimit: 2.5, premiumStopDollar: null, structuralStop: null, exitPlan: null, maxLossOverride: null,
  pick: pick(), ...o,
});
const OPTS = { broker: 'ibkr_paper', globalPremiumStopPct: 0.6 };
const STAMPS = { entryDate: '2026-09-14', orderedAt: '2026-09-14T10:00:00', recId: 'REC-1' };

describe('submission draft — the request object both review and submission consume', () => {
  it('stamping keeps every request field and the old builders\' key order', () => {
    const d = buildSubmissionDraft(inputs(), OPTS);
    const tracked = stampPosition(d.tracking, STAMPS);
    expect(Object.keys(tracked)).toEqual(Object.keys(d.tracking));
    expect(Object.keys(tracked).slice(0, 5)).toEqual(['symbol', 'contract', 'direction', 'entryDate', 'expiry']);
    expect(Object.keys(tracked).at(-1)).toBe('scanStockPrice');
    expect(tracked).toMatchObject({ recId: 'REC-1', entryDate: '2026-09-14', orderedAt: '2026-09-14T10:00:00', contract: 'AAA 150C 05/15', source: 'manual' });
    const directPos = stampPosition(d.direct!.limit.position, STAMPS);
    expect(directPos).toMatchObject({ contract: 'AAA|150|2026-05-15|C', source: 'paper', sourceLabel: 'IBKR Paper — Limit (ID: pending)' });
    expect(orderAtQuantity(d.direct!.limit.order, 1)).toEqual({
      broker: 'ibkr_paper', symbol: 'AAA', option_symbol: 'AAA|150|2026-05-15|C', action: 'BUY', effect: 'OPEN',
      quantity: 1, order_type: 'LMT', limit_price: 2.5, tif: 'DAY',
    });
    expect(d.direct!.market.order.limit_price).toBeNull();
  });

  it('is immutable: a consumer cannot alter the reviewed request', () => {
    const d = buildSubmissionDraft(inputs(), OPTS);
    expect(Object.isFrozen(d)).toBe(true);
    expect(Object.isFrozen(d.tracking)).toBe(true);
    expect(Object.isFrozen(d.direct!.limit.order)).toBe(true);
    expect(() => { (d.tracking as any).stop = 1; }).toThrow();
  });

  it('no broker selected: direct routes are absent, tracking is unchanged', () => {
    const d = buildSubmissionDraft(inputs(), { ...OPTS, broker: null });
    expect(d.direct).toBeNull();
    expect(d.tracking.contracts).toBe(2);
  });

  it('Tastytrade paper reports its existing market-order refusal on the market route', () => {
    const d = buildSubmissionDraft(inputs(), { ...OPTS, broker: 'tastytrade_paper' });
    expect(d.direct!.market.blocked).toMatch(/limit orders only/);
    expect(d.direct!.limit.blocked).toBeNull();
  });
});

describe('actual stops versus calculation stops', () => {
  it('the actual Exit Plan stop is sent; a calculation stop never replaces it', () => {
    const d = buildSubmissionDraft(inputs({ exitPlan: plan([[2, 170], [3, 185]], 131) }), OPTS);
    expect(d.stops.stockStop).toBe(140);
    expect(d.tracking.stop).toBe(140);
    expect(d.direct!.limit.position.stop).toBe(140);
    expect(d.tracking.exitPlan?.stop.price).toBe(131); // attached as a record, not applied
  });

  it('a calculation-only change keeps parity; an actual-setting change breaks it by name', () => {
    const reviewed = buildSubmissionDraft(inputs(), OPTS);
    // Card-level calculation stop (scan final stop) moved; nothing actual moved.
    const calcMoved = buildSubmissionDraft(inputs({ card: card({ exit: { ...card().exit, finalStop: { price: 120 } as any } }) }), OPTS);
    expect(submissionDifferences(reviewed, calcMoved)).toEqual([]);
    expect(calcMoved.fingerprint).toBe(reviewed.fingerprint);
    const actualMoved = buildSubmissionDraft(inputs({ invalidation: 132, invalidationIsUserSet: true }), OPTS);
    expect(submissionDifferences(reviewed, actualMoved)).toEqual(['stockStop', 'stockStopIsUserSet']);
    const premiumMoved = buildSubmissionDraft(inputs({ premiumStopDollar: 0.9 }), OPTS);
    expect(submissionDifferences(reviewed, premiumMoved)).toEqual(['premiumStopDollar', 'premiumStopPct']);
    const qtyMoved = buildSubmissionDraft(inputs({ contracts: 3 }), OPTS);
    expect(submissionDifferences(reviewed, qtyMoved)).toEqual(['quantity']);
    const entryMoved = buildSubmissionDraft(inputs({ livePrice: 4.2 }), OPTS);
    expect(submissionDifferences(reviewed, entryMoved)).toEqual(['trackingEntryPrice', 'directEntryPrice']);
    const pickMoved = buildSubmissionDraft(inputs({ pick: pick({ stopBasis: 'premium' }) }), OPTS);
    expect(submissionDifferences(reviewed, pickMoved)).toEqual(['pickedStopBasis']);
  });
});

describe('premium-stop basis matches what is sent', () => {
  it('untouched: nothing is sent, the server applies the global against the saved entry', () => {
    const d = buildSubmissionDraft(inputs(), OPTS);
    expect(d.stops.premiumStop).toEqual({ kind: 'global', globalPct: 0.6 });
    expect(d.tracking.premiumStopDollar).toBeNull();
    expect(d.tracking.premiumStopPct).toBeNull();
  });

  it('pinned: the dollar and its fraction of the request\'s own entry basis', () => {
    const d = buildSubmissionDraft(inputs({ premiumStopDollar: 0.9 }), OPTS);
    expect(d.stops.premiumStop).toEqual({ kind: 'pinned', dollar: 0.9, trackingFraction: 0.9 / 4, directFraction: 0.9 / 4 });
  });

  it('tiny premium, untouched: still the global — never a $/share figure', () => {
    const tiny = card({ contractDetails: { ...card().contractDetails!, mid: 0.01 }, entry: { ...card().entry, limit: 0.01 } });
    const d = buildSubmissionDraft(inputs({ card: tiny, livePrice: 0.01, entryLimit: 0.01 }), OPTS);
    expect(d.stops.premiumStop.kind).toBe('global');
  });

  it('tiny premium, pinned: the dollar is sent and no fraction can be derived', () => {
    const tiny = card({ contractDetails: { ...card().contractDetails!, mid: 0.01 }, entry: { ...card().entry, limit: 0.01 } });
    const d = buildSubmissionDraft(inputs({ card: tiny, livePrice: 0.01, entryLimit: 0.01, premiumStopDollar: 2 }), OPTS);
    expect(d.stops.premiumStop).toEqual({ kind: 'pinned', dollar: 2, trackingFraction: null, directFraction: null });
    expect(d.tracking.premiumStopDollar).toBe(2);
  });
});

describe('intended target-alert basis follows the existing server rule (picked_method.seed_tp_from_pick)', () => {
  const p = plan([[2, 170], [3, 185]]);
  it.each([
    ['no pick', null, null, { kind: 'no_pick' }],
    ['ladder row', pick(), null, { kind: 'ladder_live' }],
    ['method with no row', pick({ method: 'arithmetic', rowStockPrice: null }), p, { kind: 'ladder_fallback', reason: 'no_row' }],
    ['MC unreachable row', pick({ method: 'monte_carlo', rowStockPrice: null, rowOptionPrice: 6.24 }), null, { kind: 'ladder_fallback', reason: 'mc_unreachable' }],
    ['MC reachable row', pick({ method: 'monte_carlo', rowStockPrice: 197.5, rowOptionPrice: 6.24 }), null, { kind: 'requested_stock_level', method: 'monte_carlo', stockPrice: 197.5, rrRatio: null }],
    ['Barrier Race row', pick({ method: 'barrier_race', rowStockPrice: null, rowOptionPrice: 7.25 }), null, { kind: 'ladder_fallback', reason: 'barrier_race' }],
    ['Arithmetic, no plan attached', pick({ method: 'arithmetic', rowStockPrice: 170 }), null, { kind: 'ladder_fallback', reason: 'arithmetic_no_plan' }],
    ['Arithmetic, no matching row', pick({ method: 'arithmetic', rowStockPrice: 171 }), p, { kind: 'ladder_fallback', reason: 'arithmetic_unmatched' }],
    ['Arithmetic, ambiguous rows', pick({ method: 'arithmetic', rowStockPrice: 170 }), plan([[2, 170], [3, 170]]), { kind: 'ladder_fallback', reason: 'arithmetic_ambiguous' }],
    ['Arithmetic, third row', pick({ method: 'arithmetic', rowStockPrice: 200 }), plan([[2, 170], [3, 185], [4, 200]]), { kind: 'ladder_fallback', reason: 'arithmetic_beyond' }],
    ['Arithmetic, mapped row', pick({ method: 'arithmetic', rowStockPrice: 185 }), p, { kind: 'requested_stock_level', method: 'arithmetic', stockPrice: 185, rrRatio: 3 }],
  ])('%s', (_name, pk, ep, expected) => {
    expect(targetBasisOf(pk as MethodPick | null, ep as ExitPlan | null)).toEqual(expected);
  });

  it('the raw pick is sent verbatim, whatever the basis', () => {
    const race = pick({ method: 'barrier_race', rowStockPrice: null, rowOptionPrice: 7.25, stopBasis: 'premium' });
    const d = buildSubmissionDraft(inputs({ pick: race }), OPTS);
    expect(d.tracking).toMatchObject({ pickedMethod: 'barrier_race', pickedRowStockPrice: null, pickedRowOptionPrice: 7.25, pickedStopBasis: 'premium' });
    expect(d.selection.pick).toBe(race);
  });
});

describe('generation tokens — a late response never replaces a newer review', () => {
  it('only the token captured for the current draft is current', () => {
    const a = buildSubmissionDraft(inputs(), OPTS);
    const b = buildSubmissionDraft(inputs({ contracts: 5 }), OPTS);
    const tokenA = submissionToken(a, 1);
    const tokenB = submissionToken(b, 2);
    expect(isCurrentSubmission(tokenA, tokenB)).toBe(false);
    expect(isCurrentSubmission(tokenB, tokenB)).toBe(true);
    // Same request reviewed again later is a NEW generation: an answer for the
    // earlier generation is still stale.
    expect(isCurrentSubmission(submissionToken(a, 1), submissionToken(a, 3))).toBe(false);
    expect(isCurrentSubmission(null, tokenB)).toBe(false);
  });
});
