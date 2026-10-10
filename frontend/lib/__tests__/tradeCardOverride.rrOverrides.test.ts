import { rrOverridesFrom } from '@/lib/tradeCardOverride';

describe('rrOverridesFrom', () => {
  it('extracts only the three rr_* keys that are numbers', () => {
    const result = rrOverridesFrom({
      rr_target_r_multiple: 3,
      rsi_floor: 40,
      trend_method: 'additive',
    });
    expect(result).toEqual({ rr_target_r_multiple: 3 });
  });

  it('ignores obsolete percentage targets', () => {
    expect(rrOverridesFrom({ rr_bullish_target_pct: 0.12, rr_bearish_target_pct: 0.2 })).toEqual({});
  });

  it('returns an empty object when no rr_* keys are set', () => {
    expect(rrOverridesFrom({ rsi_floor: 40 })).toEqual({});
  });

  it('extracts all three keys when all are present', () => {
    const result = rrOverridesFrom({
      rr_target_r_multiple: 3,
      rr_bullish_invalidation_pct: 0.04,
      rr_bearish_invalidation_pct: 0.05,
    });
    expect(result).toEqual({
      rr_target_r_multiple: 3,
      rr_bullish_invalidation_pct: 0.04,
      rr_bearish_invalidation_pct: 0.05,
    });
  });
});
