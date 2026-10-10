import { resolveIv, formatIv, ivSortValue, stripLegacyIvFields, IV_COLUMN_LABEL, ivColumnLabel, ivBasesOf } from '@/lib/ivBasis';
import { getIvPassMax, getIvCautionMax } from '@/lib/ivThresholdsStore';
import { IV_SHIPPED } from '@/lib/testFixtures/thresholds';

describe('resolveIv', () => {
  it('prefers a true percentile over the absolute level', () => {
    expect(resolveIv({ ivRank: 62, iv: 45 })).toEqual({ value: 62, basis: 'rank' });
  });

  it('falls back to the absolute level when no rank source answered', () => {
    // The default configuration: Tradier supplies a per-strike IV, nobody
    // supplies a percentile.
    expect(resolveIv({ ivRank: null, iv: 45 })).toEqual({ value: 45, basis: 'absolute' });
  });

  it('reports no basis when neither quantity is present', () => {
    expect(resolveIv({ ivRank: null, iv: null })).toEqual({ value: null, basis: 'none' });
    expect(resolveIv(undefined)).toEqual({ value: null, basis: 'none' });
    expect(resolveIv({})).toEqual({ value: null, basis: 'none' });
  });

  it('treats a rank of 0 as a real reading but an absolute IV of 0 as missing', () => {
    // IV at the very bottom of a name's own 52-week range is a genuine and
    // strongly favourable reading; a tradeable option cannot have 0% IV, so
    // that value is a missing-data sentinel. Mirrors backend augment.py.
    expect(resolveIv({ ivRank: 0, iv: 45 })).toEqual({ value: 0, basis: 'rank' });
    expect(resolveIv({ ivRank: null, iv: 0 })).toEqual({ value: null, basis: 'none' });
  });

  it('treats undefined the same as null, since the wire omits absent fields', () => {
    expect(resolveIv({ iv: 45 })).toEqual({ value: 45, basis: 'absolute' });
  });
});

describe('formatIv', () => {
  it('shows a percentile bare, marked as a rank', () => {
    const f = formatIv(resolveIv({ ivRank: 62 }), 'AAPL');
    expect(f.text).toBe('62');
    expect(f.suffix).toBe('rank');
    expect(f.title).toContain('52-week range');
  });

  it('shows an absolute level with a percent sign and says it is not a percentile', () => {
    const f = formatIv(resolveIv({ ivRank: null, iv: 45 }), 'AAPL');
    expect(f.text).toBe('45.0%');
    expect(f.suffix).toBe('');
    expect(f.title).toContain('absolute level, not a rank');
  });

  it('shows an em dash and no misleading number when there is no data', () => {
    const f = formatIv(resolveIv({}), 'AAPL');
    expect(f.text).toBe('—');
    expect(f.title).toContain('No implied-volatility data');
  });

  it('never presents an absolute level AS a rank', () => {
    // The whole point of the split: 45% IV is not the 45th percentile of this
    // name's own range (PHASE-A-NULL-IVRANK-2026-09-06). The rendered figure
    // must carry no rank wording, and the tooltip must not attach the number
    // to the words "IV rank" — it may still say a rank SOURCE was unavailable,
    // which is the explanation, not a mislabelling.
    const f = formatIv(resolveIv({ ivRank: null, iv: 45 }), 'AAPL');
    expect(`${f.text} ${f.suffix}`).not.toMatch(/rank/i);
    expect(f.title).not.toMatch(/IV rank 45/i);
  });

  it('names a generic subject when no symbol is supplied', () => {
    expect(formatIv(resolveIv({ ivRank: 62 })).title).toContain("this name's");
  });
});

describe('ivSortValue', () => {
  it('sorts on the figure actually displayed', () => {
    expect(ivSortValue({ ivRank: 62, iv: 45 })).toBe(62);
    expect(ivSortValue({ ivRank: null, iv: 45 })).toBe(45);
  });

  it('returns null rather than 0 for no data, so it can be sorted last', () => {
    // Arithmetic coerces null to 0, which would sort a contract with NO
    // volatility reading to the top of an ascending "cheapest IV" sort.
    expect(ivSortValue({ ivRank: null, iv: null })).toBeNull();
  });
});

