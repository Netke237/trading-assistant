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

/** Column heading covering a table whose rows may not share a basis.
 *
 *  A COMPROMISE, and the LAST RESORT -- every table in the app now derives its
 *  heading with `ivColumnLabel(ivBasesOf(rows))` instead. This constant survives
 *  only as that function's neutral fallback when there are no rows to describe.
 *  It was left in place on three of four tables when `ivColumnLabel` landed,
 *  which had step 5 heading the column "IV / IV RANK" and step 6 heading the
 *  same quantity "IV", one Next click apart. Heading a column `IV` while some of its cells hold a
 *  percentile is the ambiguity Phase A exists to remove, and it put the table
 *  at odds with prose that DID name the basis: Step 5's own banner says
 *  "IV rank ≤ 34 → PASS" over a column headed "IV", which reads as two
 *  different quantities to anyone who has not read ivBasis.ts. */
export const IV_COLUMN_LABEL = 'IV';

/** The heading for a column whose rows carry exactly the bases in `bases`.
 *
 *  Three different quantities are on this screen and they are easy to conflate:
 *    IV          absolute implied volatility, in volatility points ("42.0%")
 *    IV rank     where that sits in the name's own 52-week range ("31 rank")
 *    IV pctl     the share of the last year spent BELOW today's IV — its own
 *                column, and NOT what this heading covers
 *  The first two share one column because only one of them exists per row, so
 *  the heading has to say which are actually present rather than assume. */
/** The distinct bases actually present in a collection of rows.
 *
 *  Exists so the four tables that show this column can all reach
 *  `ivColumnLabel` from whatever they already render. Without it the new
 *  heading was adopted by ONE page and the other three kept the old constant,
 *  which left the app saying "IV / IV RANK" on step 5 and "IV" on step 6 for
 *  the same quantity, one Next click apart. */
export function ivBasesOf(rows: readonly (IvSource | null | undefined)[]): IvBasis[] {
  const seen = new Set<IvBasis>();
  for (const r of rows) {
    const b = resolveIv(r).basis;
    if (b !== 'none') seen.add(b);
  }
  return [...seen];
}

export function ivColumnLabel(bases: readonly IvBasis[]): string {
  const rank = bases.includes('rank');
  const absolute = bases.includes('absolute');
  if (rank && absolute) return 'IV / IV RANK';
  if (rank) return 'IV RANK';
  // Absolute-only AND the empty case both land here: with no rows to describe,
  // the neutral heading is the honest one.
  return IV_COLUMN_LABEL;
}

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

/* ── Legacy-localStorage repair (PHASE-A-NULL-IVRANK-2026-09-06) ────────────
 *
 * Before the split, `ivRank` held EITHER a true percentile (when IBKR or
 * tastytrade answered for the symbol) OR raw implied volatility × 100 (every
 * other chain), with nothing on the record saying which. That conflation IS
 * the defect Phase A removes — and a blob written to localStorage before the
 * split still carries it. Rehydrating one hands `resolveIv` a number of
 * UNKNOWN basis, and `resolveIv` reads any non-null `ivRank` as a percentile,
 * so the trade card prints "IV rank 45" for what is most likely a 45%
 * absolute IV: the exact defect, reintroduced on the card the user acts from.
 *
 * The basis is NOT recoverable from the stored record. The two quantities
 * share a scale (0–100), and the only would-be discriminator — a pre-split
 * `ivPercentile` of 0 meaning "no rank source answered" — exists on
 * `contractDetails` but on neither `alternatives` entries nor portfolio rows,
 * so it would have to be three different rules for one quantity. (Three
 * editors each deriving the same figure their own way is this project's
 * recurring regression class; see the note at the top of this file.)
 *
 * Guessing "absolute" would be right for most rows and silently wrong in the
 * other direction for the rest — the same mislabel in a new coat. So an
 * unattributable figure is DROPPED rather than relabelled: `resolveIv` then
 * returns basis "none" and every display site prints "—" until fresh data
 * arrives. Both stores refill within one ordinary action — scanStore on the
 * next scan, portfolioStore on the next successful `syncFromBackend` — and a
 * previous session's IV was stale market data regardless.
 *
 * `ivPercentile` is dropped with it: pre-split it defaulted to the literal 0
 * that meant "no rank source answered", and post-split that state is null, so
 * a surviving 0 would print as a genuine bottom-of-range percentile.
 *
 * Callers must run this from a VERSION-GATED migration branch only. It is not
 * safe to apply on every rehydration — post-split records hold a genuine
 * `ivRank`/`ivPercentile` pair that this would throw away.
 */
