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
  const [year, setYear] = useState(() => isoWeek(new Date()).isoYear);

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
          <Data size={13} weight={500}>{year}</Data>
          <button type="button" className={styles.navBtn} onClick={() => setYear((y) => y + 1)} aria-label="Next year">›</button>
          <Data size={12} weight={500} tone={yearTotal > 0 ? 'pass' : yearTotal < 0 ? 'reject' : 'primary'}>
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
          const tone = wk.totalDollar > 0 ? 'pass' as const : wk.totalDollar < 0 ? 'reject' as const : 'primary' as const;
          const hasTrades = wk.days.some((d) => d !== undefined);
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
