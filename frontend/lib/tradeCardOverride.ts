/*
 * Pure helpers for Step 7's contract-override + recompute-plan machinery.
 * Extracted out of the page component so the exact logic that determines
 * "which contract/plan does this order actually carry" is unit-testable —
 * this is what silently broke for the basket flow (the override reached the
 * single-card buttons but not the basket path, since the basket cards were
 * built straight from the raw scan candidates). Since fix #5 (D6) the basket
 * TRACKS positions in Portfolio and places no broker order.
 */
import type {
  TradeCardData, OptionContract, StructuralStop, FirstPassageEstimate, FirstPassageContext, ExitPlan,
  StockExplanation, ContractExplanation,
} from '@/types/domain';

export type OverriddenCard = TradeCardData & { _userOverride?: boolean };
export type RecomputedPlanShape = {
  entry: TradeCardData['entry'];
  exit: TradeCardData['exit'];
  rrRatio: number;
  rrModel: TradeCardData['rrModel'];
};
export type PlanEntry = { key: string; plan: RecomputedPlanShape };

export type ScoreEvidence<T> =
  | { state: 'captured'; explanation: T }
  | { state: 'not_captured'; message: 'Not captured — re-run scan' };

/** Read evidence only when it belongs to this authoritative result. Repricing
 *  a plan does not score a contract; mergePlan must retain the picked row's
 *  evidence. Legacy absence is explicit and never filled from live settings. */
export function scoreEvidenceFor(card: TradeCardData): {
  stock: ScoreEvidence<StockExplanation>;
  contract: ScoreEvidence<ContractExplanation>;
} {
  const absent = { state: 'not_captured', message: 'Not captured — re-run scan' } as const;
  const stock = card.stockExplanation;
  const contract = card.contractExplanation;
  return {
    stock: stock && stock.symbol === card.symbol && stock.direction === card.direction
      && stock.score === card.stockScore && stock.status === card.stockConfidence
      ? { state: 'captured', explanation: stock } : absent,
    contract: contract && contract.contract_id === card.contract
      && contract.score === card.contractScore && contract.status === card.contractConfidence
      ? { state: 'captured', explanation: contract } : absent,
  };
}

/** Swap the auto-picked contract's details for a user-selected one from the
 *  Step 6 chain. Only the Contract Details block changes here — Entry/Exit/RR
 *  are recomputed asynchronously (a network round-trip) and merged in
 *  separately. Returns `card` unchanged when there's no override. */
export function applyPickedContract(card: TradeCardData, picked: OptionContract | undefined): OverriddenCard {
  if (!picked) return card;
  if (picked.id === card.contract) return { ...card, noLiveQuote: picked.noLiveQuote ?? false };
  return {
    ...card,
    contract: picked.id,
    noLiveQuote: picked.noLiveQuote ?? false,
    contractScore: picked.score,
    contractConfidence: picked.contractConfidence,
    // ROUND 6 finding 8. The breakdown has to move with the contract. Without
    // this, the card showed the PICKED contract's composite score and the
    // AUTO-PICKED one's five component scores and detail lines beneath it —
    // and since the Phase A split made ivDetailText quantitative ("IV 62% ·
    // pref ≤55%"), the two panels visibly asserted a specific IV percentage
    // for a strike the user was not looking at.
    //
    // Falls back to the existing breakdown only when the picked row carries
    // none (an older cached /api/contracts response, or a chain row that came
    // from the scan rather than the endpoint). Nothing is invented: the
    // backend already computes this per contract and simply was not returning
    // it.
    contractBreakdown: picked.breakdown ?? card.contractBreakdown,
    // Set from picked row ONLY; legacy/missing picked explanation clears it rather
    // than borrowing the auto-picked card's explanation.
    contractExplanation: picked.explanation,
    contractDetails: {
      strike:       picked.strike,
      expiry:       picked.expiry,
      right:        picked.right,
      mid:          picked.price,
      spread:       picked.spread,
      delta:        picked.delta,
      theta:        picked.theta,
      // Carry BOTH quantities across the override — `ivRank` is null on any
      // chain without a rank source, and dropping `iv` would blank the card's
      // IV readout for the contract the user just picked
      // (PHASE-A-NULL-IVRANK-2026-09-06).
      ivRank:       picked.ivRank,
      iv:           picked.iv,
      ivPercentile: picked.ivPercentile,
      dte:          picked.dte,
    },
    _userOverride: true,
  };
}

