/**
 * #581 (TC-REVIEW-06) — THE SUBMISSION DRAFT.
 *
 * Step 7 used to build what it submits in two inline builders on the page
 * (`positionFromOrder` for Track basket, `buildPaperPosition` plus an inline
 * `postOptionOrder` body for Place Limit / Right Now — Market). Anything that
 * wanted to SHOW the trader what would be submitted had to reconstruct it in a
 * second code path, and a second path is a path that can disagree.
 *
 * Those builders now live here, unchanged in output, and every consumer goes
 * through them:
 *
 *   - the review (`components/organisms/SubmissionReview`) renders a draft;
 *   - Track basket stamps `draft.tracking` and POSTs it;
 *   - the direct sends stamp `draft.direct.limit|market.position`, save it, and
 *     post `draft.direct.*.order` at the quantity the save approved.
 *
 * The golden-payload suite (`step-7-trade-card/__tests__/submission-payload-
 * golden.test.tsx`) pins the outbound bytes against the pre-extraction builders.
 *
 * WHAT THIS MODULE DELIBERATELY DOES NOT DO
 *
 *   - It prices nothing and resolves nothing the server resolves. The saved
 *     entry price (the router re-quotes at save), the quantity after the
 *     exposure check, the premium-stop fraction against that entry, and the
 *     EFFECTIVE target-alert price are all server-side
 *     (`position_writer.create_position`). The draft carries what is REQUESTED
 *     and states the existing rule for what the server does with it; the
 *     effective values stay "unresolved until server review" (#582).
 *   - It never copies a calculation's stop (Arithmetic, Monte Carlo, Barrier
 *     Race) into the actual settings. `stops` is the Exit Plan's execution
 *     fields, exactly as the send paths resolve them.
 *
 * IMMUTABILITY AND GENERATIONS. A draft is frozen. Its `fingerprint` covers the
 * material request (everything that can change trading semantics; not the
 * wall-clock stamps and not the record-only card snapshot). The page numbers
 * each distinct fingerprint with a generation, and an async consumer captures a
 * `SubmissionToken` at request time and applies its response only while
 * `isCurrentSubmission(token, current)` holds — a late answer for an older
 * contract, quantity, entry, setting or selection can then never replace a
 * newer review.
 */

import type {
  ExitPlan, MaxLossOverride, MethodPick, PortfolioPosition, TradeCardData,
} from '@/types/domain';
import { contractId as buildContractId } from '@/types/domain';
import { premiumStopPctFromDollars } from './barrierRace';
import { tradeCardSnapshotOf } from './tradeCardSnapshot';
import { pickedFieldsFrom } from './cardEdits';
import { contractKeyFor } from './tradeCardOverride';
import { brokerLabelFor, contractLabelFor, directOrderBlock } from './directOrder';
import { TIME_STOP_DTE } from './alertEngine';

/* ── Inputs ──────────────────────────────────────────────────────────────── */

/** Everything a submission is built from, ALREADY RESOLVED by the page's one
 *  reader per field (`invalidationFor`, `entryLimitFor`, `premiumStopDollarFor`,
 *  `methodPickFor`, ...). The draft never re-reads a cache itself, so it cannot
 *  resolve a field differently from the page. */
export interface SubmissionInputs {
  card: TradeCardData;
  /** The quantity this submission requests. */
  contracts: number;
  /** A fetched live option mid for this contract, else null. */
  livePrice: number | null;
  /** The actual stock stop: a typed value, else the card's own invalidation. */
  invalidation: number | null;
  /** Whether `invalidation` was TYPED (absolute; the server must not re-anchor). */
  invalidationIsUserSet: boolean;
  /** The entry limit the order posts. */
  entryLimit: number;
  /** The touched premium stop in dollars, or null for "untouched — inherit the global". */
  premiumStopDollar: number | null;
  structuralStop: number | null;
  exitPlan: ExitPlan | null;
  maxLossOverride: MaxLossOverride | null;
  pick: MethodPick | null;
}

