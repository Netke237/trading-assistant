// Phase G (piece 5, D4/D5) build step 2 — the per-scan CARD EDIT slices.
//
// Spec: docs/superpowers/plans/2026-09-14-phase-g-per-trade-method-pick-spec.md
// §5 and §5.1. Read §5.1 before changing anything here; it is the argument for
// why this file exists in the shape it does.
//
// THE ONE IDEA. Every user edit made on a trade card belongs to the SCAN it was
// made against, and the slice carries that scan's id as a STAMP. A read whose
// stamp does not match the scan currently in the store returns EMPTY. That is
// the whole invalidation mechanism: a scan landing anywhere, by any path that
// exists today or is added later, changes `scan_id` and thereby makes every
// older edit unreadable. There is nothing to remember to call.
//
// WHY NOT A RESET CALL. §5.1 records that two drafts of this design each named
// a reset site and each was wrong — the second one asserted a stocks path that
// `return`s three lines above the call it claimed to reach. A reset that must
// be invoked from every scan-landing site is only ever as correct as the last
// enumeration of those sites, and this codebase already carries the fossil of
// that approach: `scanStore.clearPickedContracts` has ZERO production callers.
// So no reset action is exported here. If you are about to add one, you are
// about to reintroduce the defect the stamp removes.
//
// PURE FUNCTIONS, DELIBERATELY. The store wires these in; the rules themselves
// live here so they are unit-testable in isolation rather than as inline
// closures inside a zustand `set`. Same precedent, same reason, as
// `lib/tradeCardOverride.ts`.

import type { MaxLossOverride, MethodPick } from '@/types/domain';

export type CardEditMode = 'options' | 'stocks';

/** One scan's worth of user edits for one screener mode.
 *
 *  TWO SLICES, NOT ONE (§5). Options and stocks have independent results
 *  (`scanResult` / `stockScanResult`) and therefore independent `scan_id`s. A
 *  single stamped slice would reset on every mode toggle and throw away edits
 *  the user had not finished with.
 *
 *  KEYING (§5). In options mode the three contract-scoped maps (`picks`,
 *  `premiumStop`, `entryLimit`) are keyed by CONTRACT — `contractKeyFor`, i.e.
 *  `SYMBOL|strike|expiry|right`, the same identity `exitPlanByContract` and
 *  `estimatesByContract` use — and the two underlying-scoped maps
 *  (`invalidation`, `maxLossOverride`) by SYMBOL. That split is not cosmetic:
 *  an invalidation is a price level on the UNDERLYING, the same thesis
 *  whichever strike expresses it, while a premium stop or a picked target row
 *  is meaningful only against one contract's numbers. In stocks mode there is
 *  no contract, so everything is symbol-keyed.
 *
 *  `null` in the three number/override maps means "the user has not touched
 *  this field", which is a DISTINCT state from any value — see the step-7
 *  page's own notes on why a cached seed is not the same as a typed one.
 *  `picks` has no such state: a key is present only if a human picked. */
export interface CardEditSlice {
  /** The `scan_id` these edits were made against. Both result types carry a
   *  required one: `ScanResult.scan_id` (lib/scanStore.ts — NOT types/domain.ts,
   *  which has no scan_id) and `StockScanResult.scan_id` (types/stockDomain.ts).
   *  `null` means "stamped with nothing", which reads as EMPTY and never as
   *  "matches everything". */
  scanId:          string | null;
  picks:           Record<string, MethodPick>;
  invalidation:    Record<string, number | null>;
  premiumStop:     Record<string, number | null>;
  entryLimit:      Record<string, number | null>;
  maxLossOverride: Record<string, MaxLossOverride | null>;
}

/** The five writable maps. `scanId` is not among them — it is set by the
 *  writer from the store, never by a caller. */
export type CardEditField = Exclude<keyof CardEditSlice, 'scanId'>;

/** The value type of one entry in one of those maps, so a writer cannot put a
 *  `MethodPick` in `entryLimit` or a number in `picks`. */
export type CardEditValue<F extends CardEditField> = CardEditSlice[F][string];

export function emptyCardEdits(): CardEditSlice {
  return {
    scanId:          null,
    picks:           {},
    invalidation:    {},
    premiumStop:     {},
    entryLimit:      {},
    maxLossOverride: {},
  };
}

