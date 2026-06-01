# Portfolio Year Heatmap + CSV Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the portfolio P&L heatmap into a scalable, per-year calendar view (one ISO year at a time, ~3× larger squares, week number + date range + weekly $ and %), and add a "Download CSV" button that exports the full closed-trade history.

**Architecture:** Frontend-only. All closed trades since inception are already returned by `GET /api/portfolio/history` and held in `usePerformanceStore().history`, so year navigation and CSV export are pure client-side transforms of that array. We extract pure, unit-tested helpers into a new `lib/portfolioHistory.ts` module, then rewrite the `PnlHeatmap` organism to consume them and add a year selector. The CSV button lives on the Portfolio History tab.

**Tech Stack:** Next.js 15 (client component), TypeScript (strict), CSS Modules, Zustand (read-only here), Jest + ts-jest for the pure helpers.

---

## Background / Domain notes (read before starting)

- **Data source type** (`frontend/lib/performanceStore.ts`):
  ```ts
  export interface ClosedPosition {
    id: string;
    recId: string;
    symbol: string;
    contract: string;
    direction: string;
    entryPrice: number;
    entryDate?: string;
    exitPrice: number;
    exitDate: string;       // 'YYYY-MM-DD'
    qtyClosed: number;
    realizedPnlDollar: number;
    realizedPnlPct: number;
    closedAt: string;
  }
  ```
  `usePerformanceStore((s) => s.history)` is a `ClosedPosition[]` containing **every** closed trade since inception (the backend never prunes it).

- **Weekly % definition (confirmed with user):** a week's return % = `(sum of realizedPnlDollar for trades closed that week) / (sum of entry cost for those trades) * 100`, where entry cost = `entryPrice * 100 * qtyClosed`. Guard division by zero → `0`.

- **Weeks are ISO-8601:** Monday-anchored; week 1 is the week containing Jan 4. An ISO year has 52 or 53 weeks. The year selector switches **ISO year**.

- **CSS tokens / conventions** (`frontend/app/globals.css`, `CLAUDE.md`): use `var(--...)` tokens only, no hardcoded colors, no card shadows, status tints via `color-mix(in srgb, var(--pass|--reject) N%, var(--bg-surface))`. Use the `Text`/`Data` primitives for typography.

- **Existing heatmap files** (to be modified):
  - `frontend/components/organisms/PnlHeatmap/index.tsx`
  - `frontend/components/organisms/PnlHeatmap/PnlHeatmap.module.css`
  These currently render a fixed 26-week, transposed grid with no totals and no navigation. They will be largely rewritten.

- **Run commands** (from `frontend/`):
  - Single test file: `npm run test -- --testPathPattern=portfolioHistory`
  - Typecheck: `npm run typecheck`

---

## File Structure

**Create:**
- `frontend/lib/portfolioHistory.ts` — pure helpers: `ymd`, `isoWeek`, `aggregateWeeks`, `tradeYears`, `toHistoryCsv`. One responsibility: transform `ClosedPosition[]` into week aggregates / CSV. No React, no DOM.
- `frontend/lib/__tests__/portfolioHistory.test.ts` — unit tests for the helpers.

**Modify:**
- `frontend/components/organisms/PnlHeatmap/index.tsx` — consume `aggregateWeeks`/`tradeYears`, add ISO-year state + ◀ ▶ navigation, render one row per ISO week (week number, date range, 7 daily squares, weekly $ and %).
- `frontend/components/organisms/PnlHeatmap/PnlHeatmap.module.css` — ~3× larger squares (36px), year-nav header, week-label / amount / pct columns.
- `frontend/app/(frame)/portfolio/page.tsx` — add a "Download CSV" button to the History tab header that builds a CSV via `toHistoryCsv` and triggers a browser download.

---

## Task 1: Pure history/aggregation helpers

**Files:**
- Create: `frontend/lib/portfolioHistory.ts`
- Test: `frontend/lib/__tests__/portfolioHistory.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/lib/__tests__/portfolioHistory.test.ts`:

