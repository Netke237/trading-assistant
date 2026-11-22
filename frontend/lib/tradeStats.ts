/*
 * PORTFOLIO-HISTORY-INSIGHTS (#663): pure statistics, filter and sort over the
 * closed-trade history. No React, no store access. The gate for this module is
 * a wrong number in front of the user, so every formula is exact and pinned by
 * lib/__tests__/tradeStats.test.ts.
 *
 * ROW = CLOSE EVENT. A `ClosedPosition` is one close event, not one position:
 * a partial close and the later close of the remainder are two rows and count
 * as two trades in every statistic below.
 *
 * Rows with a non-finite `realizedPnlDollar` are dropped before any statistic
 * and counted in `skipped`.
 *
 * Formulas (cents(x) = Math.round(x * 100); class: win > 0, loss < 0, else flat,
 * so -0.004 is flat, matching `moneyTone`):
 *   winRate      = wins / (wins + losses) * 100; null when wins + losses == 0
 *                  (flats are in neither numerator nor denominator)
 *   grossWon     = sum of dollars of wins; grossLost = sum of |dollars| of losses
 *   avgWin       = grossWon / wins (null if none); avgLoss = -grossLost / losses
 *   lossToWin    = |avgLoss| / avgWin; null unless both exist and avgWin > 0
 *   profitFactor = grossWon / grossLost; null when no losses; 0 when losses, no wins
 *   total        = sum of dollars; expectancy = total / count (flats count)
 *   holdDays     = calendar days between the `slice(0, 10)` date strings, computed
 *                  from UTC midnights (no timezone, no DST); null when either date
 *                  is missing or invalid or exit is before entry; 0 is valid
 *   returnPct    = realizedPnlPct when entryPrice > 0 and finite, else null (the
 *                  API reports 0.0 for a zero-cost entry; that is not a real 0.0%)
 *   pastStop     = { n: option losses past the stop, of: option losses checkable }
 *
 * EXIT-RECORD EXTENSION POINT (#664): `exitCheck` takes the stop as an argument.
 * Today callers pass the global `premiumStopPct`; once the stop in force at
 * entry is stored, #664 passes that per-trade value instead, with no change here.
 */

import type { ClosedPosition } from './performanceStore';
import { parseContractId } from './contractGrading';

export type TradeClass = 'win' | 'loss' | 'flat';
export type TradeFilter = 'all' | 'wins' | 'losses';
export type SortKey = 'symbol' | 'entry' | 'exit' | 'hold' | 'pnl' | 'return';
export type SortDir = 'asc' | 'desc';

export type ExitCheck =
  | { kind: 'win'; label: string }
  | { kind: 'flat'; label: string }
  | { kind: 'stock-loss'; label: string }
  | { kind: 'unknown'; label: string }
  | { kind: 'within-stop'; label: string }
  | { kind: 'past-stop'; lossPct: number; label: string };

export interface HoldStats {
  avg: number | null;
  min: number | null;
  max: number | null;
  n: number;
}

export interface TradeStats {
  count: number;
  wins: number;
  losses: number;
  flats: number;
  skipped: number;
  winRate: number | null;
  grossWon: number;
  grossLost: number;
  avgWin: number | null;
  avgLoss: number | null;
  lossToWin: number | null;
  profitFactor: number | null;
  total: number;
  expectancy: number | null;
  hold: HoldStats;
  pastStop: { n: number; of: number };
}

const cents = (x: number): number => Math.round(x * 100);

export function classOf(h: ClosedPosition): TradeClass {
  const c = cents(h.realizedPnlDollar);
  if (c > 0) return 'win';
  if (c < 0) return 'loss';
  return 'flat';
}

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/** `slice(0,10)` of the string when it is a real calendar date, as UTC ms. */
function dateMs(s: string | undefined | null): number | null {
  if (typeof s !== 'string') return null;
  const d = s.slice(0, 10);
  if (!DATE_RE.test(d)) return null;
  const y = Number(d.slice(0, 4));
  const m = Number(d.slice(5, 7));
  const day = Number(d.slice(8, 10));
  const ms = Date.UTC(y, m - 1, day);
  const back = new Date(ms);
  if (back.getUTCFullYear() !== y || back.getUTCMonth() !== m - 1 || back.getUTCDate() !== day) return null;
  return ms;
}

export function holdDays(h: ClosedPosition): number | null {
  const a = dateMs(h.entryDate);
  const b = dateMs(h.exitDate);
  if (a === null || b === null) return null;
  const days = (b - a) / 86_400_000;
  return days < 0 ? null : days;
}

export function returnPct(h: ClosedPosition): number | null {
  if (!(h.entryPrice > 0)) return null;
  return Number.isFinite(h.realizedPnlPct) ? h.realizedPnlPct : null;
}

const isStock = (contract: string): boolean => contract.endsWith('|STOCK');
const isOption = (contract: string): boolean => parseContractId(contract) !== null;

const UNKNOWN: ExitCheck = { kind: 'unknown', label: '—' };

