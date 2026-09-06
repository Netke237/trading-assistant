import { resolveIv, formatIv, ivSortValue, IV_COLUMN_LABEL } from '@/lib/ivBasis';
import { getIvPassMax, getIvCautionMax, FALLBACK } from '@/lib/ivThresholdsStore';

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
    expect(f.title).toContain('absolute level, not a percentile');
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
    expect(getIvPassMax('Swing', FALLBACK, 'absolute')).toBe(34);
    expect(getIvCautionMax('Swing', FALLBACK, 'absolute')).toBe(55);
    expect(getIvPassMax('Position', FALLBACK, 'absolute')).toBe(44);
  });

  it('judges a percentile against the percentile set', () => {
    expect(getIvPassMax('Swing', FALLBACK, 'rank')).toBe(34);
    expect(getIvCautionMax('Position', FALLBACK, 'rank')).toBe(65);
  });

  it('keeps the two sets independent, so measuring one never moves the other', () => {
    const measured = {
      ...FALLBACK,
      Swing: { ...FALLBACK.Swing, rank_pass_max: 70, rank_caution_max: 85 },
    };
    expect(getIvPassMax('Swing', measured, 'rank')).toBe(70);
    expect(getIvPassMax('Swing', measured, 'absolute')).toBe(34);
  });

  it('returns no threshold at all when there is no figure to judge', () => {
    expect(getIvPassMax('Swing', FALLBACK, 'none')).toBeNull();
    expect(getIvCautionMax('Swing', FALLBACK, 'none')).toBeNull();
  });

  it('has no IV gate on either basis for Intraday', () => {
    expect(getIvPassMax('Intraday', FALLBACK, 'absolute')).toBeNull();
    expect(getIvPassMax('Intraday', FALLBACK, 'rank')).toBeNull();
  });

  it('falls back to the built-in defaults for an unknown horizon', () => {
    expect(getIvPassMax('Nonsense', FALLBACK, 'absolute')).toBeNull();
  });
});

describe('IV_COLUMN_LABEL', () => {
  it('does not promise a rank, since most rows carry an absolute level', () => {
    expect(IV_COLUMN_LABEL).toBe('IV');
  });
});
