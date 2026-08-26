/*
 * Pure helpers for Step 7's contract-override + recompute-plan machinery.
 * Extracted out of the page component so the exact logic that determines
 * "which contract/plan does this order actually carry" is unit-testable —
 * this is what silently broke for the basket "Send to broker" flow (the
 * override reached the single-card buttons but not the basket path, since
 * the basket cards were built straight from the raw scan candidates).
 */
import type {
  TradeCardData, OptionContract, StructuralStop, FirstPassageEstimate, FirstPassageContext, ExitPlan,
} from '@/types/domain';

export type OverriddenCard = TradeCardData & { _userOverride?: boolean };
export type RecomputedPlanShape = {
  entry: TradeCardData['entry'];
  exit: TradeCardData['exit'];
  rrRatio: number;
  rrModel: TradeCardData['rrModel'];
};
export type PlanEntry = { key: string; plan: RecomputedPlanShape };

/** Swap the auto-picked contract's details for a user-selected one from the
 *  Step 6 chain. Only the Contract Details block changes here — Entry/Exit/RR
 *  are recomputed asynchronously (a network round-trip) and merged in
 *  separately. Returns `card` unchanged when there's no override. */
export function applyPickedContract(card: TradeCardData, picked: OptionContract | undefined): OverriddenCard {
  if (!picked || picked.id === card.contract) return card;
  return {
    ...card,
    contract: picked.id,
    contractScore: picked.score,
    contractConfidence: picked.contractConfidence,
    contractDetails: {
      strike:       picked.strike,
      expiry:       picked.expiry,
      right:        picked.right,
      mid:          picked.price,
      delta:        picked.delta,
      theta:        picked.theta,
      ivRank:       picked.ivRank,
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
 *  narrowing it away. */
export function mergePlan(card: OverriddenCard, plan: RecomputedPlanShape): OverriddenCard {
  return { ...card, entry: plan.entry, exit: plan.exit, rrRatio: plan.rrRatio, rrModel: plan.rrModel };
}

/**
 * Resolve every basket symbol to its (possibly overridden, possibly
 * plan-merged) card. Any overridden symbol whose plan isn't cached yet for its
 * CURRENT contract key is excluded from the returned list and flips
 * `pending` — this is the gate that must block "Send to broker" so an order
 * can never go out carrying an overridden contract whose Entry/Exit/RR still
 * describe the auto-pick.
 */
export function resolveBasketCards(
  basket: string[],
  cardIndex: Record<string, TradeCardData>,
  pickedContracts: Record<string, string>,
  contractsBySymbol: Record<string, OptionContract[]>,
  plansBySymbol: Record<string, PlanEntry>,
): { cards: TradeCardData[]; pending: boolean } {
  let pending = false;
  const cards: TradeCardData[] = [];
  for (const sym of basket) {
    const raw = cardIndex[sym];
    if (!raw) continue;
    const pickedId = pickedContracts[sym];
    const picked = pickedId ? contractsBySymbol[sym]?.find((c) => c.id === pickedId) : undefined;
    const resolved = applyPickedContract(raw, picked);
    if (!resolved._userOverride) {
      cards.push(resolved);
      continue;
    }
    const key = contractKeyFor(resolved);
    const entry = plansBySymbol[sym];
    if (entry && entry.key === key) {
      cards.push(mergePlan(resolved, entry.plan));
    } else {
      pending = true;
    }
  }
  return { cards, pending };
}

const RR_OVERRIDE_KEYS = [
  'rr_bullish_target_pct', 'rr_bearish_target_pct',
  'rr_bullish_invalidation_pct', 'rr_bearish_invalidation_pct',
] as const;

/** Pull just the four Reward/Risk override keys out of scanOverrides, dropping
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

/** One cached "Check structure" result, keyed by SYMBOL — the structural level is
 *  a function of (symbol, direction, stock_price) only; the contract never reaches
 *  api.getStructuralStop. `stop: null` is a real, cacheable answer ("checked, no
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
  symbol: string,
  stop: StructuralStop | null | undefined,
  stockPrice: number | null,
): Record<string, CachedStructural> {
  if (stop === undefined) return prev;
  const cur = prev[symbol];
  if (cur && cur.stop === stop && cur.stockPrice === stockPrice) return prev;
  return { ...prev, [symbol]: { stop, stockPrice } };
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
