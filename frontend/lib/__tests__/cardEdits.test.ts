// Phase G piece 5, build step 2 — the stamp's rules, tested where they live.
// The store-level spec tests (11, 11b, 12, 15) are in scanStoreCardEdits.test.ts.

import {
  EMPTY_CARD_EDITS, clearCardPick, clearPicksForSymbol, currentScanIdFor, emptyCardEdits,
  armPickedFieldsFrom, normalizeCardEdits, pickedFieldsFrom, selectCardEdits, writeCardEdit,
} from '@/lib/cardEdits';
import type { CardEditsHost, CardEditSlice } from '@/lib/cardEdits';
import type { MethodPick } from '@/types/domain';

const pick = (method: MethodPick['method'] = 'monte_carlo'): MethodPick => ({
  method,
  rowStockPrice: 197.5,
  rowOptionPrice: 6.24,
  stopBasis: 'stock',
  pickedAt: '2026-09-14T10:00:00.000Z',
});

const host = (over: Partial<CardEditsHost> = {}): CardEditsHost => ({
  scanResult: null,
  stockScanResult: null,
  optionsCardEdits: emptyCardEdits(),
  stocksCardEdits: emptyCardEdits(),
  ...over,
});

const stamped = (scanId: string | null, over: Partial<CardEditSlice> = {}): CardEditSlice => ({
  ...emptyCardEdits(), scanId, ...over,
});

describe('currentScanIdFor', () => {
  it('reads the mode’s own result, not the other mode’s', () => {
    const h = host({
      scanResult: { scan_id: 'opt-1' },
      stockScanResult: { scan_id: 'stk-1' },
    });
    expect(currentScanIdFor(h, 'options')).toBe('opt-1');
    expect(currentScanIdFor(h, 'stocks')).toBe('stk-1');
  });

  it('is null with no result', () => {
    expect(currentScanIdFor(host(), 'options')).toBeNull();
    expect(currentScanIdFor(host(), 'stocks')).toBeNull();
  });

  // An empty id would otherwise be a stamp that matches every other
  // empty-stamped slice — the "matches everything" failure test 15 names.
  it('treats an empty-string scan_id as NO scan', () => {
    expect(currentScanIdFor(host({ scanResult: { scan_id: '', timestamp: '' } }), 'options')).toBeNull();
  });

  // Reachable: `scan_id` entered the frontend ScanResult on 2026-08-28 and no
  // migration backfills it, so an older persisted blob restores without one.
  // Dropping every edit there would show the user a typed level the order does
  // not carry — see currentScanIdFor's own note.
  it('falls back to timestamp when the restored result has no scan_id', () => {
    const h = host({ scanResult: { timestamp: '2026-08-01T10:00:00Z' } });
    expect(currentScanIdFor(h, 'options')).toBe('2026-08-01T10:00:00Z');
  });

  it('prefers scan_id over timestamp when both are present', () => {
    const h = host({ scanResult: { scan_id: 'A', timestamp: '2026-08-01T10:00:00Z' } });
    expect(currentScanIdFor(h, 'options')).toBe('A');
  });

  it('is null for a result carrying neither', () => {
    expect(currentScanIdFor(host({ scanResult: {} }), 'options')).toBeNull();
  });

  // The fallback must still be a WORKING stamp, not a sentinel: two scans with
  // different timestamps must not read each other's edits.
  it('the timestamp fallback still invalidates across scans', () => {
    const slice = stamped('2026-08-01T10:00:00Z', { entryLimit: { k: 2.71 } });
    expect(
      selectCardEdits(host({ scanResult: { timestamp: '2026-08-01T10:00:00Z' }, optionsCardEdits: slice }), 'options'),
    ).toBe(slice);
    expect(
      selectCardEdits(host({ scanResult: { timestamp: '2026-08-02T10:00:00Z' }, optionsCardEdits: slice }), 'options'),
    ).toBe(EMPTY_CARD_EDITS);
  });
});