/** What every mismatched read returns.
 *
 *  ONE SHARED FROZEN OBJECT, and both halves of that matter. Shared, because
 *  zustand v5 compares selector results with `Object.is`: a selector returning
 *  a fresh `{}` on every call re-renders forever. Frozen, because a caller that
 *  writes into the empty slice would corrupt every future mismatched read — and
 *  in a module (always strict mode) that write throws instead of silently
 *  landing. */
export const EMPTY_CARD_EDITS: CardEditSlice = Object.freeze({
  scanId:          null,
  picks:           Object.freeze({}) as Record<string, MethodPick>,
  invalidation:    Object.freeze({}) as Record<string, number | null>,
  premiumStop:     Object.freeze({}) as Record<string, number | null>,
  entryLimit:      Object.freeze({}) as Record<string, number | null>,
  maxLossOverride: Object.freeze({}) as Record<string, MaxLossOverride | null>,
});

/** The subset of `ScanStoreState` these functions read. Typed structurally so
 *  this module does not import the store that imports it. */
export interface CardEditsHost {
  /** Both fields are declared REQUIRED on `ScanResult`/`StockScanResult` and
   *  are optional here on purpose: a result restored from an old localStorage
   *  blob can be missing either, and this module's job is to survive that
   *  rather than to trust the declaration. A type with both required is still
   *  assignable to this one. */
  scanResult:       { scan_id?: string; timestamp?: string } | null;
  stockScanResult:  { scan_id?: string; timestamp?: string } | null;
  optionsCardEdits: CardEditSlice;
  stocksCardEdits:  CardEditSlice;
}

/** The scan a given mode's edits would belong to RIGHT NOW.
 *
 *  THE SINGLE DERIVATION, used by both the reader and the writer. The spec's
 *  draft signature had the writer take `scanId` as a parameter; it is derived
 *  here instead, and the reason is the design's own: a caller that passes a
 *  stale or wrong id writes an edit under a stamp the reader will reject, so
 *  the edit vanishes silently — exactly the class of defect the stamp exists to
 *  make impossible. No caller has a better source for this than the store does
 *  (`TradeCardData` carries no scan_id; only the two result objects do), so the
 *  parameter bought nothing and cost a way to get it wrong. Recorded as a
 *  deliberate deviation in PHASE-G-STEP2-STAMP-DERIVED-2026-09-14.
 *
 *  An empty-string id is treated as NO scan, not as a stamp. A backend that
 *  emitted `''` would otherwise give every slice a stamp that matches every
 *  other empty-stamped slice.
 *
 *  FALLS BACK TO `timestamp`, and that is not belt-and-braces -- it is reachable.
 *  `scan_id` entered the frontend's `ScanResult` on 2026-08-28 (ac84e93d) and no
 *  store migration backfills it, so a localStorage blob written before that date
 *  restores a result with no id. Without the fallback every card edit on such a
 *  session would be DROPPED while the card still displayed it: the user types
 *  $2.71, the card shows $2.71, and the order carries the card's original $2.50.
 *  That display-vs-send disagreement is the exact defect class step 7 has spent
 *  four rounds closing, and it is worse than the staleness the stamp prevents.
 *  `timestamp` is required on both result types, has been present far longer,
 *  and changes per scan -- so it is a working stamp, not a sentinel that matches
 *  everything. Null is left for a result carrying neither, which is not a result. */
export function currentScanIdFor(state: CardEditsHost, mode: CardEditMode): string | null {
  const result = mode === 'options' ? state.scanResult : state.stockScanResult;
  return nonEmpty(result?.scan_id) ?? nonEmpty(result?.timestamp) ?? null;
}

