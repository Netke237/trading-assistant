/**
 * scanStore v15 — piece 3's stop migration.
 *
 * `exit.invalidation` USED to be a flat percentage move off the stock price:
 * the same -3% on every symbol in the universe. It is now the resolved
 * structural+ATR stop, and the field did not change name — so a blob written
 * before piece 3 holds a flat stop under the resolved one's name.
 *
 * That is not cosmetic. `buildPaperPosition` stores that field as
 * `PortfolioPosition.stop`, the level STOP_REACHED fires against, so a user
 * placing an order from a restored candidate would arm a -3% stop believing it
 * to be the structural one — up to 3x tighter than the level the rest of the
 * app now claims a position's stop is.
 */
import { useScanStore } from '../scanStore';

// Reach into the store's persist config for the real migrate() callback —
// same approach as scanStoreIvMigration.test.ts.
const migrate = (useScanStore as unknown as {
  persist: { getOptions: () => {
    migrate: (state: unknown, version: number) => unknown;
    version: number;
  } };
}).persist.getOptions();

// scanStore v18 (TRADING-REVIEW-PHASE-C-RR) discards an options result unless
// EVERY candidate's R/R was computed on the full-premium basis, and branches
// accumulate -- so every fixture below, shaped as it was before v18, would come
// out as `scanResult: null`. Each candidate is marked full_premium on the way
// in so these tests keep measuring THIS file's branch, not v18's discard
// (scanStoreRrBasisMigration.test.ts owns that).
function markFullPremium(state: unknown): unknown {
  if (state === null || typeof state !== 'object') return state;
  const s = { ...(state as Record<string, unknown>) };
  for (const key of ['scanResult', 'previousRun']) {
    const run = s[key] as { candidates?: unknown } | null | undefined;
    if (run && typeof run === 'object' && Array.isArray(run.candidates)) {
      s[key] = {
        ...run,
        candidates: run.candidates.map((c) => (c && typeof c === 'object'
          ? { ...c, exit: { ...((c as { exit?: object }).exit ?? {}), rrRiskBasis: 'full_premium' } }
          : c)),
      };
    }
  }
  return s;
}
const migrateKept = (state: unknown, version: number) => migrate.migrate(markFullPremium(state), version);

type Migrated = {
  scanResult: { candidates: Array<{ symbol: string; exit: Record<string, unknown> }> };
  previousRun: { candidates: Array<{ symbol: string; exit: Record<string, unknown> }> } | null;
};

const FINAL_STOP = {
  price: 169.0, source: 'final_stop', stopSource: 'atr_widened',
  structuralSource: 'swing_low', structuralPrice: 182.0, atrFloorPrice: 169.0,
  distanceDollar: 13.0, atr: 8.0, computedAt: '2026-09-09T12:00:00+00:00',
};

/** A blob as it was written before piece 3: a flat stop, no provenance.
 *  Typed loosely on purpose — this is JSON out of localStorage, not a
 *  `TradeCardData`, and the migration's whole job is to survive shapes the
 *  current types no longer describe. */
function legacyBlob(): Record<string, any> {   // eslint-disable-line @typescript-eslint/no-explicit-any
  return {
    scanResult: {
      scan_id: 'S1', timestamp: '2026-09-05T10:00:00', rejected: [],
      candidates: [
        { symbol: 'AAPL', exit: { invalidation: 179.45, premiumStop: 1.5, timeStopDays: 10, target: 200.0, targets: [] } },
        { symbol: 'MSFT', exit: { invalidation: 388.0, premiumStop: 2.2, timeStopDays: 12, target: 430.0, targets: [] } },
      ],
    },
    previousRun: {
      scan_id: 'S0', timestamp: '2026-09-04T10:00:00', rejected: [],
      candidates: [
        { symbol: 'NVDA', exit: { invalidation: 110.0, premiumStop: 3.0, timeStopDays: 8, target: 130.0, targets: [] } },
      ],
    },
  };
}