describe('selectCardEdits', () => {
  it('returns the live slice when the stamp matches', () => {
    const slice = stamped('A', { picks: { 'AAPL|190|2027-01-15|C': pick() } });
    const h = host({ scanResult: { scan_id: 'A' }, optionsCardEdits: slice });
    expect(selectCardEdits(h, 'options')).toBe(slice);
  });

  it('returns EMPTY when the stamp is for a different scan', () => {
    const slice = stamped('A', { entryLimit: { k: 2.71 } });
    const h = host({ scanResult: { scan_id: 'B' }, optionsCardEdits: slice });
    expect(selectCardEdits(h, 'options')).toBe(EMPTY_CARD_EDITS);
    expect(selectCardEdits(h, 'options').entryLimit).toEqual({});
  });

  // Test 15's second half, at the unit level: a null stamp reads as empty even
  // when there is no scan either, so `null === null` never becomes a match.
  it('returns EMPTY for a null stamp, including against a null current scan', () => {
    const slice = stamped(null, { entryLimit: { k: 2.71 } });
    expect(selectCardEdits(host({ optionsCardEdits: slice }), 'options')).toBe(EMPTY_CARD_EDITS);
    expect(
      selectCardEdits(host({ scanResult: { scan_id: 'A' }, optionsCardEdits: slice }), 'options'),
    ).toBe(EMPTY_CARD_EDITS);
  });

  it('returns EMPTY when the slice itself is missing from a corrupt blob', () => {
    const h = host({ scanResult: { scan_id: 'A' } });
    (h as { optionsCardEdits: unknown }).optionsCardEdits = undefined;
    expect(() => selectCardEdits(h, 'options')).not.toThrow();
    expect(selectCardEdits(h, 'options')).toBe(EMPTY_CARD_EDITS);
  });

  it('keeps the two modes independent — one stale stamp does not empty the other', () => {
    const h = host({
      scanResult: { scan_id: 'opt-2' },
      stockScanResult: { scan_id: 'stk-1' },
      optionsCardEdits: stamped('opt-1', { entryLimit: { k: 2.71 } }),
      stocksCardEdits: stamped('stk-1', { invalidation: { AAPL: 180 } }),
    });
    expect(selectCardEdits(h, 'options')).toBe(EMPTY_CARD_EDITS);
    expect(selectCardEdits(h, 'stocks').invalidation).toEqual({ AAPL: 180 });
  });

  // Referential stability: zustand v5 compares selector results with Object.is,
  // so a fresh object per call would re-render forever.
  it('returns the SAME empty object every time', () => {
    const h = host({ scanResult: { scan_id: 'B' }, optionsCardEdits: stamped('A') });
    expect(selectCardEdits(h, 'options')).toBe(selectCardEdits(h, 'options'));
  });

  it('EMPTY_CARD_EDITS is frozen, so a caller cannot poison every later read', () => {
    expect(() => {
      (EMPTY_CARD_EDITS.entryLimit as Record<string, number>)['k'] = 1;
    }).toThrow();
    expect(EMPTY_CARD_EDITS.entryLimit).toEqual({});
  });
});

