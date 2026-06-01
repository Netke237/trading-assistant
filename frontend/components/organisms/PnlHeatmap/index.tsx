'use client';

/*
 * PnlHeatmap — calendar-week grid of daily realized P&L.
 *
 * One row per calendar week (Monday-anchored), labelled with the week's
 * start date; seven small cells per row, Mon→Sun. Each cell is tinted green
 * for a net-profit day and red for a net-loss day, scaled by magnitude.
 * Source: realized P&L summed by a closed trade's exit date.
 */

import { useMemo } from 'react';
import { Text } from '@/components/primitives';
import type { ClosedPosition } from '@/lib/performanceStore';
import styles from './PnlHeatmap.module.css';

const WEEKS = 26;
const DOW_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

interface DayCell {
  key: string;
  date: Date;
  pnl: number | undefined; // undefined = no trades that day (or future)
}

interface WeekRow {
  start: Date;
  days: DayCell[];
}

function ymd(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** Tint by sign and magnitude, following the project's color-mix status pattern. */
function cellColor(pnl: number | undefined, maxAbs: number): string {
  if (pnl === undefined || pnl === 0 || maxAbs === 0) return 'var(--bg-surface-2)';
  const ratio = Math.min(1, Math.abs(pnl) / maxAbs);
  const pct = 20 + Math.round(ratio * 60); // 20% … 80%
  const base = pnl > 0 ? 'var(--pass)' : 'var(--reject)';
  return `color-mix(in srgb, ${base} ${pct}%, var(--bg-surface))`;
}

export function PnlHeatmap({ history }: { history: ClosedPosition[] }) {
  const { weeks, maxAbs } = useMemo(() => {
    const byDay = new Map<string, number>();
    for (const h of history) {
      const key = (h.exitDate ?? '').slice(0, 10);
      if (!key) continue;
      byDay.set(key, (byDay.get(key) ?? 0) + h.realizedPnlDollar);
    }

    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const start = new Date(today);
    const mondayOffset = (today.getDay() + 6) % 7;
    start.setDate(today.getDate() - mondayOffset - (WEEKS - 1) * 7);

    const rows: WeekRow[] = [];
    let max = 0;
    const cursor = new Date(start);
    for (let w = 0; w < WEEKS; w++) {
      const weekStart = new Date(cursor);
      const days: DayCell[] = [];
      for (let d = 0; d < 7; d++) {
        const key = ymd(cursor);
        const future = cursor > today;
        const pnl = !future && byDay.has(key) ? byDay.get(key)! : undefined;
        if (pnl !== undefined) max = Math.max(max, Math.abs(pnl));
        days.push({ key, date: new Date(cursor), pnl });
        cursor.setDate(cursor.getDate() + 1);
      }
      rows.push({ start: weekStart, days });
    }
    return { weeks: rows, maxAbs: max };
  }, [history]);

  return (
    <div className={styles.wrap}>
      <div className={styles.title}>
        <Text size={11} tone="dim">Daily realized P&amp;L by calendar week — last {WEEKS} weeks</Text>
      </div>

      <div className={styles.table}>
        <div className={styles.headRow}>
          <span className={styles.weekLabel} />
          {DOW_LABELS.map((d) => (
            <span key={d} className={styles.dowLabel}>{d}</span>
          ))}
        </div>

        {weeks.map((week) => (
          <div key={week.start.toISOString()} className={styles.weekRow}>
            <span className={styles.weekLabel}>
              {week.start.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })}
            </span>
            {week.days.map((day) => (
              <div
                key={day.key}
                className={styles.cell}
                style={{ background: cellColor(day.pnl, maxAbs) }}
                title={
                  day.pnl === undefined
                    ? `${day.key} — no trades`
                    : `${day.key} — ${day.pnl > 0 ? '+' : ''}$${Math.round(day.pnl)}`
                }
              />
            ))}
          </div>
        ))}
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
