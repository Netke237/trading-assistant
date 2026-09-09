/**
 * EDITED-FLAG-2026-09-04 — the card-level "edited" indicator's rule.
 *
 * The defect these tests exist to pin is the one that made a straight value
 * comparison (the deleted `isDirty`) unsafe to reinstate: `mergePlan` moves the
 * plan under a live card WITHOUT changing `data.contract`, so the four overlay
 * fields with no follow-the-seed effect would read as "edited" on a card nobody
 * touched. Every "untouched field, plan moved" case below fails against a
 * value-only rule.
 */
import {
  DEFAULT_CONTRACTS,
  EDITABLE_FIELDS,
  FIELD_LABELS,
  NO_EDITS,
  type EditOverlay,
  type EditedFields,
  editedFields,
  markEdited,
  planOverlay,
  restoredEdits,
} from '../tradeCardEdits';
import type { TradeCardData } from '@/types/domain';

const PLAN: EditOverlay = {
  entryLimit: 4.00,
  maxFill: 4.20,
  invalidation: 140,
  premiumStop: 2.40,
  timeStopDays: 18,
  targets: [190, 200],
  contracts: DEFAULT_CONTRACTS,
};

const overlayOf = (over: Partial<EditOverlay> = {}): EditOverlay => ({ ...PLAN, ...over });
const editedOf = (over: Partial<EditedFields> = {}): EditedFields => ({ ...NO_EDITS, ...over });

// ── planOverlay ─────────────────────────────────────────────────────────────

describe('planOverlay', () => {
  const data = {
    entry: { limit: 4.00, maxFill: 4.20 },
    exit: {
      invalidation: 140,
      premiumStop: 2.40,
      timeStopDays: 18,
      targets: [{ stockPrice: 188, targetPrice: 190 }, { stockPrice: 200 }],
    },
  } as unknown as TradeCardData;

  it('reads the plan out of the card CURRENT data, targetPrice winning over stockPrice', () => {
    expect(planOverlay(data)).toEqual(PLAN);
  });

  it('measures contracts against the constant, NOT the parent-supplied size', () => {
    // ROUND 1 FINDING. step-7-trade-card/page.tsx writes
    // orderContractsBySymbol from handleEditsChange unconditionally and feeds
    // it straight back as the `contracts` prop, so a baseline taken from that
    // prop is the user's own edit and can never differ from itself.
    expect(planOverlay(data).contracts).toBe(DEFAULT_CONTRACTS);
  });

  it('falls back to stockPrice when the backend sent no targetPrice', () => {
    expect(planOverlay(data).targets).toEqual([190, 200]);
  });
});

// ── editedFields: the two-halves rule ───────────────────────────────────────

describe('editedFields', () => {
  it('is empty on a card nobody has touched', () => {
    expect(editedFields(overlayOf(), PLAN, NO_EDITS)).toEqual([]);
  });

  it('names a field the user changed and left differing', () => {
    expect(editedFields(overlayOf({ entryLimit: 3.50 }), PLAN, editedOf({ entryLimit: true })))
      .toEqual(['entryLimit']);
  });

  it.each(EDITABLE_FIELDS.filter((f) => f !== 'targets'))(
    'does NOT flag %s when the plan moved under it and the user never touched it',
    (field) => {
      // THE REGRESSION. mergePlan swaps data.exit wholesale without changing
      // data.contract, so maxFill / timeStopDays / targets / contracts keep
      // their old seed while the plan moves. A value-only rule says "edited".
      const stale = overlayOf({ [field]: (PLAN[field] as number) + 1 } as Partial<EditOverlay>);
      expect(editedFields(stale, PLAN, NO_EDITS)).toEqual([]);
    },
  );

  it('does NOT flag targets when the plan moved under them and the user never touched them', () => {
    expect(editedFields(overlayOf({ targets: [111, 222] }), PLAN, NO_EDITS)).toEqual([]);
  });

  it('drops a touched field the user typed back to the plan value', () => {
    // The decision's own wording: the indicator says the card DIFFERS from the
    // plan, not that a keystroke once happened.
    expect(editedFields(overlayOf(), PLAN, editedOf({ premiumStop: true }))).toEqual([]);
  });

  it('drops a touched field when the plan MOVES onto the typed value', () => {
    const overlay = overlayOf({ entryLimit: 3.50 });
    const movedPlan = { ...PLAN, entryLimit: 3.50 };
    expect(editedFields(overlay, movedPlan, editedOf({ entryLimit: true }))).toEqual([]);
  });

  it('keeps flagging a touched field the plan moved AWAY from', () => {
    const overlay = overlayOf({ entryLimit: 3.50 });
    const movedPlan = { ...PLAN, entryLimit: 6.00 };
    expect(editedFields(overlay, movedPlan, editedOf({ entryLimit: true }))).toEqual(['entryLimit']);
  });

  it('compares targets element-wise and by length', () => {
    const touched = editedOf({ targets: true });
    expect(editedFields(overlayOf({ targets: [190, 200] }), PLAN, touched)).toEqual([]);
    expect(editedFields(overlayOf({ targets: [190, 201] }), PLAN, touched)).toEqual(['targets']);
    expect(editedFields(overlayOf({ targets: [190] }), PLAN, touched)).toEqual(['targets']);
    expect(editedFields(overlayOf({ targets: [190, 200, 210] }), PLAN, touched)).toEqual(['targets']);
  });

  it('returns fields in EDITABLE_FIELDS order, not the order they were edited', () => {
    const overlay = overlayOf({ premiumStop: 1.00, entryLimit: 3.50, contracts: 9 });
    const got = editedFields(overlay, PLAN, editedOf({ premiumStop: true, entryLimit: true, contracts: true }));
    expect(got).toEqual(['entryLimit', 'contracts', 'premiumStop']);
  });

  it('has a label for every editable field', () => {
    for (const f of EDITABLE_FIELDS) expect(FIELD_LABELS[f]).toBeTruthy();
  });
});