/** Contract identity key for a card — used to cache/invalidate recomputed
 *  plans per contract, so a plan for contract A is never merged onto contract B. */
export function contractKeyFor(card: TradeCardData | undefined): string | null {
  const cd = card?.contractDetails;
  if (!card?.symbol || cd?.strike == null || !cd.expiry || !cd.right) return null;
  return `${card.symbol}|${cd.strike}|${cd.expiry}|${cd.right}`;
}

/** Merge a resolved plan into an overridden card's Entry/Exit/RR. Preserves
 *  `_userOverride` via the spread — the return type reflects that instead of
 *  narrowing it away.
 *
 *  PIECE 3: `exit` is replaced WHOLESALE, which is what makes the stop worth
 *  guarding here. The stop is a STOCK level — which contract is being traded
 *  has no bearing on where structure sits — so a contract override must not
 *  move it. The endpoint is sent the card's own `finalStop` and echoes it
 *  back, so the merged plan normally already carries it; this keeps the card's
 *  block anyway when a response arrives without one, which is what a stale
 *  client, a proxy that dropped the field, or a rolled-back backend looks
 *  like. Defence in depth, per the plan's part 3 — never the primary
 *  mechanism, and the two must not disagree: when the plan DOES carry a block,
 *  the plan wins, because it is the block the plan's `invalidation` was
 *  computed against and a mismatched pair is worse than either half. */
export function mergePlan(card: OverriddenCard, plan: RecomputedPlanShape): OverriddenCard {
  const exit = plan.exit.finalStop == null && card.exit.finalStop != null
    ? { ...plan.exit, finalStop: card.exit.finalStop, invalidation: card.exit.invalidation }
    : plan.exit;
  return { ...card, entry: plan.entry, exit, rrRatio: plan.rrRatio, rrModel: plan.rrModel };
}

/**
 * Resolve every basket symbol to its (possibly overridden, possibly
 * plan-merged) card. Any overridden symbol whose plan isn't cached yet for its
 * CURRENT contract key is excluded from the returned list and flips
 * `pending` — this is the gate that must block the basket's "Track basket"
 * submit, so a tracked row can never be booked carrying an overridden contract
 * whose Entry/Exit/RR still describe the auto-pick. (The basket places no
 * broker order since fix #5 / D6; it books Portfolio rows that reserve the
 * contract and symbol.)
 *
 * Also splices in each card's cached "Compute Exit Plan" result (keyed by
 * contract, same cache `withCachedEstimate` reads for the single active
 * TradeCard) — without this, `checkTradeRisk`'s max-loss-per-trade gate
 * silently never fires for the basket "Track basket" path: a raw scan
 * candidate never carries `exit.exitPlan` on its own, only a user's
 * "Compute Exit Plan" click populates it, and that click's result was never
 * otherwise reaching the cards this function returns.
 */
export function resolveBasketCards(
  basket: string[],
  cardIndex: Record<string, TradeCardData>,
  pickedContracts: Record<string, string>,
  contractsBySymbol: Record<string, OptionContract[]>,
  plansBySymbol: Record<string, PlanEntry>,
  exitPlanByContract: Record<string, CachedExitPlan> = {},
): { cards: TradeCardData[]; pending: boolean } {
  let pending = false;
  const cards: TradeCardData[] = [];
  for (const sym of basket) {
    const raw = cardIndex[sym];
    if (!raw) continue;
    const pickedId = pickedContracts[sym];
    const picked = pickedId ? contractsBySymbol[sym]?.find((c) => c.id === pickedId) : undefined;
    const resolved = applyPickedContract(raw, picked);
    let card: TradeCardData;
    if (!resolved._userOverride) {
      card = resolved;
    } else {
      const key = contractKeyFor(resolved);
      const entry = plansBySymbol[sym];
      if (entry && entry.key === key) {
        card = mergePlan(resolved, entry.plan);
      } else {
        pending = true;
        continue;
      }
    }
    const contractKey = contractKeyFor(card);
    const exitPlanEntry = contractKey ? exitPlanByContract[contractKey] : undefined;
    // withCachedEstimate MUST run after mergePlan (see its own doc comment) —
    // mergePlan replaces `exit` wholesale, which would discard the splice if
    // applied first. Falls back to the unspliced `card` only if the helper
    // itself somehow returned undefined, which it can't for a defined input.
    cards.push(withCachedEstimate(card, undefined, undefined, exitPlanEntry) ?? card);
  }
  return { cards, pending };
}