function nonEmpty(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

/** THE ONLY WAY TO READ A SLICE. Returns the live slice when its stamp matches
 *  the scan currently in the store, and the shared empty slice otherwise — so
 *  no caller can ever see a foreign scan's edits.
 *
 *  Do not reach for `state.optionsCardEdits` directly. A direct slice read that
 *  skips the `scan_id` check is the whole defect this design exists to prevent
 *  (spec §12 step 2 says so in those words). */
export function selectCardEdits(state: CardEditsHost, mode: CardEditMode): CardEditSlice {
  const slice = mode === 'options' ? state.optionsCardEdits : state.stocksCardEdits;
  const current = currentScanIdFor(state, mode);
  // `slice?.scanId == null` also covers a slice that is missing or malformed in
  // a hand-edited localStorage blob: unreadable beats throwing on `.scanId`.
  if (current == null || slice?.scanId == null || slice.scanId !== current) {
    return EMPTY_CARD_EDITS;
  }
  return slice;
}

/** Write one entry, stamping the current scan.
 *
 *  Three rules, in this order, and the order is load-bearing:
 *
 *  1. NO SCAN, NO WRITE. With no scan in the store there is no stamp to write
 *     under, and a null-stamped slice reads as empty — so storing the edit
 *     would be silent loss wearing the costume of a save. Dropping it is at
 *     least visible: the field reverts in front of the user.
 *  2. STAMP MISMATCH RESETS FIRST. A write under a new scan starts from an
 *     empty slice, so it cannot land beside edits from the old one.
 *  3. AN UNCHANGED WRITE RETURNS `slice` ITSELF. The step-7 card reports its
 *     whole overlay on every patch, so without this guard each render would
 *     produce a new slice object and re-trigger the cascade. This is the same
 *     identity guard the `useState` caches carried inline before the move, kept
 *     because the reason for it did not change. It is checked only once the
 *     stamp is known to match — an unchanged VALUE under a stale STAMP must
 *     still reset. */
export function writeCardEdit<F extends CardEditField>(
  slice: CardEditSlice,
  scanId: string | null,
  field: F,
  key: string,
  value: CardEditValue<F>,
): CardEditSlice {
  if (scanId == null) return slice;

  const stampMatches = slice.scanId === scanId;
  if (stampMatches && key in slice[field] && Object.is(slice[field][key], value)) {
    return slice;
  }
  const base: CardEditSlice = stampMatches
    ? { ...slice }
    : { ...emptyCardEdits(), scanId };
  // The cast is the price of one generic writer instead of five near-identical
  // ones — and five is how a sixth gets added that forgets to stamp. `F` pins
  // both sides: the spread is `CardEditSlice[F]` and `value` is its entry type.
  base[field] = { ...base[field], [key]: value } as CardEditSlice[F];
  return base;
}

/** Drop every pick for `symbol` except the one under `keepKey` (spec test 12).
 *
 *  BY SYMBOL PREFIX, not by the outgoing contract id, and that is wider than
 *  the test's wording on purpose. Step 6 can switch away from a contract that
 *  was never an explicit override — the AUTO-PICK — and in that case the store
 *  holds no previous id to clear by. Only one contract per symbol is ever the
 *  active card, so every OTHER pick under that symbol is by definition a
 *  judgement about numbers no longer on screen.
 *
 *  Only `picks` is cleared. `premiumStop` and `entryLimit` are contract-keyed
 *  too and are deliberately left, preserving today's behaviour: switch back to
 *  a contract and the limit you typed for it is still there. A pick is treated
 *  differently because it names ONE target row out of a specific plan, and
 *  `pickedAt` exists precisely because a pick can go stale in a way a typed
 *  limit price cannot. */
export function clearPicksForSymbol(
  slice: CardEditSlice,
  symbol: string,
  keepKey: string | null,
): CardEditSlice {
  const doomed = Object.keys(slice.picks).filter((k) => {
    if (k === keepKey) return false;
    const i = k.indexOf('|');
    return (i === -1 ? k : k.slice(0, i)) === symbol;
  });
  if (doomed.length === 0) return slice;   // identity guard, as above
  const picks = { ...slice.picks };
  for (const k of doomed) delete picks[k];
  return { ...slice, picks };
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

/** Coerce a persisted blob's slice back into a well-formed one.
 *
 *  SHAPE ONLY — this does not validate that a stored `MethodPick` is a real
 *  pick, and does not try to. What it guarantees is that the five maps are
 *  objects and `scanId` is a non-empty string or null, so `selectCardEdits`
 *  cannot throw and a corrupt stamp cannot read as "matches everything". A
 *  wrong-shaped entry that survives this is still gated by the stamp, and the
 *  worst it can do is render as an untouched field. */
export function normalizeCardEdits(value: unknown): CardEditSlice {
  const raw = asRecord(value);
  return {
    scanId: typeof raw.scanId === 'string' && raw.scanId.length > 0 ? raw.scanId : null,
    picks:           asRecord(raw.picks)           as Record<string, MethodPick>,
    invalidation:    asRecord(raw.invalidation)    as Record<string, number | null>,
    premiumStop:     asRecord(raw.premiumStop)     as Record<string, number | null>,
    entryLimit:      asRecord(raw.entryLimit)      as Record<string, number | null>,
    maxLossOverride: asRecord(raw.maxLossOverride) as Record<string, MaxLossOverride | null>,
  };
}