describe('scanStore migrate(): v15, piece 3\'s stop', () => {
  it('sits below the configured version, so a v14 blob actually reaches the branch', () => {
    // zustand calls migrate only when the stored version DIFFERS from the
    // configured one. Every test below invokes migrate directly and so bypasses
    // that comparison — this assertion is the only one that verifies the branch
    // is REACHED in a real browser. Round 5 of Phase A shipped a migration that
    // was appended to an already-released version's branch and was therefore
    // dead code for exactly the stores that needed it; this is that lesson.
    //
    // A FLOOR, NOT AN EQUALITY, since Phase G piece 5 took the store to v16 for
    // the card-edit slices. The property that matters to piece 3's stop has
    // never been "the configured version is exactly 15" — it is "a v14 blob
    // still differs from it", which every later bump keeps true while an
    // equality pin would fail on each one and teach nothing. That the branch
    // itself still strips the stop is asserted directly below.
    expect(migrate.version).toBeGreaterThan(14);
  });

  it('strips the flat stop from every candidate in both runs', () => {
    const out = migrateKept(legacyBlob(), 14) as Migrated;
    expect(out.scanResult.candidates.map((c) => c.exit.invalidation)).toEqual([null, null]);
    expect(out.previousRun!.candidates.map((c) => c.exit.invalidation)).toEqual([null]);
  });

  it('deletes ONLY the stop, leaving the rest of the exit block intact', () => {
    // The other exit figures are stale in the ordinary way a restored card is
    // stale — they did not change MEANING, so dropping them would destroy real
    // data for no reason.
    const c = (migrateKept(legacyBlob(), 14) as Migrated).scanResult.candidates[0];
    expect(c.exit.premiumStop).toBe(1.5);
    expect(c.exit.timeStopDays).toBe(10);
    expect(c.exit.target).toBe(200.0);
  });

  it('leaves a stop that HAS a provenance block alone', () => {
    // A blob written by piece 3 or later carries a `finalStop` for the stop it
    // stored, so its `invalidation` is the resolved level and is not legacy.
    const blob = legacyBlob();
    blob.scanResult.candidates[0].exit = {
      ...blob.scanResult.candidates[0].exit, invalidation: 169.0, finalStop: FINAL_STOP,
    };
    const out = migrateKept(blob, 14) as Migrated;
    expect(out.scanResult.candidates[0].exit.invalidation).toBe(169.0);
    expect(out.scanResult.candidates[0].exit.finalStop).toEqual(FINAL_STOP);
    // ...while its neighbour, which has none, is still stripped.
    expect(out.scanResult.candidates[1].exit.invalidation).toBeNull();
  });

  it('is idempotent, so re-running it under a later version cannot lose data', () => {
    // v13's own history is that a branch was edited nine commits after it
    // shipped and had to be re-run under a new version. This branch has to
    // survive that: a second pass over an already-migrated blob must not turn
    // a good stop into null.
    const once = migrateKept(legacyBlob(), 14) as Migrated;
    const twice = migrateKept(once, 14) as Migrated;
    expect(twice).toEqual(once);

    const kept = migrateKept({
      scanResult: {
        candidates: [{ symbol: 'AAPL', exit: { invalidation: 169.0, finalStop: FINAL_STOP } }],
      },
      previousRun: null,
    }, 14) as Migrated;
    expect((migrateKept(kept, 14) as Migrated).scanResult.candidates[0].exit.invalidation).toBe(169.0);
  });

  it('accumulates rather than short-circuiting: a v12 blob gets this branch too', () => {
    // The migrate chain has no early returns by design, so a store at any old
    // version receives every intermediate step in one pass. A v12 blob that
    // skipped v15 would keep its flat stop forever.
    const out = migrateKept(legacyBlob(), 12) as Migrated;
    expect(out.scanResult.candidates[0].exit.invalidation).toBeNull();
  });

  it('survives a malformed blob rather than throwing away the whole store', () => {
    // zustand swallows a throw from migrate, which leaves the store unhydrated
    // — every deep step URL then bounces to step-1-regime. Same guard, same
    // reason, as the migrations above it.
    expect(() => migrateKept({ scanResult: null, previousRun: undefined }, 14)).not.toThrow();
    expect(() => migrateKept({ scanResult: { candidates: 'nope' } }, 14)).not.toThrow();
    expect(() => migrateKept({ scanResult: { candidates: [null, 7, { symbol: 'X' }] } }, 14)).not.toThrow();
  });
});