describe('writeCardEdit', () => {
  it('drops the write when there is no scan to stamp it with', () => {
    const slice = emptyCardEdits();
    expect(writeCardEdit(slice, null, 'entryLimit', 'k', 2.71)).toBe(slice);
  });

  it('writes under the current stamp', () => {
    const next = writeCardEdit(emptyCardEdits(), 'A', 'entryLimit', 'k', 2.71);
    expect(next.scanId).toBe('A');
    expect(next.entryLimit).toEqual({ k: 2.71 });
  });

  // The rule that makes a mismatched write safe: an old scan's edits cannot
  // end up sitting beside a new scan's.
  it('RESETS the slice before writing when the stamp differs', () => {
    const stale = stamped('A', {
      entryLimit: { 'AAPL|190|2027-01-15|C': 2.71 },
      invalidation: { AAPL: 180 },
      picks: { 'AAPL|190|2027-01-15|C': pick() },
    });
    const next = writeCardEdit(stale, 'B', 'premiumStop', 'MSFT|420|2026-06-18|C', 3.1);
    expect(next.scanId).toBe('B');
    expect(next.premiumStop).toEqual({ 'MSFT|420|2026-06-18|C': 3.1 });
    expect(next.entryLimit).toEqual({});
    expect(next.invalidation).toEqual({});
    expect(next.picks).toEqual({});
  });

  it('returns the SAME slice for an unchanged write (the render-cascade guard)', () => {
    const slice = writeCardEdit(emptyCardEdits(), 'A', 'entryLimit', 'k', 2.71);
    expect(writeCardEdit(slice, 'A', 'entryLimit', 'k', 2.71)).toBe(slice);
  });

  // Order matters: the identity guard must not short-circuit a stale stamp.
  it('still resets when the VALUE is unchanged but the STAMP is stale', () => {
    const stale = stamped('A', { entryLimit: { k: 2.71 }, invalidation: { AAPL: 180 } });
    const next = writeCardEdit(stale, 'B', 'entryLimit', 'k', 2.71);
    expect(next).not.toBe(stale);
    expect(next.scanId).toBe('B');
    expect(next.invalidation).toEqual({});
  });

  // `null` means "untouched" and is a real value, distinct from absent.
  it('writes an explicit null over an absent key', () => {
    const next = writeCardEdit(stamped('A'), 'A', 'invalidation', 'AAPL', null);
    expect(next).not.toBe(stamped('A'));
    expect('AAPL' in next.invalidation).toBe(true);
    expect(next.invalidation.AAPL).toBeNull();
    expect(writeCardEdit(next, 'A', 'invalidation', 'AAPL', null)).toBe(next);
  });

  it('leaves the other four maps alone on a normal write', () => {
    const slice = stamped('A', { invalidation: { AAPL: 180 } });
    const next = writeCardEdit(slice, 'A', 'entryLimit', 'k', 2.71);
    expect(next.invalidation).toBe(slice.invalidation);
  });
});

describe('clearPicksForSymbol', () => {
  const OLD = 'AAPL|190|2027-01-15|C';
  const NEW = 'AAPL|200|2027-01-15|C';
  const OTHER = 'MSFT|420|2026-06-18|C';

  it('drops the outgoing contract’s pick and keeps the incoming one', () => {
    const slice = stamped('A', { picks: { [OLD]: pick(), [NEW]: pick('ladder'), [OTHER]: pick() } });
    const next = clearPicksForSymbol(slice, 'AAPL', NEW);
    expect(Object.keys(next.picks).sort()).toEqual([OTHER, NEW].sort());
  });

  // The auto-pick case: nothing recorded the outgoing contract's id anywhere,
  // so clearing by symbol prefix is what reaches it.
  it('drops a pick made on a contract that was never an explicit override', () => {
    const slice = stamped('A', { picks: { [OLD]: pick() } });
    expect(clearPicksForSymbol(slice, 'AAPL', NEW).picks).toEqual({});
  });

  it('leaves the typed price caches alone', () => {
    const slice = stamped('A', {
      picks: { [OLD]: pick() },
      entryLimit: { [OLD]: 2.71 },
      premiumStop: { [OLD]: 3.12 },
    });
    const next = clearPicksForSymbol(slice, 'AAPL', NEW);
    expect(next.entryLimit).toEqual({ [OLD]: 2.71 });
    expect(next.premiumStop).toEqual({ [OLD]: 3.12 });
  });

  it('returns the SAME slice when there is nothing to drop', () => {
    const slice = stamped('A', { picks: { [OTHER]: pick() } });
    expect(clearPicksForSymbol(slice, 'AAPL', NEW)).toBe(slice);
  });

  // `indexOf('|') === -1` must not slice off the last character and match a
  // near-miss symbol.
  it('handles a key with no pipe without mangling it', () => {
    const slice = stamped('A', { picks: { AAPL: pick(), AAPLX: pick() } });
    const next = clearPicksForSymbol(slice, 'AAPL', null);
    expect(Object.keys(next.picks)).toEqual(['AAPLX']);
  });
});