export function exitCheck(h: ClosedPosition, stopPct: number): ExitCheck {
  const cls = classOf(h);
  if (cls === 'win') return { kind: 'win', label: 'Win' };
  if (cls === 'flat') return { kind: 'flat', label: 'Flat' };
  if (isStock(h.contract)) return { kind: 'stock-loss', label: 'Stock loss' };
  const ret = returnPct(h);
  const stopValid = Number.isFinite(stopPct) && stopPct > 0 && stopPct < 1;
  if (!isOption(h.contract) || ret === null || ret >= 0 || !stopValid) return UNKNOWN;
  const lossPct = -ret;
  // Integer hundredths: a float product (0.29 * 100 = 28.999...) cannot flip a boundary loss.
  if (Math.round(lossPct * 100) > Math.round(stopPct * 10000)) {
    const s = Math.round(stopPct * 100);
    const r = Math.round(lossPct);
    const l = r <= s ? lossPct.toFixed(1) : String(r);
    return { kind: 'past-stop', lossPct, label: `Lost ${l}%: past ${s}% premium stop` };
  }
  return { kind: 'within-stop', label: 'Within premium stop' };
}

export function computeTradeStats(rows: readonly ClosedPosition[], stopPct: number): TradeStats {
  const trades = rows.filter((r) => Number.isFinite(r.realizedPnlDollar));
  const skipped = rows.length - trades.length;
  let wins = 0, losses = 0, flats = 0, grossWon = 0, grossLost = 0, total = 0;
  let pastN = 0, pastOf = 0;
  let holdSum = 0, holdN = 0, holdMin: number | null = null, holdMax: number | null = null;
  for (const t of trades) {
    const cls = classOf(t);
    total += t.realizedPnlDollar;
    if (cls === 'win') { wins += 1; grossWon += t.realizedPnlDollar; }
    else if (cls === 'loss') {
      losses += 1; grossLost += Math.abs(t.realizedPnlDollar);
      const ec = exitCheck(t, stopPct);
      if (ec.kind === 'past-stop') { pastN += 1; pastOf += 1; }
      else if (ec.kind === 'within-stop') pastOf += 1;
    } else flats += 1;
    const hd = holdDays(t);
    if (hd !== null) {
      holdSum += hd; holdN += 1;
      holdMin = holdMin === null ? hd : Math.min(holdMin, hd);
      holdMax = holdMax === null ? hd : Math.max(holdMax, hd);
    }
  }
  const count = wins + losses + flats;
  const avgWin = wins > 0 ? grossWon / wins : null;
  const avgLoss = losses > 0 ? -grossLost / losses : null;
  return {
    count, wins, losses, flats, skipped,
    winRate: wins + losses > 0 ? (wins / (wins + losses)) * 100 : null,
    grossWon, grossLost, avgWin, avgLoss,
    lossToWin: avgWin !== null && avgLoss !== null && avgWin > 0 ? Math.abs(avgLoss) / avgWin : null,
    profitFactor: losses > 0 ? grossWon / grossLost : null,
    total,
    expectancy: count > 0 ? total / count : null,
    hold: holdN > 0
      ? { avg: Math.round(holdSum / holdN), min: holdMin, max: holdMax, n: holdN }
      : { avg: null, min: null, max: null, n: 0 },
    pastStop: { n: pastN, of: pastOf },
  };
}

export function filterTrades(rows: readonly ClosedPosition[], filter: TradeFilter, query: string): ClosedPosition[] {
  const needle = query.trim().toUpperCase();
  return rows.filter((r) => {
    if (filter !== 'all') {
      const cls = classOf(r);
      if (filter === 'wins' && cls !== 'win') return false;
      if (filter === 'losses' && cls !== 'loss') return false;
    }
    return needle === '' || r.symbol.toUpperCase().includes(needle);
  });
}

function sortValue(h: ClosedPosition, key: SortKey): string | number | null {
  switch (key) {
    case 'symbol': return h.symbol.toUpperCase();
    case 'entry': return typeof h.entryDate === 'string' && h.entryDate !== '' ? h.entryDate.slice(0, 10) : null;
    case 'exit': return typeof h.exitDate === 'string' && h.exitDate !== '' ? h.exitDate.slice(0, 10) : null;
    case 'hold': return holdDays(h);
    case 'pnl': return Number.isFinite(h.realizedPnlDollar) ? h.realizedPnlDollar : null;
    case 'return': return returnPct(h);
  }
}

/** Returns a new array; `key === null` keeps the API order. Missing values sort
 *  last in both directions and ties keep the original order (index tiebreak). */
export function sortTrades(rows: readonly ClosedPosition[], key: SortKey | null, dir: SortDir): ClosedPosition[] {
  if (key === null) return [...rows];
  const sign = dir === 'asc' ? 1 : -1;
  return rows
    .map((row, i) => ({ row, i, v: sortValue(row, key) }))
    .sort((x, y) => {
      if (x.v === null && y.v === null) return x.i - y.i;
      if (x.v === null) return 1;
      if (y.v === null) return -1;
      if (x.v < y.v) return -sign;
      if (x.v > y.v) return sign;
      return x.i - y.i;
    })
    .map((e) => e.row);
}

export function tradeLabel(h: ClosedPosition): string {
  if (isStock(h.contract)) return `${h.symbol} stock`;
  const p = parseContractId(h.contract);
  if (p) return `${p.symbol} ${String(p.strike)}${p.right}`;
  return h.symbol;
}