```ts
import { isoWeek, aggregateWeeks, tradeYears, toHistoryCsv, ymd } from '../portfolioHistory';
import type { ClosedPosition } from '../performanceStore';

function trade(partial: Partial<ClosedPosition>): ClosedPosition {
  return {
    id: 'id', recId: 'rec', symbol: 'AAPL', contract: 'AAPL|185|2026-06-19|C',
    direction: 'Bullish', entryPrice: 1.0, entryDate: '2026-01-01', exitPrice: 2.0,
    exitDate: '2026-01-08', qtyClosed: 1, realizedPnlDollar: 100, realizedPnlPct: 100,
    closedAt: '2026-01-08T00:00:00Z', ...partial,
  };
}

describe('ymd', () => {
  it('formats a local date as YYYY-MM-DD', () => {
    expect(ymd(new Date(2026, 0, 5))).toBe('2026-01-05');
  });
});

describe('isoWeek', () => {
  it('puts 2026-01-01 (Thursday) in ISO year 2026 week 1', () => {
    expect(isoWeek(new Date(2026, 0, 1))).toEqual({ isoYear: 2026, week: 1 });
  });
  it('puts 2027-01-01 (Friday) in ISO year 2026 week 53', () => {
    // 2026 is a 53-week ISO year; 2027-01-01 falls in its last ISO week.
    expect(isoWeek(new Date(2027, 0, 1))).toEqual({ isoYear: 2026, week: 53 });
  });
});

describe('aggregateWeeks', () => {
  it('produces 53 weeks for ISO year 2026 with week 1 starting on a Monday', () => {
    const weeks = aggregateWeeks([], 2026);
    expect(weeks).toHaveLength(53);
    expect(weeks[0]!.isoWeek).toBe(1);
    expect(weeks[0]!.start.getDay()).toBe(1); // Monday
    expect(weeks[52]!.isoWeek).toBe(53);
  });

  it('sums realized $ and computes weekly % from entry cost', () => {
    // Two trades closed Tue 2026-01-06 and Wed 2026-01-07 (both in ISO week 2 of 2026).
    const history = [
      trade({ exitDate: '2026-01-06', realizedPnlDollar: 200, entryPrice: 2, qtyClosed: 1 }), // cost 200
      trade({ exitDate: '2026-01-07', realizedPnlDollar: -50, entryPrice: 1, qtyClosed: 3 }), // cost 300
    ];
    const weeks = aggregateWeeks(history, 2026);
    const wk2 = weeks.find((w) => w.isoWeek === 2)!;
    expect(wk2.totalDollar).toBe(150);
    expect(wk2.totalCostBasis).toBe(500);
    expect(wk2.pct).toBeCloseTo(30, 5); // 150/500*100
    expect(wk2.days[1]).toBe(200);      // Tuesday
    expect(wk2.days[2]).toBe(-50);      // Wednesday
    expect(wk2.days[0]).toBeUndefined();// Monday, no trades
  });

  it('returns pct 0 for a week with no trades', () => {
    const wk1 = aggregateWeeks([], 2026).find((w) => w.isoWeek === 1)!;
    expect(wk1.totalDollar).toBe(0);
    expect(wk1.pct).toBe(0);
  });
});

describe('tradeYears', () => {
  it('returns sorted distinct ISO years that have trades', () => {
    const history = [
      trade({ exitDate: '2026-06-01' }),
      trade({ exitDate: '2027-03-01' }),
      trade({ exitDate: '2026-12-30' }), // ISO week 53 → still ISO year 2026
    ];
    expect(tradeYears(history)).toEqual([2026, 2027]);
  });
});

describe('toHistoryCsv', () => {
  it('emits a header row and one row per trade with quoted commas', () => {
    const csv = toHistoryCsv([
      trade({ symbol: 'AAPL', contract: 'AAPL|185|2026-06-19|C', qtyClosed: 2,
              entryPrice: 1.5, exitPrice: 2.25, realizedPnlDollar: 150, realizedPnlPct: 50,
              exitDate: '2026-06-01', entryDate: '2026-05-01', direction: 'Bull, ish' }),
    ]);
    const lines = csv.split('\n');
    expect(lines[0]).toBe('Exit Date,Entry Date,Symbol,Contract,Direction,Qty,Entry,Exit,P&L $,P&L %');
    expect(lines[1]).toBe('2026-06-01,2026-05-01,AAPL,AAPL|185|2026-06-19|C,"Bull, ish",2,1.50,2.25,150.00,50.00');
  });

  it('returns just the header for empty history', () => {
    expect(toHistoryCsv([])).toBe('Exit Date,Entry Date,Symbol,Contract,Direction,Qty,Entry,Exit,P&L $,P&L %');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- --testPathPattern=portfolioHistory`
Expected: FAIL — `Cannot find module '../portfolioHistory'`.

- [ ] **Step 3: Write minimal implementation**

Create `frontend/lib/portfolioHistory.ts`:

```ts
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- --testPathPattern=portfolioHistory`
Expected: PASS — all tests green.

- [ ] **Step 5: Commit**

```bash
git add "frontend/lib/portfolioHistory.ts" "frontend/lib/__tests__/portfolioHistory.test.ts"
git commit -m "feat(portfolio): pure ISO-week aggregation + CSV history helpers"
```