describe('normalizeCardEdits', () => {
  it.each([undefined, null, 'nonsense', 42, []])('coerces %p into a well-formed slice', (v) => {
    expect(normalizeCardEdits(v)).toEqual(emptyCardEdits());
  });

  it('keeps a valid stamp and the five maps', () => {
    const raw = { scanId: 'A', picks: { k: pick() }, invalidation: { AAPL: 180 },
      premiumStop: {}, entryLimit: {}, maxLossOverride: {} };
    expect(normalizeCardEdits(raw)).toEqual(raw);
  });

  it('nulls a non-string or empty stamp rather than trusting it', () => {
    expect(normalizeCardEdits({ scanId: '' }).scanId).toBeNull();
    expect(normalizeCardEdits({ scanId: 7 }).scanId).toBeNull();
  });

  it('forces a non-numeric price entry to null rather than letting it reach the order', () => {
    /* `entryLimitFor` / `invalidationFor` fall back with `??`, which catches
     * only null and undefined — so a string surviving this boundary would be
     * posted as the broker order's `limit_price` and stored as the position's
     * `stop`. `null` is the "untouched" state, which is what those readers are
     * built to handle. Only reachable from an externally corrupted blob (JSON
     * cannot round-trip NaN or Infinity), which is why it is cheap insurance. */
    const out = normalizeCardEdits({
      scanId: 's1',
      entryLimit:   { a: 'abc', b: 2.71, c: null },
      invalidation: { a: {}, b: 132 },
      premiumStop:  { a: true, b: 1.5 },
    });
    expect(out.entryLimit).toEqual({ a: null, b: 2.71, c: null });
    expect(out.invalidation).toEqual({ a: null, b: 132 });
    expect(out.premiumStop).toEqual({ a: null, b: 1.5 });
  });

  it('keeps a real zero, which is a value and not an absence', () => {
    // `Number.isFinite(0)` is true and 0 must survive: the readers use `??`,
    // so coercing 0 to null here would silently re-inherit the plan's seed.
    expect(normalizeCardEdits({ entryLimit: { a: 0 } }).entryLimit).toEqual({ a: 0 });
  });

  it('replaces a map that came back as a non-object', () => {
    expect(normalizeCardEdits({ scanId: 'A', entryLimit: 'x' }).entryLimit).toEqual({});
  });
});

// ─── Build step 3 ──────────────────────────────────────────────────────────
describe('clearCardPick', () => {
  it('removes the KEY, so "present" and "picked" stay the same fact', () => {
    const slice = stamped('s1', { picks: { A: pick(), B: pick('ladder') } });
    const next = clearCardPick(slice, 's1', 'A');
    // Not `picks.A === null`. `picks` is `Record<string, MethodPick>` and every
    // reader is allowed to treat a present key as a human decision.
    expect('A' in next.picks).toBe(false);
    expect(next.picks.B).toEqual(pick('ladder'));
  });

  it('leaves the other four maps alone', () => {
    const slice = stamped('s1', {
      picks: { A: pick() },
      entryLimit: { 'A|1|x|C': 2.71 },
      invalidation: { A: 180 },
    });
    const next = clearCardPick(slice, 's1', 'A');
    expect(next.entryLimit).toEqual({ 'A|1|x|C': 2.71 });
    expect(next.invalidation).toEqual({ A: 180 });
  });

  it('returns the SAME object when the key is not there', () => {
    // Identity guard. This fires from a render effect, so a fresh object on a
    // no-op is a loop rather than merely churn.
    const slice = stamped('s1', { picks: { A: pick() } });
    expect(clearCardPick(slice, 's1', 'B')).toBe(slice);
  });

  it('is a NO-OP on a stamp mismatch, not a reset', () => {
    // Deliberately the opposite of `writeCardEdit`'s rule 2. A write under a
    // new scan must reset so the new edit cannot land beside old ones; a clear
    // lands nothing, and everything it could clear is already unreadable.
    // Resetting would discard the slice's other four maps as a side effect.
    const slice = stamped('old', { picks: { A: pick() }, entryLimit: { X: 2.71 } });
    expect(clearCardPick(slice, 'new', 'A')).toBe(slice);
    expect(clearCardPick(slice, null, 'A')).toBe(slice);
  });
});

