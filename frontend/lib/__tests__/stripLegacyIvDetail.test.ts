/** ROUND 5 findings 2 and 5. `stripLegacyIvDetail` and the scanStore v14 pass
 *  had ZERO coverage — deleting both call sites broke no test — and the
 *  version-gating defect that made round 4's fix unreachable was invisible for
 *  the same reason. These tests fail without the v14 branch and without the
 *  `iv_basis` discriminator. */
import { stripLegacyIvDetail } from '../ivBasis';

describe('stripLegacyIvDetail', () => {
  it('drops an unattributable pre-split figure', () => {
    // No `iv_basis` — written before the split, basis unrecoverable.
    const out = stripLegacyIvDetail({ iv_rank: 62, reason: 'ok' }) as Record<string, unknown>;
    expect(out.iv_rank).toBeNull();
  });

  it('KEEPS a figure that carries a basis, on either basis', () => {
    // The round-5 discriminator. A v13 blob can hold a genuine post-split
    // percentile; stripping it is the same harm as printing an unattributable
    // one, and a version gate alone cannot tell the two apart.
    const ranked = { iv_rank: 62, iv_basis: 'rank' as const };
    expect(stripLegacyIvDetail(ranked)).toBe(ranked);
    const abs = { iv_rank: 45.2, iv_basis: 'absolute' as const };
    expect(stripLegacyIvDetail(abs)).toBe(abs);
  });

  it('treats a legitimate 0 as a figure, not as absent', () => {
    // 0 is a real absolute IV and a real percentile; only null means "no
    // reading". A truthiness test here would silently pass a 0 through.
    const out = stripLegacyIvDetail({ iv_rank: 0 }) as Record<string, unknown>;
    expect(out.iv_rank).toBeNull();
  });

  it('is a no-op with nothing to strip, and is idempotent', () => {
    const empty = { reason: 'compressed_vol' };
    expect(stripLegacyIvDetail(empty)).toBe(empty);
    const once = stripLegacyIvDetail({ iv_rank: 30 });
    expect(stripLegacyIvDetail(once)).toBe(once);
  });

  it('passes non-records through untouched', () => {
    expect(stripLegacyIvDetail(null)).toBeNull();
    expect(stripLegacyIvDetail([1])).toEqual([1]);
    expect(stripLegacyIvDetail('x')).toBe('x');
  });
});