---

## Task 2: Rewrite PnlHeatmap as a per-year calendar with weekly totals

**Files:**
- Modify (full rewrite): `frontend/components/organisms/PnlHeatmap/index.tsx`
- Modify (full rewrite): `frontend/components/organisms/PnlHeatmap/PnlHeatmap.module.css`

**Note:** This is a UI component with no Jest coverage; verification is `npm run typecheck` plus a visual check. There is no failing-test step for this task.

- [ ] **Step 1: Replace the component**

Overwrite `frontend/components/organisms/PnlHeatmap/index.tsx` with:

```tsx
'use client';

/*
 * PnlHeatmap — per-ISO-year calendar of daily realized P&L.
 *
 * One row per ISO week (Mon→Sun): week number + date range on the left, seven
 * day cells tinted green (profit) / red (loss) by magnitude, and the week's
 * total realized $ and % on the right. ◀ ▶ switch the ISO year, so the view
 * scales across years. Source: realized P&L summed by a closed trade's exit
 * date (see lib/portfolioHistory.ts).
 */

import { useMemo, useState } from 'react';
import { Text, Data } from '@/components/primitives';
import type { ClosedPosition } from '@/lib/performanceStore';
import { aggregateWeeks, isoWeek, type WeekAgg } from '@/lib/portfolioHistory';
import styles from './PnlHeatmap.module.css';

const DOW_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

/** Tint by sign and magnitude, following the project's color-mix status pattern. */
function cellColor(pnl: number | undefined, maxAbs: number): string {
  if (pnl === undefined || pnl === 0 || maxAbs === 0) return 'var(--bg-surface-2)';
  const ratio = Math.min(1, Math.abs(pnl) / maxAbs);
  const pct = 20 + Math.round(ratio * 60); // 20% … 80%
  const base = pnl > 0 ? 'var(--pass)' : 'var(--reject)';
  return `color-mix(in srgb, ${base} ${pct}%, var(--bg-surface))`;
}

function fmtDay(d: Date): string {
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
}

export function PnlHeatmap({ history }: { history: ClosedPosition[] }) {
  const currentIsoYear = useMemo(() => isoWeek(new Date()).isoYear, []);
  const [year, setYear] = useState(currentIsoYear);

  const { weeks, maxAbs } = useMemo(() => {
    const w: WeekAgg[] = aggregateWeeks(history, year);
    let max = 0;
    for (const wk of w) {
      for (const d of wk.days) {
        if (d !== undefined) max = Math.max(max, Math.abs(d));
      }
    }
    return { weeks: w, maxAbs: max };
  }, [history, year]);

  const yearTotal = useMemo(() => weeks.reduce((s, w) => s + w.totalDollar, 0), [weeks]);

  return (
    <div className={styles.wrap}>
      <div className={styles.header}>
        <Text size={11} tone="dim">Realized P&amp;L by ISO week</Text>
        <div className={styles.yearNav}>
          <button type="button" className={styles.navBtn} onClick={() => setYear((y) => y - 1)} aria-label="Previous year">‹</button>
          <Data size={13} weight={600}>{year}</Data>
          <button type="button" className={styles.navBtn} onClick={() => setYear((y) => y + 1)} aria-label="Next year">›</button>
          <Data size={12} weight={500} tone={yearTotal > 0 ? 'pass' : yearTotal < 0 ? 'reject' : undefined}>
            {yearTotal > 0 ? '+' : ''}${Math.round(yearTotal)}
          </Data>
        </div>
      </div>

      <div className={styles.table}>
        <div className={styles.headRow}>
          <span className={styles.weekLabel} />
          {DOW_LABELS.map((d) => (
            <span key={d} className={styles.dowLabel}>{d}</span>
          ))}
          <span className={styles.amount}>P&amp;L</span>
          <span className={styles.pct}>%</span>
        </div>

        {weeks.map((wk) => {
          const tone = wk.totalDollar > 0 ? 'pass' : wk.totalDollar < 0 ? 'reject' : undefined;
          const hasTrades = wk.totalCostBasis > 0;
          return (
            <div key={wk.isoWeek} className={styles.weekRow}>
              <span className={styles.weekLabel}>
                <span className={styles.weekNum}>W{String(wk.isoWeek).padStart(2, '0')}</span>
                <span className={styles.weekDates}>{fmtDay(wk.start)} – {fmtDay(wk.end)}</span>
              </span>
              {wk.days.map((d, i) => (
                <div
                  key={i}
                  className={styles.cell}
                  style={{ background: cellColor(d, maxAbs) }}
                  title={d === undefined ? 'no trades' : `${d > 0 ? '+' : ''}$${Math.round(d)}`}
                />
              ))}
              <Data size={12} weight={500} tone={tone} className={styles.amount}>
                {hasTrades ? `${wk.totalDollar > 0 ? '+' : ''}$${Math.round(wk.totalDollar)}` : '—'}
              </Data>
              <Data size={11} tone={tone} className={styles.pct}>
                {hasTrades ? `${wk.pct > 0 ? '+' : ''}${wk.pct.toFixed(1)}%` : '—'}
              </Data>
            </div>
          );
        })}
      </div>

      <div className={styles.legend}>
        <Text size={10} tone="dim">Loss</Text>
        <span className={styles.swatch} style={{ background: 'color-mix(in srgb, var(--reject) 70%, var(--bg-surface))' }} />
        <span className={styles.swatch} style={{ background: 'color-mix(in srgb, var(--reject) 35%, var(--bg-surface))' }} />
        <span className={styles.swatch} style={{ background: 'var(--bg-surface-2)' }} />
        <span className={styles.swatch} style={{ background: 'color-mix(in srgb, var(--pass) 35%, var(--bg-surface))' }} />
        <span className={styles.swatch} style={{ background: 'color-mix(in srgb, var(--pass) 70%, var(--bg-surface))' }} />
        <Text size={10} tone="dim">Profit</Text>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Replace the stylesheet**

Overwrite `frontend/components/organisms/PnlHeatmap/PnlHeatmap.module.css` with:

```css
.wrap {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: var(--space-3);
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.yearNav {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.navBtn {
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-size: 15px;
  line-height: 1;
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
}

.navBtn:hover {
  color: var(--text-primary);
  border-color: var(--border-strong);
}

.table {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.headRow,
.weekRow {
  display: flex;
  align-items: center;
  gap: 4px;
}

.weekLabel {
  width: 128px;
  flex-shrink: 0;
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-family: var(--font-mono), JetBrains Mono, monospace;
}

.weekNum {
  font-size: 11px;
  color: var(--text-secondary);
}

.weekDates {
  font-size: 10px;
  color: var(--text-dim);
  white-space: nowrap;
}

.dowLabel {
  width: 36px;
  text-align: center;
  font-size: 10px;
  color: var(--text-dim);
  font-family: var(--font-mono), JetBrains Mono, monospace;
}

.cell {
  width: 36px;
  height: 36px;
  border-radius: 3px;
  border: 1px solid var(--border-subtle);
  flex-shrink: 0;
}

.amount {
  width: 72px;
  text-align: right;
  flex-shrink: 0;
}

.pct {
  width: 56px;
  text-align: right;
  flex-shrink: 0;
}

.legend {
  display: flex;
  align-items: center;
  gap: 4px;
  justify-content: flex-end;
}

.swatch {
  width: 11px;
  height: 11px;
  border-radius: 2px;
  border: 1px solid var(--border-subtle);
}
```

- [ ] **Step 3: Typecheck**

Run: `npm run typecheck`
Expected: clean (no output errors). If `--border-strong` is reported as unused that is fine — CSS tokens are not typechecked; only `.ts/.tsx` are.

- [ ] **Step 4: Visual check**

Start/refresh the app, go to Portfolio → History tab, scroll to the heatmap. Confirm:
- Squares are noticeably larger (36px).
- Rows are labelled `W01 … W52/53` with a date range.
- Each row shows a weekly `$` total and `%` on the right (`—` when the week had no trades).
- The ◀ ▶ buttons change the year label and re-render the grid; the year total updates.

(If port 3001 is occupied by the user's own dev server, rely on typecheck + the user's live Fast Refresh instead of `preview_start`.)

- [ ] **Step 5: Commit**

```bash
git add "frontend/components/organisms/PnlHeatmap/index.tsx" "frontend/components/organisms/PnlHeatmap/PnlHeatmap.module.css"
git commit -m "feat(portfolio): per-year heatmap with week numbers and weekly P&L totals"
```

---

## Task 3: Add a "Download CSV" button to the History tab

**Files:**
- Modify: `frontend/app/(frame)/portfolio/page.tsx`
- Modify: `frontend/app/(frame)/portfolio/page.module.css`

**Note:** UI change; verification is `npm run typecheck` plus a manual download click. No Jest test (the CSV builder itself is already tested in Task 1).

- [ ] **Step 1: Import the CSV helper**

In `frontend/app/(frame)/portfolio/page.tsx`, add to the existing import block (near the other `@/lib` imports, e.g. just after the `performanceStore` import on line 19):

```tsx
import { toHistoryCsv } from '@/lib/portfolioHistory';
```

- [ ] **Step 2: Add a download helper above the `PortfolioPage` component**

Insert just before `export default function PortfolioPage() {` (currently line 34):

```tsx
function downloadCsv(filename: string, text: string): void {
  const blob = new Blob([text], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
```

- [ ] **Step 3: Render the button on the History tab**

In the History block, the list is currently wrapped as:

```tsx
      {tab === 'history' && (
        <>
        <div className={styles.historyWrap}>
          {history.length === 0 ? (
            <Text size={13} tone="secondary">No closed trades yet.</Text>
          ) : (
          <>
          <div className={styles.historyHeader} style={{ gridTemplateColumns: HISTORY_COLUMNS }}>
```

Insert a toolbar row immediately after `<>` (i.e. between `{tab === 'history' && (` `<>` and `<div className={styles.historyWrap}>`):

```tsx
        <div className={styles.historyToolbar}>
          <Text size={12} tone="secondary">{history.length} closed trades</Text>
          <button
            type="button"
            className={styles.downloadBtn}
            onClick={() => downloadCsv('trade-history.csv', toHistoryCsv(history))}
            disabled={history.length === 0}
          >
            Download CSV
          </button>
        </div>
```

So the History block opens as:

```tsx
      {tab === 'history' && (
        <>
        <div className={styles.historyToolbar}>
          <Text size={12} tone="secondary">{history.length} closed trades</Text>
          <button
            type="button"
            className={styles.downloadBtn}
            onClick={() => downloadCsv('trade-history.csv', toHistoryCsv(history))}
            disabled={history.length === 0}
          >
            Download CSV
          </button>
        </div>
        <div className={styles.historyWrap}>
```

- [ ] **Step 4: Add toolbar styles**

Append to `frontend/app/(frame)/portfolio/page.module.css`:

```css
.historyToolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-2);
}

.downloadBtn {
  height: 30px;
  padding: 0 var(--space-4);
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  font-family: var(--font-dm);
  font-size: 12px;
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
}

.downloadBtn:hover:not(:disabled) {
  color: var(--text-primary);
  border-color: var(--accent);
}

.downloadBtn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
```

- [ ] **Step 5: Typecheck**

Run: `npm run typecheck`
Expected: clean.

- [ ] **Step 6: Visual check**

Portfolio → History tab: a "Download CSV" button sits top-right above the list. Clicking it downloads `trade-history.csv`; opening it shows the header row plus one row per closed trade. The button is disabled when there are no trades.

- [ ] **Step 7: Commit**

```bash
git add "frontend/app/(frame)/portfolio/page.tsx" "frontend/app/(frame)/portfolio/page.module.css"
git commit -m "feat(portfolio): download closed-trade history as CSV"
```

---

## Self-Review

**1. Spec coverage**
- "Triple the size of each square" → Task 2 CSS `.cell { width:36px; height:36px }` (was 12px).
- "Room to display all 52 weeks of a year" → Task 1 `aggregateWeeks` emits every ISO week (52 or 53); Task 2 renders one row each.
- "Display the amount of money made/lost in each week" → Task 2 `.amount` column with `wk.totalDollar`.
- "Give a number to each week" → Task 2 `W##` label from `wk.isoWeek`.
- "Weekly % too" (user's answer) → `WeekAgg.pct` (Task 1) rendered in `.pct` (Task 2).
- "Scalable across years (2027 etc.)" → Task 1 year-parameterized aggregation; Task 2 ◀ ▶ year selector defaulting to the current ISO year.
- "Downloadable list / CSV of all trades" → Task 1 `toHistoryCsv` + Task 3 button.

**2. Placeholder scan** — no TBD/TODO; every code step shows full code; test code is concrete.

**3. Type consistency** — `WeekAgg` fields (`isoWeek`, `start`, `end`, `days`, `totalDollar`, `totalCostBasis`, `pct`) are defined in Task 1 and used identically in Task 2. `aggregateWeeks(history, isoYear)`, `isoWeek(date)`, `tradeYears(history)`, `toHistoryCsv(history)` signatures match between definition (Task 1), tests (Task 1), and call sites (Tasks 2–3). `ClosedPosition` imported from `@/lib/performanceStore` everywhere.

**Note for the implementer:** the year selector intentionally allows navigating to years with no trades (e.g. 2027) — those render an empty grid with `—` totals, which is the desired "scales forward" behaviour. `tradeYears` is exported for a possible future year-range clamp but is not required by these tasks.