export interface SubmissionOptions {
  /** The selected paper broker, or null when none is selected (direct sends unavailable). */
  broker: string | null;
  /** Settings' global premium stop, display only: the server applies its own. */
  globalPremiumStopPct: number;
}

/** The wall-clock / random fields stamped at the moment of submission. */
export interface SubmissionStamps {
  entryDate: string;
  orderedAt: string;
  recId: string;
}

/* ── Request shapes ──────────────────────────────────────────────────────── */

type Stamped = 'entryDate' | 'orderedAt' | 'recId';
/** A position request whose stamps are still empty. The three keys are PRESENT
 *  (as null) so stamping keeps the serialized key order of the old builders. */
export type UnstampedPosition = Omit<PortfolioPosition, Stamped> & { [K in Stamped]: null };

export interface OptionOrderRequest {
  broker: string;
  symbol: string;
  option_symbol: string;
  action: 'BUY';
  effect: 'OPEN';
  /** The REQUESTED quantity. A direct send posts the quantity the save approved
   *  (`saved.adjustedQty ?? contracts`) in its place. */
  quantity: number;
  order_type: 'LMT' | 'MKT';
  limit_price: number | null;
  tif: 'DAY';
}

export interface DirectRoute {
  orderType: 'LMT' | 'MKT';
  position: Readonly<UnstampedPosition>;
  order: Readonly<OptionOrderRequest>;
  /** A refusal known before sending: the contract has no supplied expiry
   *  (`directExpiryBlock`), else a broker refusal (e.g. Tastytrade paper
   *  refuses MKT). The page refuses a blocked route before anything is sent. */
  blocked: string | null;
}

/* ── Selection / target basis ────────────────────────────────────────────── */

/** Why the existing server rule (`services/picked_method.py`
 *  `seed_tp_from_pick`) starts this position's target alert on the live Ladder
 *  rather than on a recorded price. Described from the REQUEST alone; the
 *  effective value is still the server's to resolve. */
export type LadderFallbackReason =
  | 'no_row'              // a method with no target row: no stock price is sent
  | 'mc_unreachable'      // a Monte Carlo row with no stock-price equivalent
  | 'barrier_race'        // a race row carries an option premium only
  | 'arithmetic_no_plan'  // no Arithmetic plan attached to the request
  | 'arithmetic_unmatched'// no attached plan row within a cent of the target
  | 'arithmetic_ambiguous'// equally close rows with different R multiples
  | 'arithmetic_beyond';  // a row past the first two (only two alert slots exist)

export type TargetBasis =
  | { kind: 'no_pick' }
  | { kind: 'ladder_live' }
  | { kind: 'requested_stock_level'; method: 'monte_carlo' | 'arithmetic'; stockPrice: number; rrRatio: number | null }
  | { kind: 'ladder_fallback'; reason: LadderFallbackReason };

/** Mirrors `picked_method._PRICE_TOL` — a cent is far below the gap between two
 *  R rows and far above float noise. */
const PRICE_TOL = 0.005;
/** `picked_method._RR_ROW_METHODS` has two entries: exit_plan_2r, exit_plan_3r. */
const ARITHMETIC_ALERT_SLOTS = 2;

/** The intended target-alert basis of a pick, from the request alone.
 *
 *  This is a DESCRIPTION of which branch of the existing server rule the
 *  request shape lands in, so the review can say "falls back to the Ladder"
 *  instead of promising a target that is not sent. It is not a resolution:
 *  the review still labels the effective alert unresolved until server review. */
