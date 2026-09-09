/*
 * The card-level "edited" indicator for Step 7's TradeCard
 * (decision EDITED-FLAG-2026-09-04).
 *
 * This is NOT a revert of the removal that deleted `isDirty` alongside the
 * "Projected R/R (+8% stock move)" readout — that readout stays gone, and
 * `computeEditedRR`'s delta approximation is not resurrected here. What the
 * decision asked for is a card-level indicator that an overlay field differs
 * from the scan's plan, independent of both. The comparison lives in this file
 * rather than inline in the card so the rule can be tested without a render.
 *
 * WHY "TOUCHED **AND** DIFFERENT", NOT VALUE COMPARISON ALONE
 *
 * The deleted `isDirty` compared the overlay against `data` and nothing else.
 * That is not safe to reinstate as-is, because the plan moves under the
 * overlay: `mergePlan` replaces `data.exit` wholesale after a contract
 * override resolves, WITHOUT changing `data.contract`, so TradeCard's
 * contract-change reset does not re-seed. Three fields survive that because
 * they have follow-the-seed effects while untouched (entryLimit, invalidation,
 * premiumStop); `maxFill`, `timeStopDays`, `targets` and `contracts` do not.
 * A pure value comparison would therefore raise "Edited" on a card nobody
 * edited, the moment a plan landed under one of those four.
 *
 * So a field counts as edited only when BOTH hold:
 *   1. the user actually changed it on this card (`EditedFields`), and
 *   2. its current value still differs from the plan's CURRENT value.
 *
 * (2) is what keeps the indicator honest in the other direction, and is the
 * half that implements the decision's own wording: a field typed back to the
 * plan's value — or cleared, which `TradeCard.revert` turns into exactly that
 * plus a cleared flag (CLEAR-TO-INHERIT-2026-09-05) — is inheriting again, so
 * it does not count.
 *
 * TWO OF THE SIX FIELDS THE DECISION NAMES CANNOT FIRE TODAY, BY DESIGN.
 * `maxFill` and `timeStopDays` are rendered read-only (plain `KV` rows reading
 * `data.*` directly) because MAXFILL-TIMESTOP-2026-09-05 defers threading
 * them, so nothing can ever set their flag. They are carried here anyway
 * rather than special-cased out: the rule is generic, and if either is ever
 * made editable it starts counting with no change to this file.
 *
 * `targets` IS included, and is the one field the decision's parenthetical
 * does not name. It is editable today (TradeCard's TargetRow writes
 * `patch({ targets })`), so leaving it out would print "not edited" on a card
 * whose targets the user had just retyped. Flagged for Kenneth rather than
 * decided silently.
 */
import type { TradeCardData } from '@/types/domain';

/** The user-editable overlay Step 7's TradeCard keeps over the scan's plan.
 *  Defined here (rather than in the card) so the comparison below and the card
 *  cannot drift apart on the field list. */
export interface EditOverlay {
  entryLimit: number;
  maxFill: number;
  invalidation: number;
  premiumStop: number;
  timeStopDays: number;
  targets: number[];
  contracts: number;
}

export type EditableField = keyof EditOverlay;

/** Field order here is the order the indicator's tooltip lists them in, and it
 *  follows the card top-to-bottom: entry strip, then the exit block. */
export const EDITABLE_FIELDS: readonly EditableField[] = [
  'entryLimit', 'maxFill', 'contracts', 'invalidation', 'premiumStop', 'timeStopDays', 'targets',
] as const;

/** Whether the user has changed each overlay field on the card currently on
 *  screen. Distinct from `TouchedFields` in TradeCard, which covers only the
 *  three fields a SEND path reads and is reported to the parent — this one is
 *  card-local display state and covers every field. The three they share are
 *  written in the same statements, so they cannot disagree. */
export type EditedFields = Record<EditableField, boolean>;

export const NO_EDITS: EditedFields = {
  entryLimit: false, maxFill: false, contracts: false, invalidation: false,
  premiumStop: false, timeStopDays: false, targets: false,
};

/** Labels as the card itself spells them, so the tooltip names what the user
 *  can see. "Time stop" and "Max fill" match their read-only `KV` rows. */
export const FIELD_LABELS: Record<EditableField, string> = {
  entryLimit:   'Entry limit',
  maxFill:      'Max fill',
  contracts:    'Contracts',
  invalidation: 'Invalidation',
  premiumStop:  'Premium stop',
  timeStopDays: 'Time stop',
  targets:      'Targets',
};

/** The contract count the scan plans. There is no scan-supplied size — the
 *  backend never sends one — so the plan is the card's own default, and
 *  TradeCard's `defaultOverlay` seeds from this same constant so the two
 *  cannot drift. */
export const DEFAULT_CONTRACTS = 1;

