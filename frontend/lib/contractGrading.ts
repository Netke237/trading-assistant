/*
 * WATCHLIST-SCAN-CONTRACT-RULES — grading a starred contract as the scan did.
 *
 * A star stores the grading inputs Step 6 sent to `/api/contracts` for that row
 * (`ContractGrading`). Step 6 derives its request FROM the grading through
 * `gradingToCtx`, and the Watchlist sends the same ctx, plus the star's own
 * expiry and strikes, so the two can never drift.
 *
 * Pure helpers only: a Next.js page file may export only its route symbols, so
 * every runtime rule the Watchlist uses lives here and is pinned by
 * `__tests__/contractGrading.test.ts`.
 */

import type { ContractGrading, OptionContract, OptionRight } from '@/types/domain';

/** The grading fields of `api.getContracts`' ctx. */
export interface GradingCtx {
  stock_score?:    number;
  hold_min_days?:  number;
  hold_max_days?:  number;
  contract_rules?: Record<string, number>;
}

/** The ctx a grading sends. A null field is OMITTED (`undefined`), exactly what
 *  Step 6 sent before gradings existed; `{}` rules pass THROUGH as `{}`
 *  (`api.ts` drops an empty object from the URL). */
export function gradingToCtx(g: ContractGrading | null | undefined): GradingCtx {
  const ctx: GradingCtx = {};
  if (!g) return ctx;
  if (g.stock_score != null) ctx.stock_score = g.stock_score;
  if (g.hold_min_days != null && g.hold_max_days != null) {
    ctx.hold_min_days = g.hold_min_days;
    ctx.hold_max_days = g.hold_max_days;
  }
  if (g.contract_rules != null) ctx.contract_rules = g.contract_rules;
  return ctx;
}

/** Step 6's grading for one symbol's row: the scan's recorded rules (`null` =
 *  not recorded), the sanitized hold days (or nulls), and the stock score. */
export function buildGrading(
  contractRules: Record<string, number> | null | undefined,
  hold: { hold_min_days: number; hold_max_days: number } | undefined,
  stockScore: number,
): ContractGrading {
  return {
    contract_rules: contractRules ?? null,
    hold_min_days:  hold?.hold_min_days ?? null,
    hold_max_days:  hold?.hold_max_days ?? null,
    stock_score:    stockScore,
  };
}

const isInt = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v);

/** The backend's acceptance rule, checked client-side before a stored grading
 *  is used: rule values finite numbers, hold days non-negative integers both or
 *  neither with max >= min, stock_score an int 0-100. Server-served gradings
 *  pass it; this only bites a corrupt local entry. */
export function isValidGrading(g: unknown): g is ContractGrading {
  if (g == null || typeof g !== 'object') return false;
  const o = g as Record<string, unknown>;
  const rules = o.contract_rules;
  if (rules !== null) {
    if (typeof rules !== 'object' || Array.isArray(rules) || rules === undefined) return false;
    for (const v of Object.values(rules as Record<string, unknown>)) {
      if (typeof v !== 'number' || !Number.isFinite(v)) return false;
    }
  }
  const lo = o.hold_min_days;
  const hi = o.hold_max_days;
  if (lo === null || hi === null) {
    if (lo !== hi) return false;
  } else {
    if (!isInt(lo) || !isInt(hi) || lo < 0 || hi < lo) return false;
  }
  const s = o.stock_score;
  if (s !== null && !(isInt(s) && s >= 0 && s <= 100)) return false;
  return true;
}

/** The grading a stored entry stands for: itself when valid, else none. */
export function usableGrading(g: ContractGrading | undefined): ContractGrading | null {
  return g !== undefined && isValidGrading(g) ? g : null;
}

/** True when the row is graded on contract_rules.yaml: no usable grading, or
 *  one whose scan recorded no rules. */
export function isYamlGraded(g: ContractGrading | undefined): boolean {
  const u = usableGrading(g);
  return u === null || u.contract_rules === null;
}

/** JSON with sorted object keys: equal values give equal strings. */
export function stableStringify(v: unknown): string {
  if (v === null || typeof v !== 'object') return JSON.stringify(v);
  if (Array.isArray(v)) return `[${v.map(stableStringify).join(',')}]`;
  const o = v as Record<string, unknown>;
  return `{${Object.keys(o).sort().map((k) => `${JSON.stringify(k)}:${stableStringify(o[k])}`).join(',')}}`;
}