export function targetBasisOf(pick: MethodPick | null, exitPlan: ExitPlan | null): TargetBasis {
  if (!pick) return { kind: 'no_pick' };
  const stock = pick.rowStockPrice;
  if (stock == null || !Number.isFinite(stock) || stock <= 0) {
    if (pick.method === 'barrier_race') return { kind: 'ladder_fallback', reason: 'barrier_race' };
    if (pick.method === 'monte_carlo' && pick.rowOptionPrice != null) {
      return { kind: 'ladder_fallback', reason: 'mc_unreachable' };
    }
    return { kind: 'ladder_fallback', reason: 'no_row' };
  }
  if (pick.method === 'ladder') return { kind: 'ladder_live' };
  if (pick.method === 'monte_carlo') {
    return { kind: 'requested_stock_level', method: 'monte_carlo', stockPrice: stock, rrRatio: null };
  }
  if (pick.method === 'arithmetic') {
    const rows = Array.isArray(exitPlan?.targets) ? exitPlan!.targets : null;
    if (!rows || rows.length === 0) return { kind: 'ladder_fallback', reason: 'arithmetic_no_plan' };
    const near = rows
      .filter((r) => Number.isFinite(r.price) && Number.isFinite(r.rrRatio) && Math.abs(r.price - stock) <= PRICE_TOL + 1e-12)
      .map((r) => ({ d: Math.abs(r.price - stock), rr: r.rrRatio }));
    if (near.length === 0) return { kind: 'ladder_fallback', reason: 'arithmetic_unmatched' };
    const best = Math.min(...near.map((n) => n.d));
    const ratios = new Set(near.filter((n) => n.d === best).map((n) => n.rr));
    if (ratios.size !== 1) return { kind: 'ladder_fallback', reason: 'arithmetic_ambiguous' };
    const rr = [...ratios][0]!;
    const slot = rows.findIndex((r) => r.rrRatio === rr);
    if (slot < 0 || slot >= ARITHMETIC_ALERT_SLOTS) return { kind: 'ladder_fallback', reason: 'arithmetic_beyond' };
    return { kind: 'requested_stock_level', method: 'arithmetic', stockPrice: stock, rrRatio: rr };
  }
  return { kind: 'ladder_fallback', reason: 'no_row' };
}

/* ── Premium stop basis ──────────────────────────────────────────────────── */

export type PremiumStopBasis =
  /** Untouched: no dollar and no fraction are sent; the server applies the
   *  global premium stop against the entry it saves (the fill basis). */
  | { kind: 'global'; globalPct: number }
  /** Touched: the dollar is sent, plus the fraction of the request's own entry
   *  basis (null when that basis cannot carry it — e.g. a tiny premium). */
  | { kind: 'pinned'; dollar: number; trackingFraction: number | null; directFraction: number | null };

/* ── The draft ───────────────────────────────────────────────────────────── */

export type EntryPriceSource = 'live mid' | 'scan mid' | 'entry limit';

export interface SubmissionDraft {
  readonly fingerprint: string;
  readonly identity: {
    readonly symbol: string;
    readonly direction: TradeCardData['direction'];
    readonly contractLabel: string;
    /** The OCC-style id the broker receives and a direct send stores. */
    readonly optionSymbol: string;
    /** What Track basket stores as `contract` (the card's display label). */
    readonly trackedContract: string;
    readonly contractKey: string | null;
    readonly expiry: string | null;
    readonly dte: number | null;
    /** Set for a multi-leg card: only the selected contract is submitted. */
    readonly spread: { readonly name: string; readonly legCount: number } | null;
  };
  readonly quantity: { readonly contracts: number; readonly shares: number };
  readonly entry: {
    /** The plan's order type label (card.entry.orderType). */
    readonly planOrderType: string;
    readonly limitPrice: number;
    /** `entryPrice` in the tracking request. */
    readonly trackingEntryPrice: number;
    /** `entryPrice` in the direct-send position. */
    readonly directEntryPrice: number;
    readonly entryPriceSource: EntryPriceSource;
  };
  readonly stops: {
    readonly stockStop: number | null;
    readonly stockStopIsUserSet: boolean;
    readonly structuralStop: number | null;
    readonly premiumStop: PremiumStopBasis;
    readonly maxLossOverride: MaxLossOverride | null;
    /** App-wide TIME_STOP rule; not a per-position field of the request. */
    readonly timeExitDte: number;
  };
  readonly selection: {
    /** The raw recorded choice, sent verbatim (`pickedFieldsFrom`). */
    readonly pick: MethodPick | null;
    readonly targetBasis: TargetBasis;
    readonly exitPlanAttached: boolean;
    readonly exitPlanComputedAt: string | null;
  };
  /** Track basket's request (Portfolio row only; no broker order). */
  readonly tracking: Readonly<UnstampedPosition>;
  /** The direct sends, or null when no broker is selected. */
  readonly direct: Readonly<{
    broker: string;
    brokerLabel: string;
    limit: DirectRoute;
    market: DirectRoute;
  }> | null;
}