/**
 * The plan the overlay is measured against: the card's CURRENT data, not the
 * data it mounted with. That is deliberate — `mergePlan` is allowed to move
 * it, and when it does, an untouched field follows it (so nothing flags) while
 * a touched field is compared against the new plan (so the flag reflects what
 * the user would actually be overriding now).
 *
 * `contracts` IS NOT `initialContracts`, and that is the whole point.
 *
 * ROUND 1 FINDING. It was, briefly, on the reasoning the deleted `isDirty`
 * recorded: the parent seeds a shared per-symbol size, so comparing against a
 * literal 1 would flag a card the parent had sized. That reasoning belonged to
 * `isDirty`'s pure value comparison and does not survive the touched half of
 * this rule — but taking `initialContracts` as the baseline broke the field
 * outright, because of where that prop comes from.
 *
 * `step-7-trade-card/page.tsx` writes `orderContractsBySymbol` from
 * `handleEditsChange` UNCONDITIONALLY (`{ ...prev, [symbol]: overlay.contracts }`),
 * unlike the three caches beside it, which write `null` unless `meta.touched`
 * says the user typed. It then feeds that map straight back in as this very
 * prop. So the moment the user edits Contracts, the "plan" became the edit:
 * overlay 7 vs baseline 7, no difference, no badge — for the one field whose
 * count reaches a broker order. The card was silent on the edit it exists to
 * announce.
 *
 * Comparing against the constant is safe here precisely because a value alone
 * never raises the flag: a card that MOUNTS at 7 has `edited.contracts` set by
 * `restoredEdits` instead, which is truthful, since the user is the only thing
 * that ever writes a count into that map.
 */
export function planOverlay(data: TradeCardData): EditOverlay {
  return {
    entryLimit:   data.entry.limit,
    maxFill:      data.entry.maxFill,
    invalidation: data.exit.invalidation,
    premiumStop:  data.exit.premiumStop,
    timeStopDays: data.exit.timeStopDays,
    targets:      data.exit.targets.map((t) => t.targetPrice ?? t.stockPrice),
    contracts:    DEFAULT_CONTRACTS,
  };
}

function targetsDiffer(a: readonly number[], b: readonly number[]): boolean {
  if (a.length !== b.length) return true;
  return a.some((v, i) => v !== b[i]);
}

function fieldDiffers(field: EditableField, overlay: EditOverlay, plan: EditOverlay): boolean {
  if (field === 'targets') return targetsDiffer(overlay.targets, plan.targets);
  return overlay[field] !== plan[field];
}

/**
 * Which fields the user has edited AND left differing from the plan, in
 * `EDITABLE_FIELDS` order. An empty array means the card is inheriting the
 * plan everywhere and the indicator does not render.
 */
export function editedFields(
  overlay: EditOverlay,
  plan: EditOverlay,
  edited: EditedFields,
): EditableField[] {
  return EDITABLE_FIELDS.filter((f) => edited[f] && fieldDiffers(f, overlay, plan));
}

/**
 * Fold one `patch()` into the edited-field record.
 *
 * Mirrors `patch`'s own rule for `TouchedFields` and for the same reason: a
 * patch carries a partial, but any caller may re-send a value unchanged
 * (EditableKV's save-on-blur did), and a key merely being PRESENT is not the
 * user choosing it. Only a key whose value actually differs from the overlay
 * it is being applied to counts.
 *
 * Returns the identical `prev` when nothing changed, so a no-op patch cannot
 * re-render the card through this state.
 */
export function markEdited(
  prev: EditedFields,
  partial: Partial<EditOverlay>,
  current: EditOverlay,
): EditedFields {
  let next: EditedFields | null = null;
  for (const f of EDITABLE_FIELDS) {
    const incoming = partial[f];
    if (incoming === undefined || prev[f]) continue;
    const changed = f === 'targets'
      ? targetsDiffer(incoming as number[], current.targets)
      : incoming !== current[f];
    if (changed) next = { ...(next ?? prev), [f]: true };
  }
  return next ?? prev;
}

/**
 * The record a card mounts (or resets) with. A cached value arriving from the
 * parent IS a previous edit on this card restored — the same reading
 * `touchedRef` applies to the same three props — so it starts flagged, and
 * `editedFields` then decides whether it still differs from the plan.
 *
 * `contracts` is carried here too, though `touchedRef` does not track it: see
 * `planOverlay` for why its baseline is the constant and its restore is by
 * value.
 */
export function restoredEdits(restored: {
  entryLimit: number | null | undefined;
  invalidation: number | null | undefined;
  premiumStop: number | null | undefined;
  contracts: number;
}): EditedFields {
  // `!= null` (loose), matching `touchedRef`'s own seeding character for
  // character — the two are seeded from the SAME three props, and a card that
  // considered a prop restored for one and absent for the other is exactly the
  // drift this file's `EditedFields` doc comment says cannot happen.
  return {
    ...NO_EDITS,
    entryLimit:   restored.entryLimit != null,
    invalidation: restored.invalidation != null,
    premiumStop:  restored.premiumStop != null,
    // `contracts` restores by VALUE rather than by a null sentinel, because
    // its cache has none: `orderContractsBySymbol` holds a bare number and is
    // written on every patch. A count other than the default can only have got
    // there through a user edit, so a card mounting at one is resuming that
    // edit — the same reading the three above apply to their own caches.
    contracts:    restored.contracts !== DEFAULT_CONTRACTS,
  };
}
