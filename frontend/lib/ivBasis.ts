/**
 * ivBasis.ts — the single place the UI decides WHICH volatility figure it has.
 *
 * `ivRank` and `iv` are two different quantities and usually only one of them
 * is present (PHASE-A-NULL-IVRANK-2026-09-06):
 *
 *   ivRank  a TRUE PERCENTILE — where today's implied volatility sits inside
 *           this name's own 52-week range. Supplied only when IBKR or
 *           tastytrade answered, so it is `null` on most chains.
 *   iv      ABSOLUTE implied volatility, 0–100, for the contract itself.
 *           Tradier per strike, the yfinance backfill, or the backend's
 *           Black-Scholes inversion.
 *
 * Until 2026-09-06 the absolute figure was written into `ivRank`, so a name at
 * 45% IV was displayed and scored as though it sat at its own 45th percentile.
 * Every consumer must therefore resolve the two through THIS module and label
 * whichever one it ends up showing — the resolution is deliberately not
 * duplicated per call site, because two editors each computing the same
 * quantity their own way is how this codebase has repeatedly regressed.
 *
 * The resolution mirrors backend/app/data/augment.py and
 * backend/app/routers/scan.py exactly, including the asymmetry: a rank of 0 is
 * MEANINGFUL (bottom of the 52-week range, i.e. genuinely cheap), whereas an
 * absolute IV of 0 is a missing-data sentinel.
 */

export type IvBasis = 'rank' | 'absolute' | 'none';

/** Anything carrying the two wire fields — a contract row, a contractDetails
 *  block, an alternative, a portfolio position. */
export interface IvSource {
  ivRank?: number | null;
  iv?:     number | null;
}

export interface ResolvedIv {
  /** The figure to show and to judge, or null when there is none. */
  value: number | null;
  /** Which quantity `value` holds — picks the threshold set, and the label. */
  basis: IvBasis;
}

export function resolveIv(src: IvSource | null | undefined): ResolvedIv {
  const rank = src?.ivRank;
  if (rank != null) return { value: rank, basis: 'rank' };
  const abs = src?.iv;
  if (abs != null && abs > 0) return { value: abs, basis: 'absolute' };
  return { value: null, basis: 'none' };
}

/** Column heading covering a table whose rows may not share a basis. */
export const IV_COLUMN_LABEL = 'IV';

/** How a single resolved figure reads in a cell.
 *
 *  A percentile and an absolute level are told apart by the `%`: `45%` is
 *  forty-five volatility points, `45` with the `rank` suffix is the 45th
 *  percentile of this name's own range. `title` spells that out on hover so
 *  the distinction never rests on the suffix alone.
 */
export function formatIv(r: ResolvedIv, symbol?: string): {
  text: string;
  suffix: string;
  title: string;
} {
  const who = symbol ? `${symbol}'s` : "this name's";
  if (r.basis === 'rank') {
    return {
      text: String(Math.round(r.value as number)),
      suffix: 'rank',
      title: `IV rank ${Math.round(r.value as number)} — where today's implied volatility sits in ${who} own 52-week range. Lower is cheaper premium.`,
    };
  }
  if (r.basis === 'absolute') {
    return {
      text: `${(r.value as number).toFixed(1)}%`,
      suffix: '',
      title: `Implied volatility ${(r.value as number).toFixed(1)}% — an absolute level, not a percentile. No IV rank source (IBKR or tastytrade) answered for ${who === "this name's" ? 'this name' : symbol}, so there is nothing to say whether that is high or low for it.`,
    };
  }
  return { text: '—', suffix: '', title: 'No implied-volatility data for this contract.' };
}

/** Sort key: the resolved figure, with "no data" sorted last in both
 *  directions rather than pretending to be zero. */
export function ivSortValue(src: IvSource | null | undefined): number | null {
  return resolveIv(src).value;
}