describe('threshold selection by basis', () => {
  it('judges an absolute level against the absolute set', () => {
    expect(getIvPassMax('Swing', IV_SHIPPED, 'absolute')).toBe(34);
    expect(getIvCautionMax('Swing', IV_SHIPPED, 'absolute')).toBe(55);
    expect(getIvPassMax('Position', IV_SHIPPED, 'absolute')).toBe(44);
  });

  it('judges a percentile against the percentile set', () => {
    expect(getIvPassMax('Swing', IV_SHIPPED, 'rank')).toBe(34);
    expect(getIvCautionMax('Position', IV_SHIPPED, 'rank')).toBe(65);
  });

  it('keeps the two sets independent, so measuring one never moves the other', () => {
    const measured = {
      ...IV_SHIPPED,
      Swing: { ...IV_SHIPPED.Swing, rank_pass_max: 70, rank_caution_max: 85 },
    };
    expect(getIvPassMax('Swing', measured, 'rank')).toBe(70);
    expect(getIvPassMax('Swing', measured, 'absolute')).toBe(34);
  });

  it('returns no threshold at all when there is no figure to judge', () => {
    expect(getIvPassMax('Swing', IV_SHIPPED, 'none')).toBeNull();
    expect(getIvCautionMax('Swing', IV_SHIPPED, 'none')).toBeNull();
  });

  it('has no IV gate on either basis for Intraday', () => {
    expect(getIvPassMax('Intraday', IV_SHIPPED, 'absolute')).toBeNull();
    expect(getIvPassMax('Intraday', IV_SHIPPED, 'rank')).toBeNull();
  });
});

describe('IV_COLUMN_LABEL', () => {
  it('does not promise a rank, since most rows carry an absolute level', () => {
    expect(IV_COLUMN_LABEL).toBe('IV');
  });
});

describe('stripLegacyIvFields', () => {
  // ROUND 1 findings (a) and (b). A blob written before the split carries ONE
  // number of unknown basis under the percentile's name; resolveIv reads any
  // non-null ivRank as a percentile, so rehydrating it reintroduces the exact
  // mislabel Phase A removes — on the trade card and the portfolio table, the
  // two surfaces the user acts from.

  it('drops an unattributable legacy figure rather than guessing its basis', () => {
    const out = stripLegacyIvFields({ symbol: 'AAPL', ivRank: 45 }) as Record<string, unknown>;
    expect(out.ivRank).toBeNull();
    // And the point of dropping it: the display sites now say "no data"
    // instead of printing "IV rank 45" for what is most likely 45% IV.
    expect(resolveIv(out as { ivRank: number | null })).toEqual({ value: null, basis: 'none' });
  });

  it('drops a legacy ivPercentile of 0, which meant "no rank source answered"', () => {
    // Pre-split the field defaulted to the literal 0; post-split that state is
    // null. A surviving 0 renders as a genuine bottom-of-range percentile.
    const out = stripLegacyIvFields({ ivRank: 45, ivPercentile: 0 }) as Record<string, unknown>;
    expect(out.ivPercentile).toBeNull();
  });

  it('leaves every other field on the record untouched', () => {
    const out = stripLegacyIvFields({
      symbol: 'AAPL', strike: 185, iv: 45, ivRank: 62,
    }) as Record<string, unknown>;
    expect(out).toEqual({ symbol: 'AAPL', strike: 185, iv: 45, ivRank: null });
  });

  it('is a no-op on a record that never carried a reading', () => {
    const row = { symbol: 'AAPL', ivRank: null };
    expect(stripLegacyIvFields(row)).toBe(row);
    const bare = { symbol: 'AAPL' };
    expect(stripLegacyIvFields(bare)).toBe(bare);
  });

  it('passes non-records through, since persisted JSON is unvalidated', () => {
    expect(stripLegacyIvFields(null)).toBeNull();
    expect(stripLegacyIvFields(undefined)).toBeUndefined();
    expect(stripLegacyIvFields('AAPL')).toBe('AAPL');
    const arr = [{ ivRank: 45 }];
    expect(stripLegacyIvFields(arr)).toBe(arr);
  });

  it('does not mutate the input', () => {
    const row = { ivRank: 45, ivPercentile: 0 };
    stripLegacyIvFields(row);
    expect(row).toEqual({ ivRank: 45, ivPercentile: 0 });
  });
});