const RR_OVERRIDE_KEYS = [
  'rr_target_r_multiple',
  'rr_bullish_invalidation_pct', 'rr_bearish_invalidation_pct',
] as const;

/** Pull just the Reward/Risk override keys out of scanOverrides, dropping
 *  any that aren't set (so recomputePlan's optional fields stay optional). */
export function rrOverridesFrom(
  scanOverrides: Record<string, number | boolean | string>,
): Partial<Record<typeof RR_OVERRIDE_KEYS[number], number>> {
  const out: Partial<Record<typeof RR_OVERRIDE_KEYS[number], number>> = {};
  for (const key of RR_OVERRIDE_KEYS) {
    const v = scanOverrides[key];
    if (typeof v === 'number') out[key] = v;
  }
  return out;
}

/** The Reward/Risk overrides Step 7's recompute-plan sends: the ones the scan
 *  priced its plans with (ScanResult.rr_overrides), so a Step-3 value edited
 *  after the scan cannot reprice the card's plan on different targets from
 *  the card the scan built (STEP3-PARAM-REACH). A result from before the scan
 *  recorded them (absent or null) falls back to live scanOverrides, which is
 *  what every recompute sent before. */
export function rrOverridesForPlan(
  scanResult: { rr_overrides?: Record<string, number> | null } | null | undefined,
  scanOverrides: Record<string, number | boolean | string>,
): Partial<Record<typeof RR_OVERRIDE_KEYS[number], number>> {
  const recorded = scanResult?.rr_overrides;
  return rrOverridesFrom(recorded != null ? recorded : scanOverrides);
}

export const ENTRY_OVERRIDE_KEYS = [
  'entry_spread_tolerance_pct',
  'entry_max_slippage_pct',
  'entry_min_premium',
] as const;

/** Pull just the Entry Quality override keys out of scanOverrides, dropping
 *  any that aren't set (so recomputePlan's optional fields stay optional).
 *  Zero (0 / 0.0) is a valid override value and is preserved. */
export function entryOverridesFrom(
  scanOverrides: Record<string, number | boolean | string>,
): Partial<Record<typeof ENTRY_OVERRIDE_KEYS[number], number>> {
  const out: Partial<Record<typeof ENTRY_OVERRIDE_KEYS[number], number>> = {};
  for (const key of ENTRY_OVERRIDE_KEYS) {
    const v = scanOverrides[key];
    if (typeof v === 'number' && Number.isFinite(v)) out[key] = v;
  }
  return out;
}

/** The Entry Quality overrides Step 7's recompute-plan sends: the ones the scan
 *  priced its plans with (ScanResult.entry_overrides), so a Step-3 value edited
 *  after the scan cannot reprice the card's entry plan on different rules from
 *  the card the scan built (APP-AUDIT-B-ENTRY-OVERRIDES). A result from before
 *  the scan recorded them (absent or null) falls back to live scanOverrides. */
export function entryOverridesForPlan(
  scanResult: { entry_overrides?: Record<string, number> | null } | null | undefined,
  scanOverrides: Record<string, number | boolean | string>,
): Partial<Record<typeof ENTRY_OVERRIDE_KEYS[number], number>> {
  const recorded = scanResult?.entry_overrides;
  return entryOverridesFrom(recorded != null ? recorded : scanOverrides);
}