/** The identity an async consumer captures at request time. */
export interface SubmissionToken { readonly generation: number; readonly fingerprint: string }

/* ── Builders (moved verbatim from the Step 7 page) ──────────────────────── */

/** A positive number, else null. The router refuses `entryPrice` 0 (`gt=0`),
 *  so a `0` scan mid must fall through to the next source, not be kept by `??`. */
function positiveOrNull(x: number | null | undefined): number | null {
  return x != null && x > 0 ? x : null;
}

/** Build the pipe-delimited option id the OCC converter and broker adapters expect. */
export function optionSymbolFor(card: TradeCardData): string {
  const cd = card.contractDetails;
  if (cd?.strike != null && cd.expiry && cd.right) {
    return buildContractId(card.symbol, cd.strike, cd.expiry, cd.right);
  }
  return card.contract; // fallback (display label — broker may reject, best effort)
}

/** Track basket's entry basis: live mid, scan mid, the entry limit, the plan limit. */
function trackingMid(i: SubmissionInputs): number {
  const cd = i.card.contractDetails;
  return positiveOrNull(i.livePrice) ?? positiveOrNull(cd?.mid)
    ?? positiveOrNull(i.entryLimit) ?? i.card.entry.limit;
}

/** A direct send's entry basis: live mid, scan mid, the entry limit. */
function directMid(i: SubmissionInputs): number {
  const cd = i.card.contractDetails;
  return positiveOrNull(i.livePrice) ?? positiveOrNull(cd?.mid) ?? i.entryLimit;
}

/** Track basket's request — formerly the page's `positionFromOrder` (plus the
 *  `scanStockPrice` its caller appended). Key order is load-bearing for the
 *  golden-payload guard; do not reorder. */
function trackingRequest(i: SubmissionInputs): UnstampedPosition {
  const c = i.card;
  const cd = c.contractDetails;
  const mid = trackingMid(i);
  const dte = cd?.dte ?? 24;
  return {
    symbol:        c.symbol,
    contract:      c.contract,
    direction:     c.direction,
    entryDate:     null,
    expiry:        cd?.expiry ?? new Date(Date.now() + dte * 86_400_000).toISOString().slice(0, 10),
    dteRemaining:  dte,
    dteTotal:      dte,
    entryPrice:    mid,
    currentPrice:  mid,
    pnlDollar:     0,
    pnlPct:        0,
    stop:          i.invalidation,
    // True means a TOUCHED field: an absolute price the server must not re-anchor.
    stopIsUserSet: i.invalidationIsUserSet,
    structuralStop: i.structuralStop,
    exitPlan:      i.exitPlan,
    maxLossOverride: i.maxLossOverride,
    // Sent as DOLLARS; the backend derives the fraction against the entry it persists...
    premiumStopDollar: i.premiumStopDollar,
    // ...and as the user's own FRACTION of this `mid` (PREMIUM-STOP-FALLBACK-
    // USER-FRACTION-2026-10-03), stored only when the dollar is unusable there.
    premiumStopPct: premiumStopPctFromDollars(i.premiumStopDollar, mid) ?? null,
    targets:       c.exit.targets,
    status:        c.finalStatus,
    ivRank:        cd?.ivRank,
    iv:            cd?.iv,
    delta:         cd?.delta,
    theta:         cd?.theta,
    vega:          0.20,
    contracts:     i.contracts,
    // Fix #5: the basket places no broker order (D6).
    source:        'manual',
    orderedAt:     null,
    recId:         null,
    tradeCardSnapshot: tradeCardSnapshotOf(c),
    ...pickedFieldsFrom(i.pick),
    // ROUND 10 finding 2 — without it the router never re-anchors or guards.
    scanStockPrice: c.price,
  };
}

