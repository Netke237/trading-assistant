// frontend/lib/portfolioHistory.ts
// Pure transforms over closed-trade history: ISO-week aggregation + CSV export.
// No React, no DOM — unit-tested in lib/__tests__/portfolioHistory.test.ts.
import type { ClosedPosition } from './performanceStore';

export interface WeekAgg {
  isoWeek: number;                  // 1..53
  start: Date;                      // Monday (local)
  end: Date;                        // Sunday (local)
  days: (number | undefined)[];     // 7 daily realized $ (undefined = no trades that day)
  totalDollar: number;              // weekly realized $
  totalCostBasis: number;           // sum(entryPrice*100*qtyClosed) for the week
  pct: number;                      // weekly return % (totalDollar/totalCostBasis*100, 0 if no cost)
}

const DAY_MS = 24 * 60 * 60 * 1000;

/** Local-time 'YYYY-MM-DD'. */
export function ymd(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** ISO-8601 week number (1..53) and the ISO year that owns it. */
export function isoWeek(date: Date): { isoYear: number; week: number } {
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const dayNum = (d.getUTCDay() + 6) % 7;        // Mon=0 … Sun=6
  d.setUTCDate(d.getUTCDate() - dayNum + 3);     // shift to the week's Thursday
  const isoYear = d.getUTCFullYear();
  const firstThursday = new Date(Date.UTC(isoYear, 0, 4));
  const ftDayNum = (firstThursday.getUTCDay() + 6) % 7;
  firstThursday.setUTCDate(firstThursday.getUTCDate() - ftDayNum + 3);
  const week = 1 + Math.round((d.getTime() - firstThursday.getTime()) / (7 * DAY_MS));
  return { isoYear, week };
}

/** Monday (local) of ISO week 1 for the given ISO year. */
function isoWeek1Monday(isoYear: number): Date {
  const jan4 = new Date(isoYear, 0, 4);
  const dayNum = (jan4.getDay() + 6) % 7; // Mon=0
  const monday = new Date(jan4);
  monday.setDate(jan4.getDate() - dayNum);
  monday.setHours(0, 0, 0, 0);
  return monday;
}

/** All ISO weeks of `isoYear`, each aggregated from `history` by exit date. */
export function aggregateWeeks(history: ClosedPosition[], isoYear: number): WeekAgg[] {
  const byDay = new Map<string, { dollar: number; cost: number }>();
  for (const h of history) {
    const key = (h.exitDate ?? '').slice(0, 10);
    if (!key) continue;
    const cost = h.entryPrice * 100 * h.qtyClosed;
    const cur = byDay.get(key) ?? { dollar: 0, cost: 0 };
    cur.dollar += h.realizedPnlDollar;
    cur.cost += cost;
    byDay.set(key, cur);
  }

  const start = isoWeek1Monday(isoYear);
  const nextYearStart = isoWeek1Monday(isoYear + 1);
  const weeks: WeekAgg[] = [];
  const cursor = new Date(start);
  let wk = 1;
  while (cursor < nextYearStart) {
    const weekStart = new Date(cursor);
    const days: (number | undefined)[] = [];
    let totalDollar = 0;
    let totalCost = 0;
    for (let i = 0; i < 7; i++) {
      const rec = byDay.get(ymd(cursor));
      days.push(rec ? rec.dollar : undefined);
      if (rec) {
        totalDollar += rec.dollar;
        totalCost += rec.cost;
      }
      cursor.setDate(cursor.getDate() + 1);
    }
    const end = new Date(weekStart);
    end.setDate(weekStart.getDate() + 6);
    weeks.push({
      isoWeek: wk,
      start: weekStart,
      end,
      days,
      totalDollar: Math.round(totalDollar * 100) / 100,
      totalCostBasis: Math.round(totalCost * 100) / 100,
      pct: totalCost > 0 ? (totalDollar / totalCost) * 100 : 0,
    });
    wk++;
  }
  return weeks;
}

/** Sorted distinct ISO years that contain at least one closed trade. */
export function tradeYears(history: ClosedPosition[]): number[] {
  const years = new Set<number>();
  for (const h of history) {
    const key = (h.exitDate ?? '').slice(0, 10);
    if (key) years.add(isoWeek(new Date(`${key}T00:00:00`)).isoYear);
  }
  return Array.from(years).sort((a, b) => a - b);
}

/** CSV text of all closed trades (header + one row per trade). */
export function toHistoryCsv(history: ClosedPosition[]): string {
  const header = ['Exit Date', 'Entry Date', 'Symbol', 'Contract', 'Direction', 'Qty', 'Entry', 'Exit', 'P&L $', 'P&L %'];
  const esc = (s: string) => (/[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);
  const rows = history.map((h) => [
    h.exitDate ?? '',
    h.entryDate ?? '',
    h.symbol,
    h.contract,
    h.direction,
    String(h.qtyClosed),
    h.entryPrice.toFixed(2),
    h.exitPrice.toFixed(2),
    h.realizedPnlDollar.toFixed(2),
    h.realizedPnlPct.toFixed(2),
  ]);
  return [header, ...rows].map((r) => r.map(esc).join(',')).join('\n');
}