/** The repricing-horizon fields every trade-card backend call must carry.
 *
 *  Three call sites send them today — the two recomputePlan effects in
 *  step-7-trade-card and TradeCard's own getFirstPassageEstimate — and they must
 *  agree, because the backend's fallback table is a dict keyed by exact string
 *  that falls through to Swing's 7 days on a miss WITHOUT complaining. A site
 *  that sends the collapsed scoring horizon, or omits the preset while another
 *  sends it, does not error: it silently reprices the Fixed % Ladder at a
 *  different horizon from the Monte Carlo card directly above it. One helper so
 *  there is one spelling.
 *
 *  A null context resolves to `{}`, which the backend reads as "Swing" — the
 *  same default presetByKey() already applies on the frontend. */
export function horizonFieldsFrom(
  ctx: { horizonPreset?: string; holdMin?: number; holdMax?: number } | null | undefined,
): { horizon_preset?: string; hold_min?: number; hold_max?: number } {
  if (!ctx) return {};
  const out: { horizon_preset?: string; hold_min?: number; hold_max?: number } = {};
  if (ctx.horizonPreset != null) out.horizon_preset = ctx.horizonPreset;
  if (typeof ctx.holdMin === 'number') out.hold_min = ctx.holdMin;
  if (typeof ctx.holdMax === 'number') out.hold_max = ctx.holdMax;
  return out;
}

/** One cached "Estimate" result, keyed by CONTRACT (contractKeyFor) — the
 *  estimate is priced off that contract's premium/strike/dte, so a symbol-level
 *  key would show contract A's numbers on contract B's card. `estimate: null`
 *  is a real, cacheable answer (a failed re-estimate that must overwrite a
 *  stale one — see cacheFirstPassage), the same role `CachedStructural.stop:
 *  null` plays below. */
export type CachedFirstPassage = {
  estimate: FirstPassageEstimate | null;
  context:  FirstPassageContext | null;
};

/** One cached "Check structure" result, keyed by CONTRACT (contractKeyFor). The
 *  structural LEVEL is a function of (symbol, direction, stock_price) only, but
 *  the request carries the contract (strike, dte, live premium) and since B2 the
 *  response's `stop.stopCost` is the stop-vs-premium verdict priced against that
 *  contract — so a symbol key would splice contract A's verdict onto contract
 *  B's card (A8, open_questions[51]). `stop: null` is a real, cacheable answer ("checked, no
 *  order block or swing level found"), distinct from "never checked" (no entry). */
export type CachedStructural = {
  stop:       StructuralStop | null;
  stockPrice: number | null;
};

/**
 * Cache-write reducer for a "Check structure" result, keyed by SYMBOL.
 *
 * Two invariants live here, both load-bearing, which is why this is a pure
 * function next to the read side rather than an inline closure in the page:
 *
 * 1. `stop === undefined` is the "reset on contract switch" / "cleared at the
 *    start of a re-check" sentinel, NOT an answer — it is ignored, never
 *    written. So an in-flight or failed re-check leaves the previously cached
 *    level intact instead of destroying what the user could still see a moment
 *    ago. (`stop === null` IS an answer — "checked, nothing found" — and is
 *    cached.)
 * 2. When nothing actually changed it returns the IDENTICAL `prev` object. The
 *    callback prop the page hands TradeCard is a fresh inline closure every
 *    render and TradeCard keeps a ref synced to it, so a write that always
 *    produced a new object would re-render the parent on every TradeCard
 *    render, re-create the prop, re-fire the sync effect... an unbounded
 *    cascade. Returning `prev` lets React skip the re-render entirely.
 */
export function cacheStructural(
  prev: Record<string, CachedStructural>,
  key: string,
  stop: StructuralStop | null | undefined,
  stockPrice: number | null,
): Record<string, CachedStructural> {
  if (stop === undefined) return prev;
  const cur = prev[key];
  if (cur && cur.stop === stop && cur.stockPrice === stockPrice) return prev;
  return { ...prev, [key]: { stop, stockPrice } };
}

