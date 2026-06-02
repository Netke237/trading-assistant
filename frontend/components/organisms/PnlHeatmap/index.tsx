'use client';

/*
 * PnlHeatmap — per-ISO-year calendar of daily realized P&L.
 *
 * Weeks are split into three parallel columns so the panel stays compact
 * even for years with 52–53 weeks. Each column is an independent sub-table
 * with its own DOW header row. ◀ ▶ switch the ISO year.
 *
 * Columns per week: W## | Mon–Sun cells | P&L $ | % Ret | # trades
 */

import { useMemo, useState } from 'react';
import { Text, Data } from '@/components/primitives';
import type { ClosedPosition } from '@/lib/performanceStore';
import { aggregateWeeks, isoWeek, type WeekAgg } from '@/lib/portfolioHistory';
import styles from './PnlHeatmap.module.css';

const DOW_LABELS = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];
const DOW_FULL   = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

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

// ── Column header tooltips ──────────────────────────────────────────────────
const TOOLTIP_PNL   = 'Realized P&L — sum of (exit − entry) × 100 × contracts for all trades closed in this week, in dollars.';
const TOOLTIP_PCT   = 'Return on cost — weekly P&L as a percentage of the total entry premium paid (entry price × 100 × contracts) for trades closed that week.';
const TOOLTIP_COUNT = 'Number of individual trade legs closed in this week.';

// ── WeekColumn ──────────────────────────────────────────────────────────────

function WeekColumn({ weeks, maxAbs }: { weeks: WeekAgg[]; maxAbs: number }) {
  return (
    <div className={styles.column}>
      {/* Header row */}
      <div className={styles.headRow}>
        <span className={styles.weekNumLabel} />
        {DOW_LABELS.map((d, i) => (
          <span key={i} className={styles.dowLabelSm} title={DOW_FULL[i]}>{d}</span>
        ))}
        <span className={styles.amountSm} title={TOOLTIP_PNL}>P&amp;L</span>
        <span className={styles.pctSm}    title={TOOLTIP_PCT}>% Ret</span>
        <span className={styles.countSm}  title={TOOLTIP_COUNT}>#</span>
      </div>

      {/* Week rows */}
      {weeks.map((wk) => {
        const tone = wk.totalDollar > 0 ? 'pass' as const : wk.totalDollar < 0 ? 'reject' as const : 'primary' as const;
        const hasTrades = wk.tradeCount > 0;
        const dateRange = `${fmtDay(wk.start)} – ${fmtDay(wk.end)}`;
        return (
          <div key={wk.isoWeek} className={styles.weekRow}>
            {/* Week number — date range shown on hover */}
            <span className={styles.weekNumLabel} title={dateRange}>
              W{String(wk.isoWeek).padStart(2, '0')}
            </span>

            {/* Day cells */}
            {wk.days.map((d, i) => (
              <div
                key={i}
                className={styles.cellSm}
                style={{ background: cellColor(d, maxAbs) }}
                title={d === undefined ? 'no trades' : `${DOW_FULL[i]}: ${d > 0 ? '+' : ''}$${Math.round(d)}`}
              />
            ))}

            {/* $ total */}
            <Data size={11} weight={500} tone={tone} className={styles.amountSm}>
              {hasTrades ? `${wk.totalDollar > 0 ? '+' : ''}$${Math.round(wk.totalDollar)}` : '—'}
            </Data>

            {/* % Ret */}
            <Data size={11} tone={tone} className={styles.pctSm}>
              {hasTrades ? `${wk.pct > 0 ? '+' : ''}${wk.pct.toFixed(1)}%` : '—'}
            </Data>

            {/* # trades */}
            <Data size={11} tone="primary" className={styles.countSm}>
              {hasTrades ? String(wk.tradeCount) : '—'}
            </Data>
          </div>
        );
      })}
    </div>
  );
}

// ── PnlHeatmap ──────────────────────────────────────────────────────────────

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

  // Split into 3 roughly equal columns (left to right: earlier → later weeks).
  const [col1, col2, col3] = useMemo(() => {
    const size = Math.ceil(weeks.length / 3);
    return [
      weeks.slice(0, size),
      weeks.slice(size, size * 2),
      weeks.slice(size * 2),
    ];
  }, [weeks]);

  return (
    <div className={styles.wrap}>
      {/* Header bar */}
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

      {/* 3-column table */}
      <div className={styles.columns}>
        <WeekColumn weeks={col1} maxAbs={maxAbs} />
        <WeekColumn weeks={col2} maxAbs={maxAbs} />
        <WeekColumn weeks={col3} maxAbs={maxAbs} />
      </div>

      {/* Loss–Profit legend */}
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
