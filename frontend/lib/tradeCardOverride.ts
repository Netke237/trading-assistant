/*
 * Pure helpers for Step 7's contract-override + recompute-plan machinery.
 * Extracted out of the page component so the exact logic that determines
 * "which contract/plan does this order actually carry" is unit-testable —
 * this is what silently broke for the basket "Send to broker" flow (the
 * override reached the single-card buttons but not the basket path, since
 * the basket cards were built straight from the raw scan candidates).
 */
import type { TradeCardData, OptionContract } from '@/types/domain';

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