describe('ivColumnLabel — the heading names the bases actually on screen', () => {
  // Step 5's banner said "IV rank ≤ 34 → PASS" over a column headed "IV".
  // Two names for one column reads as two quantities, and there genuinely ARE
  // three on that screen (absolute IV, IV rank, IV percentile), so the
  // ambiguity was not harmless.
  it('names the rank basis when every row carries a rank', () => {
    expect(ivColumnLabel(['rank'])).toBe('IV RANK');
  });

  it('stays plain IV when every row carries an absolute level', () => {
    expect(ivColumnLabel(['absolute'])).toBe('IV');
  });

  it('names BOTH when the rows disagree — the case that made the old heading wrong', () => {
    expect(ivColumnLabel(['rank', 'absolute'])).toBe('IV / IV RANK');
    expect(ivColumnLabel(['absolute', 'rank'])).toBe('IV / IV RANK');
  });

  it('falls back to the neutral heading with nothing to describe', () => {
    expect(ivColumnLabel([])).toBe(IV_COLUMN_LABEL);
  });

  it("ignores 'none' — a row with no reading says nothing about the basis", () => {
    expect(ivColumnLabel(['none'])).toBe('IV');
    expect(ivColumnLabel(['none', 'rank'])).toBe('IV RANK');
  });
});

describe('ivBasesOf — what actually feeds the column heading', () => {
  // This function had ZERO coverage when it shipped: replacing its whole body
  // with `return []` left the entire 1685-test suite green, while silently
  // reverting all four tables to the neutral "IV" heading -- the exact state the
  // change was made to fix.
  it('reports the single basis when every row agrees', () => {
    expect(ivBasesOf([{ ivRank: 30 }, { ivRank: 40 }])).toEqual(['rank']);
    expect(ivBasesOf([{ iv: 42 }, { iv: 38 }])).toEqual(['absolute']);
  });

  it('reports BOTH when the rows disagree — the case the heading exists for', () => {
    expect(ivBasesOf([{ ivRank: 30 }, { iv: 42 }]).sort()).toEqual(['absolute', 'rank']);
    expect(ivColumnLabel(ivBasesOf([{ ivRank: 30 }, { iv: 42 }]))).toBe('IV / IV RANK');
  });

  it('omits rows with no reading rather than inventing a basis', () => {
    expect(ivBasesOf([{}, { ivRank: null, iv: null }])).toEqual([]);
    expect(ivColumnLabel(ivBasesOf([{}]))).toBe(IV_COLUMN_LABEL);
  });

  it('survives nulls and an empty list', () => {
    expect(ivBasesOf([null, undefined, { ivRank: 5 }])).toEqual(['rank']);
    expect(ivBasesOf([])).toEqual([]);
  });

  it('keeps resolveIv\'s asymmetry: rank 0 is real, absolute 0 is missing', () => {
    // Pinned here too because the heading is downstream of it: an absolute 0 is
    // a missing-data sentinel, a rank of 0 is the bottom of the 52-week range.
    expect(ivBasesOf([{ ivRank: 0 }])).toEqual(['rank']);
    expect(ivBasesOf([{ iv: 0 }])).toEqual([]);
  });

  it('end-to-end: a mixed table is headed differently from a single-basis one', () => {
    expect(ivColumnLabel(ivBasesOf([{ ivRank: 10 }]))).toBe('IV RANK');
    expect(ivColumnLabel(ivBasesOf([{ iv: 44 }]))).toBe('IV');
    expect(ivColumnLabel(ivBasesOf([{ iv: 44 }, { ivRank: 10 }]))).toBe('IV / IV RANK');
  });
});