// ─── Send-path wiring gap fix (found and closed 2026-09-15) ────────────────
// Confirmed as of build step 4: the send gate blocked an UNPICKED send, but
// nothing carried a MADE pick's actual values into the position any send
// path created — `positionFromOrder`, `buildPaperPosition` and every
// `buildPaperStockPosition` caller built a `PortfolioPosition` with none of
// the five `picked_*` fields set, so a real send silently discarded the
// trader's decision even when the gate passed. `pickedFieldsFrom` is the one
// mapping every one of those call sites now spreads in.
describe('pickedFieldsFrom', () => {
  it('maps every field of a MethodPick onto its picked_* name', () => {
    expect(pickedFieldsFrom(pick('monte_carlo'))).toEqual({
      pickedMethod: 'monte_carlo',
      pickedRowStockPrice: 197.5,
      pickedRowOptionPrice: 6.24,
      pickedStopBasis: 'stock',
      pickedAt: '2026-09-14T10:00:00.000Z',
    });
  });

  it('maps null to all five fields explicitly null, not an empty object', () => {
    // The S5 auto-executor's shape (spec §7.3) — omitting the keys and
    // setting them null are identical to the backend schema, but the
    // explicit form is what this function exists to guarantee at every call
    // site, so the object shape itself is part of the contract under test.
    expect(pickedFieldsFrom(null)).toEqual({
      pickedMethod: null,
      pickedRowStockPrice: null,
      pickedRowOptionPrice: null,
      pickedStopBasis: null,
      pickedAt: null,
    });
  });

  it('preserves a null row price on an otherwise-complete pick (Barrier Race has no stock price; a Monte Carlo row may)', () => {
    const barrierRacePick: MethodPick = {
      method: 'barrier_race', rowStockPrice: null, rowOptionPrice: 6.24,
      stopBasis: 'premium', pickedAt: '2026-09-14T10:00:00.000Z',
    };
    expect(pickedFieldsFrom(barrierRacePick)).toEqual({
      pickedMethod: 'barrier_race',
      pickedRowStockPrice: null,
      pickedRowOptionPrice: 6.24,
      pickedStopBasis: 'premium',
      pickedAt: '2026-09-14T10:00:00.000Z',
    });
  });
});