/* The SCORE-DETAIL sibling of stripLegacyIvFields below.
 *
 * ROUND 4 finding 1. The v13 migration stripped `contractDetails` and each
 * `alternatives` entry and stopped there, but a persisted candidate carries the
 * SAME ambiguous figure in two more places: `stockBreakdown.volDetail.iv_rank`
 * and `contractBreakdown.ivDetail.iv_rank`. Those blocks use SNAKE_CASE, so
 * stripLegacyIvFields could not have reached them even if it had been called —
 * it tests `ivRank`.
 *
 * Left in place they are worse than the fields that were stripped, because
 * `iv_basis` is optional and scoreDetailText defaults a missing basis to
 * 'absolute' and appends '%'. A pre-split candidate whose Black-Scholes
 * inversion failed stored `iv_rank: 0.0`, which then renders as "IV 0% ·
 * compressed_vol" — an impossible implied volatility asserted as measured — and
 * a pre-split IBKR/tastytrade row whose figure genuinely WAS a 62nd percentile
 * renders as "IV 62%".
 *
 * Same remedy as everywhere else in this split: the basis is not recoverable,
 * so the figure is DROPPED, not relabelled. scoreDetailText already omits the
 * IV clause when `iv_rank` is null and keeps `reason`, so the detail line
 * survives minus the unattributable number. Version-gate this like the others —
 * it is not idempotent against a post-split record.
 */
export function stripLegacyIvDetail(record: unknown, inferred?: IvBasis): unknown {
  if (typeof record !== 'object' || record === null || Array.isArray(record)) return record;
  const r = record as Record<string, unknown>;
  if (r.iv_rank == null) return record;
  // ROUND 5 finding 2. Discriminate on `iv_basis`, do NOT rely on the store
  // version alone. The backend stamps a basis on every detail block it emits
  // post-split (including _rule_vol's unscored early return, per round 4), and
  // nothing pre-split ever did — so its ABSENCE is the pre-split marker, and
  // its presence means the figure is attributable and must be left alone.
  //
  // This is what makes the function safe to run at any version and twice: a
  // v13 blob can hold EITHER pre-split details migrated by round-1 code or a
  // genuine post-split percentile written by a later build, and a
  // version-gated strip could not tell them apart. Stripping a real 62nd
  // percentile is the same class of harm as printing an unattributable one.
  if (r.iv_basis !== undefined) return record;
  // ROUND 6 finding 2. `iv_basis` absence is a PRE-ROUND-3 marker, not a
  // pre-split one, and the comment above overstated it. VolDetail did not gain
  // the field in the schema until d1ea97c9 (round 3) -- `_rule_vol` emitted it
  // from 71e317e5 but `_safe` filters to model_fields and dropped it -- so a
  // browser that scanned during rounds 1-2 holds a v13 blob whose volDetail
  // carries a CORRECTLY RESOLVED post-split figure with no label. Stripping
  // that destroys a good number, and the project's audit gate bars corrupting
  // persisted data just as firmly as printing a wrong one.
  //
  // The basis is not lost, though, only unlabelled: the same per-symbol
  // resolution fed the contract block, so `inferred` is READ off the sibling
  // contractDetails rather than guessed, which is what keeps this inside
  // PHASE-A-NULL-IVRANK-2026-09-06's "drop, do not guess" rule. When the
  // sibling is silent too, the figure really is unattributable and goes.
  if (inferred === 'rank' || inferred === 'absolute') {
    return { ...r, iv_basis: inferred };
  }
  // ROUND 5 finding 12. Drop the VERDICT with the figure. `reason` on a vol
  // detail is derived from the number ("compressed_vol" means it fell below the
  // compressed band; "iv_too_high" means it broke the ceiling), so keeping it
  // after refusing to show the figure asserts a conclusion about a quantity we
  // have just declared unattributable. `no_iv_data` is not derived from any
  // reading and stays.
  const IV_DERIVED = new Set(['compressed_vol', 'iv_too_high', 'iv_rank_too_high']);
  const out: Record<string, unknown> = { ...r, iv_rank: null };
  if (typeof r.reason === 'string' && IV_DERIVED.has(r.reason)) delete out.reason;
  return out;
}

export function stripLegacyIvFields(record: unknown): unknown {
  if (typeof record !== 'object' || record === null || Array.isArray(record)) return record;
  const r = record as Record<string, unknown>;
  // Leave a record that carries neither field untouched, so the migration is
  // a no-op (same object identity) on the rows that never had a reading.
  if (r.ivRank == null && r.ivPercentile == null) return record;
  const out: Record<string, unknown> = { ...r };
  if (r.ivRank != null) out.ivRank = null;
  if (r.ivPercentile != null) out.ivPercentile = null;
  return out;
}
