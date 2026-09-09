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

describe('scanStore persisted migrate(): v12 -> v14, the Phase A IV split', () => {
  it('is registered past v14, so a v12 blob actually reaches the branch', () => {
    // Without the bump the branch is dead code and the defect ships intact.
    //
    // ROUND 5 finding 2: this pin is the ONLY assertion in this file that can
    // catch the defect that shipped in round 4, and it is worth being precise
    // about why. The detail-block strip was appended to the `version < 13`
    // branch nine commits AFTER v13 shipped. zustand calls migrate only when
    // the stored version differs from the configured one, so every browser
    // holding a v13 blob skipped it entirely. The tests below cannot see that:
    // they invoke `migrate.migrate(blob, n)` directly and so bypass the very
    // version comparison that was the bug. They verify what the branch DOES;
    // this pin is what verifies the branch is REACHED. Any new migration step
    // needs a new version, and this assertion is what forces the pairing.
    //
    // GREATER-THAN, not equal, since piece 3 added v15. This file's subject is
    // the Phase A IV split, and what it needs from the version is only that a
    // v12/v13 blob still DIFFERS from the configured one and so still reaches
    // these branches. Pinning equality here would make every later migration
    // fail an assertion about a migration it has nothing to do with; the
    // pairing this comment describes is enforced for v15 by
    // scanStoreStopMigration.test.ts, which owns that branch.
    expect(migrate.version).toBeGreaterThanOrEqual(15);
  });

  it('re-runs the score-detail strip for a blob ALREADY at v13', () => {
    // ROUND 5 finding 2. Covers the v14 branch's CONTENT: a store coming from
    // the previous version still gets the score-detail strip. It does NOT
    // prove the branch is reached in a real browser — that is the version pin
    // above, since calling migrate directly bypasses zustand's version check.
    const v13Blob = {
      scanResult: {
        scan_id: 'S1',
        timestamp: '2026-09-04T10:00:00',
        rejected: [],
        candidates: [{
          symbol: 'MSFT',
          // Already stripped by the v13 pass; the detail blocks were not.
          contractDetails: { strike: 400, ivRank: null },
          stockBreakdown: { volDetail: { iv_rank: 0, reason: 'compressed_vol' } },
          contractBreakdown: { ivDetail: { iv_rank: 62, preferred_max: 55 } },
        }],
      },
    };
    const out = migrate.migrate(v13Blob, 13) as { scanResult: MigratedResult };
    const c = out.scanResult.candidates[0]! as unknown as {
      stockBreakdown: { volDetail: Record<string, unknown> };
      contractBreakdown: { ivDetail: Record<string, unknown> };
    };
    // The impossible "IV 0%" and the mislabelled 62nd percentile both go.
    expect(c.stockBreakdown.volDetail.iv_rank).toBeNull();
    expect(c.contractBreakdown.ivDetail.iv_rank).toBeNull();
  });

  it('RELABELS a rounds-1-2 figure instead of destroying it (round 6 finding 2)', () => {
    // VolDetail did not gain `iv_basis` in the schema until round 3, so a
    // browser that scanned during rounds 1-2 holds a v13 blob whose volDetail
    // is correctly resolved but UNLABELLED. Treating the missing label as a
    // pre-split marker destroyed a good number — data the user cannot get back
    // without re-scanning, which the project's audit gate bars as firmly as it
    // bars printing a wrong one. The basis is recoverable from the sibling
    // contract block, so it is read, not guessed.
    const roundsOneTwo = {
      scanResult: {
        scan_id: 'S3', timestamp: '2026-09-04T10:00:00', rejected: [],
        candidates: [{
          symbol: 'NVDA',
          // `iv` PRESENT => written by a post-split backend; ivRank non-null
          // => a rank source answered, so the vol figure is a percentile.
          contractDetails: { strike: 900, iv: null, ivRank: 78.4 },
          stockBreakdown: { volDetail: { iv_rank: 78.4, reason: 'iv_too_high' } },
        }],
      },
    };
    const out = migrate.migrate(roundsOneTwo, 13) as { scanResult: MigratedResult };
    const vd = (out.scanResult.candidates[0] as unknown as {
      stockBreakdown: { volDetail: Record<string, unknown> };
    }).stockBreakdown.volDetail;
    expect(vd.iv_rank).toBe(78.4);            // kept, not nulled
    expect(vd.iv_basis).toBe('rank');         // and now labelled correctly
    expect(vd.reason).toBe('iv_too_high');    // the verdict stands with its figure
  });

  it('still strips when the sibling contract block is pre-split too', () => {
    // No `iv` key anywhere => a genuinely pre-split blob. The basis is not
    // recoverable, so the figure is dropped, per PHASE-A-NULL-IVRANK.
    const preSplit = {
      scanResult: {
        scan_id: 'S4', timestamp: '2026-09-04T10:00:00', rejected: [],
        candidates: [{
          symbol: 'INTC',
          contractDetails: { strike: 30, ivRank: null },
          stockBreakdown: { volDetail: { iv_rank: 45, reason: 'iv_too_high' } },
        }],
      },
    };
    const out = migrate.migrate(preSplit, 13) as { scanResult: MigratedResult };
    const vd = (out.scanResult.candidates[0] as unknown as {
      stockBreakdown: { volDetail: Record<string, unknown> };
    }).stockBreakdown.volDetail;
    expect(vd.iv_rank).toBeNull();
    expect(vd.iv_basis).toBeUndefined();
    expect(vd.reason).toBeUndefined();        // the verdict goes with the figure
  });

  it('does NOT strip a post-split figure from a v13 blob', () => {
    // The other half: a v13 blob written by post-split code holds a GENUINE
    // percentile. The v14 pass must leave it alone — stripping a real 62nd
    // percentile is the same harm as printing an unattributable one. This is
    // why the strip discriminates on `iv_basis` rather than on the version.
    const postSplit = {
      scanResult: {
        scan_id: 'S2',
        timestamp: '2026-09-04T10:00:00',
        rejected: [],
        candidates: [{
          symbol: 'AAPL',
          contractDetails: { strike: 200, ivRank: 62 },
          contractBreakdown: { ivDetail: { iv_rank: 62, iv_basis: 'rank', preferred_max: 55 } },
        }],
      },
    };
    const out = migrate.migrate(postSplit, 13) as { scanResult: MigratedResult };
    const c = out.scanResult.candidates[0]! as unknown as {
      contractBreakdown: { ivDetail: Record<string, unknown> };
      contractDetails: Record<string, unknown>;
    };
    expect(c.contractBreakdown.ivDetail.iv_rank).toBe(62);
    // And the v14 pass must not touch camelCase ivRank either — at v13 that is
    // a legitimate percentile, and re-running the v13 walk would null it.
    expect(c.contractDetails.ivRank).toBe(62);
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