/** The selected contract's SUPPLIED expiry, or null when it has none: missing
 *  `contractDetails`, or an expiry that is null, undefined, empty or blank. A
 *  supplied non-blank value is returned exactly as given (no trimming). */
function suppliedExpiry(card: TradeCardData): string | null {
  const expiry: unknown = card.contractDetails?.expiry;
  return typeof expiry === 'string' && expiry.trim() !== '' ? expiry : null;
}

/** #591 (DIRECT-SEND-EXPIRY-PLACEHOLDER) — why a direct send (Place Limit or
 *  Right Now — Market) is refused for this card's contract expiry, or null.
 *
 *  A direct send's position carries the contract's expiry, which the local
 *  Portfolio row keeps (the save body sends the contract id, not this field)
 *  and DTE, the time-exit alert and P/L horizons read. With no supplied expiry the
 *  send is REFUSED: nothing is inferred from a default DTE or a display label.
 *  The same helper feeds `DirectRoute.blocked` (the review) and the page's
 *  send preflight, which runs before any quote, preview, save or order. */
export function directExpiryBlock(card: TradeCardData): string | null {
  return suppliedExpiry(card) == null
    ? 'This contract has no expiry date — reselect the contract in Step 6 before sending.'
    : null;
}

/** A direct send's position — formerly the page's `buildPaperPosition`, with
 *  the order id 'pending' it was always called with before the save.
 *
 *  #591 — with no supplied expiry the route is blocked (`directExpiryBlock`)
 *  and this position carries an EMPTY expiry, which is never submitted; it
 *  never carries a made-up date. */
function directPosition(i: SubmissionInputs, orderType: 'LMT' | 'MKT', broker: string): UnstampedPosition {
  const card = i.card;
  const cd = card.contractDetails;
  const mid = directMid(i);
  const dte = cd?.dte ?? 24;
  const brokerLabel = brokerLabelFor(broker);
  const typeLabel = orderType === 'LMT' ? 'Limit' : 'Market';
  return {
    symbol:        card.symbol,
    contract:      optionSymbolFor(card),
    direction:     card.direction,
    entryDate:     null,
    expiry:        suppliedExpiry(card) ?? '',
    dteRemaining:  dte,
    dteTotal:      dte,
    entryPrice:    mid,
    currentPrice:  mid,
    pnlDollar:     0,
    pnlPct:        0,
    stop:          i.invalidation,
    stopIsUserSet: i.invalidationIsUserSet,
    structuralStop: i.structuralStop,
    exitPlan:      i.exitPlan,
    maxLossOverride: i.maxLossOverride,
    premiumStopDollar: i.premiumStopDollar,
    premiumStopPct: premiumStopPctFromDollars(i.premiumStopDollar, mid) ?? null,
    targets:       card.exit.targets,
    status:        card.finalStatus,
    ivRank:        cd?.ivRank,
    iv:            cd?.iv,
    delta:         cd?.delta,
    theta:         cd?.theta,
    vega:          0.20,
    contracts:     i.contracts,
    source:        'paper',
    sourceLabel:   `${brokerLabel} — ${typeLabel} (ID: pending)`,
    orderedAt:     null,
    recId:         null,
    scanStockPrice: card.price,
    tradeCardSnapshot: tradeCardSnapshotOf(card),
    ...pickedFieldsFrom(i.pick),
  };
}

function orderRequest(i: SubmissionInputs, orderType: 'LMT' | 'MKT', broker: string): OptionOrderRequest {
  return {
    broker,
    symbol:        i.card.symbol,
    option_symbol: optionSymbolFor(i.card),
    action:        'BUY',
    effect:        'OPEN',
    quantity:      i.contracts,
    order_type:    orderType,
    limit_price:   orderType === 'LMT' ? i.entryLimit : null,
    tif:           'DAY',
  };
}

function deepFreeze<T>(value: T): T {
  if (value && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const v of Object.values(value as Record<string, unknown>)) deepFreeze(v);
  }
  return value;
}