// ── markEdited: only a CHANGE counts ────────────────────────────────────────

describe('markEdited', () => {
  it('flags a key whose value actually differs', () => {
    expect(markEdited(NO_EDITS, { entryLimit: 3.50 }, PLAN).entryLimit).toBe(true);
  });

  it('does NOT flag a key re-sent unchanged', () => {
    // EditableKV's save-on-blur re-sends the current value. Recording that as
    // "the user chose this" is how a seeded default came to be posted as a
    // deliberate premium stop — the same rule patch() applies to touchedRef.
    expect(markEdited(NO_EDITS, { premiumStop: PLAN.premiumStop }, PLAN)).toBe(NO_EDITS);
  });

  it('does NOT flag the untouched fields that ride along in the same partial', () => {
    // patch() carries only a partial, but the overlay it produces carries
    // everything; a key merely being PRESENT is not the user choosing it.
    const next = markEdited(NO_EDITS, { contracts: 5, entryLimit: PLAN.entryLimit }, PLAN);
    expect(next.contracts).toBe(true);
    expect(next.entryLimit).toBe(false);
  });

  it('returns the IDENTICAL prev when nothing changed, so a no-op cannot re-render', () => {
    const prev = editedOf({ entryLimit: true });
    expect(markEdited(prev, {}, PLAN)).toBe(prev);
    expect(markEdited(prev, { entryLimit: 3.50 }, PLAN)).toBe(prev);
  });

  it('compares targets element-wise', () => {
    expect(markEdited(NO_EDITS, { targets: [190, 200] }, PLAN)).toBe(NO_EDITS);
    expect(markEdited(NO_EDITS, { targets: [190, 205] }, PLAN).targets).toBe(true);
  });
});

// ── restoredEdits ───────────────────────────────────────────────────────────

describe('restoredEdits', () => {
  const restore = (over: Partial<Parameters<typeof restoredEdits>[0]> = {}) => restoredEdits({
    entryLimit: null, invalidation: null, premiumStop: null, contracts: DEFAULT_CONTRACTS, ...over,
  });

  it('treats a restored cached value as a previous edit, like touchedRef does', () => {
    const got = restore({ entryLimit: 3.5, invalidation: null, premiumStop: undefined });
    expect(got.entryLimit).toBe(true);
    expect(got.invalidation).toBe(false);
    expect(got.premiumStop).toBe(false);
  });

  it('leaves every field with no cache of its own clear', () => {
    const got = restore({ entryLimit: 1, invalidation: 2, premiumStop: 3 });
    expect(got.maxFill).toBe(false);
    expect(got.timeStopDays).toBe(false);
    expect(got.targets).toBe(false);
  });

  it('treats a restored 0 as an edit, not as absent', () => {
    // `!= null`, not falsiness — the same character-for-character check
    // touchedRef seeds with.
    expect(restore({ entryLimit: 0, invalidation: 0, premiumStop: 0 }))
      .toEqual({ ...NO_EDITS, entryLimit: true, invalidation: true, premiumStop: true });
  });

  it('restores contracts BY VALUE, since its cache carries no null sentinel', () => {
    // The count is only ever written by a user edit, so a card mounting at
    // anything but the default is resuming one.
    expect(restore({ contracts: DEFAULT_CONTRACTS }).contracts).toBe(false);
    expect(restore({ contracts: 7 }).contracts).toBe(true);
  });
});