// Phase G piece 5, BUILD STEP 5 (§8). The arm endpoint's counterpart. It exists
// separately from `pickedFieldsFrom` because the two endpoints do not share a
// naming convention and neither is free to change: `PortfolioPositionCreate` is
// camelCase-with-snake-aliases, `ArmRequest` is snake_case with no aliases, and
// `ArmedStrategy(**req.model_dump())` keys off ArmRequest's field NAMES. Sending
// the wrong spelling is SILENT at both ends — `ArmRequest` inherits pydantic's
// `extra='ignore'` and returns 200 with all five NULL (measured), and `tsc`
// does not flag a wrong mapping spread into an object literal. The alternative
// to two functions is renaming keys at a call site, which is where a field gets
// quietly dropped.
describe('armPickedFieldsFrom', () => {
  it('maps every field of a MethodPick onto its snake_case arm-request name', () => {
    expect(armPickedFieldsFrom(pick('monte_carlo'))).toEqual({
      picked_method: 'monte_carlo',
      picked_row_stock_price: 197.5,
      picked_row_option_price: 6.24,
      picked_stop_basis: 'stock',
      picked_at: '2026-09-14T10:00:00.000Z',
    });
  });

  it('emits snake_case ONLY — no camelCase key survives onto the arm request', () => {
    const out = armPickedFieldsFrom(pick('monte_carlo')) as Record<string, unknown>;
    expect(Object.keys(out).sort()).toEqual([
      'picked_at', 'picked_method', 'picked_row_option_price',
      'picked_row_stock_price', 'picked_stop_basis',
    ]);
  });

  it('maps null to all five fields explicitly null, not an empty object', () => {
    // Unlike `premium_stop_pct` on the same request body, an OMISSION here has
    // no global to mean "inherit" — so "no pick" is spelled, not left out.
    expect(armPickedFieldsFrom(null)).toEqual({
      picked_method: null,
      picked_row_stock_price: null,
      picked_row_option_price: null,
      picked_stop_basis: null,
      picked_at: null,
    });
  });

  it('keeps a null row price null rather than falling back to 0', () => {
    // `?? 0` here would be caught by ArmRequest's `gt=0` as a 422 rather than
    // stored — loud, but still wrong: null means "this method quotes no level
    // in that space", and the arm would simply fail.
    const barrierRacePick: MethodPick = {
      method: 'barrier_race', rowStockPrice: null, rowOptionPrice: 6.24,
      stopBasis: 'premium', pickedAt: '2026-09-14T10:00:00.000Z',
    };
    expect(armPickedFieldsFrom(barrierRacePick)).toEqual({
      picked_method: 'barrier_race',
      picked_row_stock_price: null,
      picked_row_option_price: 6.24,
      picked_stop_basis: 'premium',
      picked_at: '2026-09-14T10:00:00.000Z',
    });
  });
});

// ─── P6 (G2-4-RESIDUAL, G2-8, G2-10) ───────────────────────────────────────
describe('P6 — picks are value-checked on rehydrate', () => {
  it('keeps a real pick, including a Barrier Race pick with no stock price', () => {
    const race: MethodPick = { ...pick('barrier_race'), rowStockPrice: null };
    const out = normalizeCardEdits({ scanId: 's1', picks: { a: pick(), b: race } });
    expect(out.picks).toEqual({ a: pick(), b: race });
  });

  it.each([
    ['an unknown method',          { method: 'ouija' }],
    ['a zero stock price',         { rowStockPrice: 0 }],
    ['a negative option price',    { rowOptionPrice: -1 }],
    ['a string price',             { rowStockPrice: '197.5' }],
    ['an unknown stop basis',      { stopBasis: 'vibes' }],
    ['a missing pickedAt',         { pickedAt: undefined }],
    ['an empty pickedAt',          { pickedAt: '' }],
  ])('drops a pick with %s (absent = not picked, which the send gate refuses)', (_label, over) => {
    const out = normalizeCardEdits({ scanId: 's1', picks: { bad: { ...pick(), ...over }, good: pick() } });
    expect(out.picks).toEqual({ good: pick() });
  });

  it.each([null, 'x', 7, []])('drops a non-object pick entry %p', (v) => {
    expect(normalizeCardEdits({ scanId: 's1', picks: { k: v } }).picks).toEqual({});
  });
});

describe('P6 — clearPicksForSymbol compares the symbol case-insensitively', () => {
  it('clears keys whose prefix differs from the raw symbol only in case', () => {
    const slice = stamped('s1', { picks: { 'BRK.B|400|2026-10-16|C': pick(), 'MSFT|1|x|C': pick() } });
    const next = clearPicksForSymbol(slice, 'brk.b', null);
    expect(Object.keys(next.picks)).toEqual(['MSFT|1|x|C']);
  });
});

describe('P6 — own-property tests, not `in`', () => {
  // writeCardEdit's copy of the same fix has no observable test: its identity
  // guard also needs Object.is(inherited, value), and a number is never an
  // inherited function. clearCardPick's guard is observable, so it is pinned.
  it('clearCardPick treats an inherited name as absent (identity returned)', () => {
    const slice = stamped('s1', { picks: { A: pick() } });
    expect(clearCardPick(slice, 's1', 'toString')).toBe(slice);
  });
});