/**
 * Cache-write reducer for an "Estimate" (first-passage) result, keyed by
 * CONTRACT — the estimate is priced off that contract's premium, so a
 * symbol-level key would show contract A's numbers on contract B's card.
 *
 * Same two invariants as `cacheStructural` — including the SAME `undefined`
 * vs. `null` distinction (`undefined` is ignored; `null` is a real, cacheable
 * answer) — plus one specific to this cache:
 * - `key === null` means the card has no resolvable contract (no
 *   `contractDetails`), in which case the Estimate button is disabled anyway —
 *   nothing to key an entry by, so nothing is written.
 *
 * `null` was originally ignored here too (a stricter `estimate == null`
 * guard), on the reasoning that nothing in this codebase ever produces a
 * genuine "checked, confirmed no estimate" result the way a structural check
 * can genuinely find no order block or swing level. That reasoning covered
 * TradeCard's OWN render, but not what happens after this cache restores a
 * value on a later navigation: a failed re-estimate has to be able to
 * overwrite a stale cached entry the same way a failed structural re-check
 * does, or the stale premium/delta silently rides along under whatever the
 * OTHER cache (structural) resolves to next — the same bug class
 * `cacheStructural`'s docstring above describes, just on this cache's data.
 * TradeCard's failure path writes `null` specifically to force that
 * overwrite, so the guard here is strict `=== undefined` to match.
 *
 * The unchanged-comparison is by REFERENCE on both halves, which is exactly
 * right: TradeCard stores one object per successful estimate and holds it until
 * the next one, and on a restore the page splices those very same objects back
 * in — so the post-restore effect fire compares equal and bails.
 */
export function cacheFirstPassage(
  prev: Record<string, CachedFirstPassage>,
  key: string | null,
  estimate: FirstPassageEstimate | null | undefined,
  context: FirstPassageContext | null,
): Record<string, CachedFirstPassage> {
  if (!key || estimate === undefined) return prev;
  const cur = prev[key];
  if (cur && cur.estimate === estimate && cur.context === context) return prev;
  return { ...prev, [key]: { estimate, context } };
}

/** One cached "Compute Exit Plan" result, keyed by CONTRACT (contractKeyFor) —
 *  same reasoning as CachedFirstPassage: the plan's repricing/probability is
 *  computed off that contract's own strike/dte/premium, so a symbol-level key
 *  would show contract A's numbers on contract B's card. `plan: null` is a
 *  real, cacheable answer (a failed re-compute that must overwrite a stale
 *  one), the same role `CachedFirstPassage.estimate: null` plays. */
export type CachedExitPlan = {
  plan: ExitPlan | null;
};

/**
 * Cache-write reducer for a "Compute Exit Plan" result, keyed by CONTRACT.
 * Same invariants as `cacheFirstPassage`: `undefined` (in-flight/reset) is
 * ignored, `null` (a real "computation failed" answer) is cached and
 * overwrites, and an unchanged write returns the identical `prev` reference
 * so the parent doesn't re-render on a no-op.
 */
export function cacheExitPlan(
  prev: Record<string, CachedExitPlan>,
  key: string | null,
  plan: ExitPlan | null | undefined,
): Record<string, CachedExitPlan> {
  if (!key || plan === undefined) return prev;
  const cur = prev[key];
  if (cur && cur.plan === plan) return prev;
  return { ...prev, [key]: { plan } };
}

/**
 * Splice cached "Estimate" / "Check structure" results into the card's
 * `exit.*` fields — the same fields TradeCard already reads for its initial
 * state and its contract-change reset, so restoring costs TradeCard no extra
 * code and works for a re-render AND a remount alike.
 *
 * MUST be applied AFTER mergePlan: mergePlan replaces `exit` wholesale with the
 * recomputed plan's, which would silently discard anything spliced in earlier.
 * Returns the card unchanged (same reference) when there is nothing cached, so
 * it never invents object churn for the common case.
 */
export function withCachedEstimate<T extends TradeCardData>(
  card: T | undefined,
  estimate: CachedFirstPassage | undefined,
  structural: CachedStructural | undefined,
  exitPlan?: CachedExitPlan,
): T | undefined {
  if (!card || (!estimate && !structural && !exitPlan)) return card;
  return {
    ...card,
    exit: {
      ...card.exit,
      ...(estimate
        ? { firstPassage: estimate.estimate, firstPassageContext: estimate.context }
        : {}),
      ...(structural
        ? { structuralStop: structural.stop, structuralStopStockPrice: structural.stockPrice }
        : {}),
      ...(exitPlan
        ? { exitPlan: exitPlan.plan }
        : {}),
    },
  };
}