/** Stable JSON: object keys sorted, so the fingerprint never depends on key order. */
function stableStringify(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(',')}]`;
  if (value && typeof value === 'object') {
    const entries = Object.keys(value as Record<string, unknown>).sort()
      .filter((k) => (value as Record<string, unknown>)[k] !== undefined)
      .map((k) => `${JSON.stringify(k)}:${stableStringify((value as Record<string, unknown>)[k])}`);
    return `{${entries.join(',')}}`;
  }
  return JSON.stringify(value ?? null);
}

/** The record-only card snapshot is excluded: it cannot change trading semantics. */
function material(p: Readonly<UnstampedPosition>): Record<string, unknown> {
  const rest: Record<string, unknown> = { ...p };
  delete rest.tradeCardSnapshot;
  return rest;
}

/** Build the immutable submission draft for one card. Pure. */
export function buildSubmissionDraft(inputs: SubmissionInputs, options: SubmissionOptions): SubmissionDraft {
  const card = inputs.card;
  const cd = card.contractDetails;
  const tracking = trackingRequest(inputs);
  const route = (orderType: 'LMT' | 'MKT', broker: string): DirectRoute => ({
    orderType,
    position: directPosition(inputs, orderType, broker),
    order: orderRequest(inputs, orderType, broker),
    // A missing expiry is refused first; a valid one keeps the broker-type refusal.
    blocked: directExpiryBlock(card) ?? directOrderBlock(orderType, broker),
  });
  const direct = options.broker
    ? { broker: options.broker, brokerLabel: brokerLabelFor(options.broker), limit: route('LMT', options.broker), market: route('MKT', options.broker) }
    : null;
  const trackingEntry = tracking.entryPrice;
  const directEntry = directMid(inputs);
  const entryPriceSource: EntryPriceSource = positiveOrNull(inputs.livePrice) != null ? 'live mid'
    : positiveOrNull(cd?.mid) != null ? 'scan mid' : 'entry limit';
  const premiumStop: PremiumStopBasis = inputs.premiumStopDollar == null
    ? { kind: 'global', globalPct: options.globalPremiumStopPct }
    : {
      kind: 'pinned',
      dollar: inputs.premiumStopDollar,
      trackingFraction: tracking.premiumStopPct ?? null,
      directFraction: premiumStopPctFromDollars(inputs.premiumStopDollar, directEntry) ?? null,
    };
  const multiLeg = card.spreadType && card.spreadType !== 'single' && card.legs && card.legs.length > 0;
  const fingerprint = stableStringify({
    tracking: material(tracking),
    direct: direct ? {
      broker: direct.broker,
      limit: { position: material(direct.limit.position), order: direct.limit.order },
      market: { position: material(direct.market.position), order: direct.market.order },
    } : null,
  });
  const draft: SubmissionDraft = {
    fingerprint,
    identity: {
      symbol: card.symbol,
      direction: card.direction,
      contractLabel: contractLabelFor(card),
      optionSymbol: optionSymbolFor(card),
      trackedContract: card.contract,
      contractKey: contractKeyFor(card),
      expiry: cd?.expiry ?? null,
      dte: cd?.dte ?? null,
      spread: multiLeg
        ? { name: card.spreadType === 'bear_put' ? 'Bear Put Spread' : 'Bear Call Spread', legCount: card.legs!.length }
        : null,
    },
    quantity: { contracts: inputs.contracts, shares: inputs.contracts * 100 },
    entry: {
      planOrderType: card.entry.orderType,
      limitPrice: inputs.entryLimit,
      trackingEntryPrice: trackingEntry,
      directEntryPrice: directEntry,
      entryPriceSource,
    },
    stops: {
      stockStop: inputs.invalidation,
      stockStopIsUserSet: inputs.invalidationIsUserSet,
      structuralStop: inputs.structuralStop,
      premiumStop,
      maxLossOverride: inputs.maxLossOverride,
      timeExitDte: TIME_STOP_DTE,
    },
    selection: {
      pick: inputs.pick,
      targetBasis: targetBasisOf(inputs.pick, inputs.exitPlan),
      exitPlanAttached: inputs.exitPlan != null,
      exitPlanComputedAt: inputs.exitPlan?.computedAt ?? null,
    },
    tracking,
    direct,
  };
  // Freeze the draft's own containers; the card-owned objects it references
  // (targets, exitPlan, snapshot) are left as they are — freezing them would
  // freeze the page's live card.
  Object.freeze(draft.identity);
  Object.freeze(draft.quantity);
  Object.freeze(draft.entry);
  Object.freeze(draft.stops.premiumStop);
  Object.freeze(draft.stops);
  Object.freeze(draft.selection);
  Object.freeze(draft.tracking);
  if (direct) {
    for (const r of [direct.limit, direct.market]) { Object.freeze(r.position); Object.freeze(r.order); Object.freeze(r); }
    Object.freeze(direct);
  }
  return Object.freeze(draft);
}

/* ── Submission boundary ─────────────────────────────────────────────────── */

/** The position a submission POSTs: the draft's request with its stamps. The
 *  spread keeps every key where the draft put it. */
export function stampPosition(request: Readonly<UnstampedPosition>, stamps: SubmissionStamps): PortfolioPosition {
  return { ...request, entryDate: stamps.entryDate, orderedAt: stamps.orderedAt, recId: stamps.recId } as PortfolioPosition;
}

/** The broker order a direct send posts: the draft's order at the saved quantity. */
export function orderAtQuantity(order: Readonly<OptionOrderRequest>, quantity: number): OptionOrderRequest {
  return { ...order, quantity };
}

/* ── Review-to-submission parity contract ────────────────────────────────── */

export function submissionToken(draft: SubmissionDraft, generation: number): SubmissionToken {
  return deepFreeze({ generation, fingerprint: draft.fingerprint });
}

/** True only while the reviewed draft is still the current one. An async
 *  consumer (the #582 server review, the #583 dispatch) captures a token at
 *  request time and drops its response when this is false. */
export function isCurrentSubmission(captured: SubmissionToken | null | undefined, current: SubmissionToken | null | undefined): boolean {
  return captured != null && current != null
    && captured.generation === current.generation && captured.fingerprint === current.fingerprint;
}

/** The material execution fields of a draft, by name. */
function parityFields(d: SubmissionDraft): Record<string, unknown> {
  return {
    contract: d.identity.optionSymbol,
    trackedContract: d.identity.trackedContract,
    quantity: d.quantity.contracts,
    broker: d.direct?.broker ?? null,
    limitPrice: d.entry.limitPrice,
    trackingEntryPrice: d.entry.trackingEntryPrice,
    directEntryPrice: d.entry.directEntryPrice,
    stockStop: d.stops.stockStop,
    stockStopIsUserSet: d.stops.stockStopIsUserSet,
    structuralStop: d.stops.structuralStop,
    premiumStopDollar: d.tracking.premiumStopDollar,
    premiumStopPct: d.tracking.premiumStopPct,
    maxLossOverride: d.stops.maxLossOverride,
    exitPlan: d.tracking.exitPlan ?? null,
    targets: d.tracking.targets ?? null,
    pickedMethod: d.tracking.pickedMethod,
    pickedRowStockPrice: d.tracking.pickedRowStockPrice,
    pickedRowOptionPrice: d.tracking.pickedRowOptionPrice,
    pickedStopBasis: d.tracking.pickedStopBasis,
    pickedAt: d.tracking.pickedAt,
  };
}

/** The names of the material fields on which a submitted draft differs from
 *  the reviewed one. Empty means review-to-submission parity holds. */
export function submissionDifferences(reviewed: SubmissionDraft, submitted: SubmissionDraft): string[] {
  const a = parityFields(reviewed);
  const b = parityFields(submitted);
  const diffs = Object.keys(a).filter((k) => stableStringify(a[k]) !== stableStringify(b[k]));
  // Anything else in the request (both fingerprints cover it) is reported as one field.
  if (diffs.length === 0 && reviewed.fingerprint !== submitted.fingerprint) diffs.push('request');
  return diffs;
}
