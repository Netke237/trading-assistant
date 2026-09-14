// Phase G piece 5, build step 2 — the stamp's rules, tested where they live.
// The store-level spec tests (11, 11b, 12, 15) are in scanStoreCardEdits.test.ts.

import {
  EMPTY_CARD_EDITS, clearPicksForSymbol, currentScanIdFor, emptyCardEdits,
  normalizeCardEdits, selectCardEdits, writeCardEdit,
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

  it('replaces a map that came back as a non-object', () => {
    expect(normalizeCardEdits({ scanId: 'A', entryLimit: 'x' }).entryLimit).toEqual({});
  });
});