/** Gradings that send the same request share a key: `stock_score` null is 70
 *  (the backend default), empty rules are dropped (as `api.ts` drops them).
 *  A grading that sends the same request as none gets '', the no-grading key. */
export function gradingKey(g: ContractGrading | null | undefined): string {
  const ctx: Record<string, unknown> = { ...gradingToCtx(usableGrading(g ?? undefined)) };
  if (ctx.stock_score === undefined) ctx.stock_score = 70;
  if (ctx.contract_rules && Object.keys(ctx.contract_rules as object).length === 0) delete ctx.contract_rules;
  const keys = Object.keys(ctx);
  if (keys.length === 1 && ctx.stock_score === 70) return '';
  return stableStringify(ctx);
}

// ── Contract ids ─────────────────────────────────────────────────────────────

export interface ParsedContractId {
  id:          string;
  symbol:      string;
  /** As written in the id, `parseFloat`ed: `187.5` stays 187.5, `187.0` is
   *  187. The exact strike: what is shown, sent and matched (the backend
   *  matches strikes exactly, EXACT-STRIKE). */
  strike: number;
  expiry: string;
  right:  OptionRight;
}

const SYMBOL_RE = /^[A-Z][A-Z0-9.\-]*$/;
const STRIKE_RE = /^[0-9]{1,5}(\.[0-9]{1,3})?$/;
const EXPIRY_RE = /^\d{4}-\d{2}-\d{2}$/;

/** `"AAPL|187|2026-12-18|C"` -> its parts, or null for an unreadable id. The
 *  expiry is checked by shape only: an impossible date (2026-02-30) passes and
 *  lands as "not in the current chain". */
export function parseContractId(id: string): ParsedContractId | null {
  const parts = id.split('|');
  if (parts.length !== 4) return null;
  const [symbol, strikeText, expiry, right] = parts as [string, string, string, string];
  if (!SYMBOL_RE.test(symbol)) return null;
  if (!STRIKE_RE.test(strikeText)) return null;
  if (!EXPIRY_RE.test(expiry)) return null;
  if (right !== 'C' && right !== 'P') return null;
  const strike = parseFloat(strikeText);
  if (!Number.isFinite(strike) || strike <= 0) return null;
  return { id, symbol, strike, expiry, right };
}

