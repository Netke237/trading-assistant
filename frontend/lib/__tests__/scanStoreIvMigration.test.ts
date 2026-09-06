import { useScanStore } from '../scanStore';
import { resolveIv } from '../ivBasis';

// Reach into the store's persist config for the real migrate() callback —
// same approach as scanStoreHorizonMigration.test.ts.
const migrate = (useScanStore as unknown as {
  persist: { getOptions: () => {
    migrate: (state: unknown, version: number) => unknown;
    version: number;
  } };
}).persist.getOptions();

type MigratedResult = {
  candidates: Array<{
    symbol: string;
    contractDetails?: Record<string, unknown>;
    alternatives?: Array<Record<string, unknown>>;
  }>;
};

/** A v12 blob as it was actually written before the split: ONE number under
 *  the percentile's name, holding raw implied volatility, and an
 *  `ivPercentile` of 0 that meant "no rank source answered". */
function legacyBlob() {
  return {
    scanResult: {
      scan_id: 'S1',
      timestamp: '2026-09-05T10:00:00',
      rejected: [],
      candidates: [{
        symbol: 'AAPL',
        contractDetails: { strike: 185, mid: 2.4, ivRank: 45, ivPercentile: 0 },
        alternatives: [
          { symbol: 'AAPL', strike: 190, ivRank: 47, reason: 'cheaper' },
          { symbol: 'AAPL', strike: 180, ivRank: null, reason: 'no iv' },
        ],
      }],
    },
    previousRun: {
      scan_id: 'S0',
      timestamp: '2026-09-04T10:00:00',
      rejected: [],
      candidates: [{ symbol: 'MSFT', contractDetails: { strike: 400, ivRank: 62 } }],
    },
  };
}

describe('scanStore persisted migrate(): v12 -> v13, the Phase A IV split', () => {
  it('is registered at v13, so a v12 blob actually reaches the branch', () => {
    // Without the bump the branch is dead code and the defect ships intact.
    expect(migrate.version).toBe(13);
  });

  it('drops the unattributable ivRank on the block the trade card renders', () => {
    const out = migrate.migrate(legacyBlob(), 12) as { scanResult: MigratedResult };
    const cd = out.scanResult.candidates[0]!.contractDetails!;
    expect(cd.ivRank).toBeNull();
    // The point of dropping it: Step 7 now prints "—" rather than
    // "IV rank 45" for what was in fact a 45% absolute IV.
    expect(resolveIv(cd as { ivRank: number | null })).toEqual({ value: null, basis: 'none' });
    // A legacy ivPercentile of 0 was the "nobody answered" sentinel, not a
    // genuine bottom-of-range percentile.
    expect(cd.ivPercentile).toBeNull();
    // Everything else on the block survives.
    expect(cd.strike).toBe(185);
    expect(cd.mid).toBe(2.4);
  });

  it('reaches alternatives too, which carry the same conflated field', () => {
    const out = migrate.migrate(legacyBlob(), 12) as { scanResult: MigratedResult };
    const alts = out.scanResult.candidates[0]!.alternatives!;
    expect(alts[0]!.ivRank).toBeNull();
    expect(alts[0]!.reason).toBe('cheaper');
    // A row that never had a reading is untouched.
    expect(alts[1]!.ivRank).toBeNull();
  });

  it('repairs previousRun as well — Δscore is computed against it', () => {
    const out = migrate.migrate(legacyBlob(), 12) as { previousRun: MigratedResult };
    expect(out.previousRun.candidates[0]!.contractDetails!.ivRank).toBeNull();
  });

  it('still applies every earlier branch, so a v1 blob is fully migrated', () => {
    // Branches must accumulate — a store frozen at an old version has to
    // receive all the intermediate field additions in one pass.
    const out = migrate.migrate({ ...legacyBlob(), context: null }, 1) as
      Record<string, unknown> & { scanResult: MigratedResult };
    expect(out.pickedContracts).toEqual({});
    expect(out.screenerMode).toBe('options');
    expect(out.scanResult.candidates[0]!.contractDetails!.ivRank).toBeNull();
  });

  it('handles absent, null and malformed persisted results without throwing', () => {
    expect(() => migrate.migrate({}, 12)).not.toThrow();
    expect(() => migrate.migrate({ scanResult: null, previousRun: null }, 12)).not.toThrow();
    expect(() => migrate.migrate({ scanResult: { candidates: 'nope' } }, 12)).not.toThrow();
    expect(() => migrate.migrate({ scanResult: { candidates: [null, 7] } }, 12)).not.toThrow();
  });

  it('leaves a post-split blob alone, because the branch is version-gated', () => {
    // Dropping is destructive and correct only for a figure of unknown basis.
    // A v13 record's ivRank IS a real percentile and must survive.
    const post = {
      scanResult: {
        candidates: [{ symbol: 'AAPL', contractDetails: { ivRank: 62, iv: null, ivPercentile: 58 } }],
      },
    };
    const out = migrate.migrate(post, 13) as { scanResult: MigratedResult };
    expect(out.scanResult.candidates[0]!.contractDetails!.ivRank).toBe(62);
    expect(out.scanResult.candidates[0]!.contractDetails!.ivPercentile).toBe(58);
  });
});