/** Today's LOCAL date as `YYYY-MM-DD`. */
export function localTodayIso(now: Date = new Date()): string {
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, '0');
  const d = String(now.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

// ── Grouping the Watchlist's requests ────────────────────────────────────────

export interface ContractGroup {
  /** (symbol, right, expiry, gradingKey). */
  key:     string;
  symbol:  string;
  right:   OptionRight;
  expiry:  string;
  /** De-duplicated exact strikes, in first-seen order. */
  strikes: number[];
  /** The grading ctx: the first member's grading, in `watchedIds` order. */
  ctx:     GradingCtx;
}

export interface ContractPlan {
  /** De-duplicated ids, in `watchedIds` order. */
  ids:      string[];
  parsed:   Map<string, ParsedContractId | null>;
  expired:  Set<string>;
  /** The group key of every fetched id. */
  groupOf:  Map<string, string>;
  groups:   ContractGroup[];
}

export function groupKeyOf(p: ParsedContractId, gKey: string): string {
  return `${p.symbol}|${p.right}|${p.expiry}|${gKey}`;
}

/** Parse, classify expired, and group the rest by (symbol, right, expiry,
 *  gradingKey): one `getContracts` per group. */
export function planContractGroups(
  watchedIds: string[],
  grading: Record<string, ContractGrading>,
  today: string,
): ContractPlan {
  const ids = [...new Set(watchedIds.filter(Boolean))];
  const parsed  = new Map<string, ParsedContractId | null>();
  const expired = new Set<string>();
  const groupOf = new Map<string, string>();
  const byKey   = new Map<string, ContractGroup>();
  for (const id of ids) {
    const p = parseContractId(id);
    parsed.set(id, p);
    if (!p) continue;
    if (p.expiry < today) { expired.add(id); continue; }
    const g = usableGrading(grading[id]);
    const key = groupKeyOf(p, gradingKey(g));
    groupOf.set(id, key);
    let group = byKey.get(key);
    if (!group) {
      group = { key, symbol: p.symbol, right: p.right, expiry: p.expiry, strikes: [], ctx: gradingToCtx(g) };
      byKey.set(key, group);
    }
    if (!group.strikes.includes(p.strike)) group.strikes.push(p.strike);
  }
  return { ids, parsed, expired, groupOf, groups: [...byKey.values()] };
}

// ── Rows ─────────────────────────────────────────────────────────────────────

export type MissingReason = 'loading' | 'expired' | 'not_listed' | 'fetch_failed';

export type WatchedContractRow =
  | { kind: 'live'; contract: OptionContract; yamlGraded: boolean }
  | { kind: 'missing'; id: string; symbol: string; strike: number; expiry: string; right: OptionRight; reason: MissingReason }
  | { kind: 'invalid'; id: string };

/** A settled group request, kept on screen until the next settled refresh. */
export interface KeptGroupResult {
  groupKey: string;
  strikes:  Set<number>;
  outcome:  OptionContract[] | 'rejected';
}

export const MISSING_NOTE: Record<MissingReason, string> = {
  loading:      'Loading…',
  expired:      'Expired',
  not_listed:   'Not in the current chain',
  fetch_failed: 'Could not load the chain — retry',
};
export const INVALID_NOTE = 'Unreadable contract id';
export const YAML_MARKER = "Graded on contract_rules.yaml — the scan's rules were not recorded with this star";

/** One row per de-duplicated star. A row is graded only from a settled request
 *  for its own group whose strikes CONTAIN its strike (a superset request
 *  counts, so unstarring a sibling does not blank a row); otherwise it is
 *  `loading`. */
export function resolveWatchedRows(
  plan: ContractPlan,
  kept: KeptGroupResult[],
  grading: Record<string, ContractGrading>,
): WatchedContractRow[] {
  return plan.ids.map((id): WatchedContractRow => {
    const p = plan.parsed.get(id);
    if (!p) return { kind: 'invalid', id };
    const missing = (reason: MissingReason): WatchedContractRow =>
      ({ kind: 'missing', id, symbol: p.symbol, strike: p.strike, expiry: p.expiry, right: p.right, reason });
    if (plan.expired.has(id)) return missing('expired');
    const key = plan.groupOf.get(id);
    const result = kept.find((k) => k.groupKey === key && k.strikes.has(p.strike));
    if (!result) return missing('loading');
    if (result.outcome === 'rejected') return missing('fetch_failed');
    const yamlGraded = isYamlGraded(grading[id]);
    const exact = result.outcome.find((c) => c.id === id);
    if (exact) return { kind: 'live', contract: exact, yamlGraded };
    const fallback = result.outcome.find((c) =>
      c.symbol === p.symbol && Number(c.strike) === p.strike
      && c.expiry === p.expiry && c.right === p.right);
    // The stored id, so ContractStar.isWatched is true and a click unstars.
    if (fallback) return { kind: 'live', contract: { ...fallback, id }, yamlGraded };
    return missing('not_listed');
  });
}

export type ContractSortKey = 'score' | 'dte' | 'price';

/** Live rows sort by `key` in `dir`; missing and invalid rows always last, in
 *  both directions and for every key, ordered by their `watchedIds` position. */
export function compareWatchedRows(
  a: WatchedContractRow,
  b: WatchedContractRow,
  key: ContractSortKey,
  dir: 'asc' | 'desc',
  order: Map<string, number>,
): number {
  const aLive = a.kind === 'live';
  const bLive = b.kind === 'live';
  if (aLive && bLive) {
    const mul = dir === 'asc' ? 1 : -1;
    const ca = a.contract;
    const cb = b.contract;
    switch (key) {
      case 'price': return (ca.price - cb.price) * mul;
      case 'dte':   return (ca.dte - cb.dte) * mul;
      case 'score':
      default:      return (ca.score - cb.score) * mul;
    }
  }
  if (aLive) return -1;
  if (bLive) return 1;
  return (order.get(a.id) ?? 0) - (order.get(b.id) ?? 0);
}

export function rowId(r: WatchedContractRow): string {
  return r.kind === 'live' ? r.contract.id : r.id;
}
