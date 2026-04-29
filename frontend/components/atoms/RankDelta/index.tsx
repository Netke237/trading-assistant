/*
 * RankDelta — ▲ +2 / ▼ -1 / — 0. Drift log Screen 4 #4. Spec §5.
 */

import styles from './RankDelta.module.css';

interface RankDeltaProps {
  value: number;
  /** Used in hover tooltip: e.g. "rank" → "Up 2 ranks since last scan" */
  context?: string;
  className?: string;
}

export function RankDelta({ value, context, className }: RankDeltaProps) {
  if (value === 0 || Number.isNaN(value)) {
    const title = context ? `No change in ${context} since last scan` : undefined;
    return <span title={title} className={[styles.delta, styles.flat, className].filter(Boolean).join(' ')}>—</span>;
  }
  const up = value > 0;
  const arrow = up ? '▲' : '▼';
  const sign = up ? '+' : '';
  const abs = Math.abs(value);
  const title = context
    ? `${up ? 'Up' : 'Down'} ${abs} ${context}${abs !== 1 ? 's' : ''} since last scan`
    : undefined;
  return (
    <span title={title} className={[styles.delta, up ? styles.up : styles.down, className].filter(Boolean).join(' ')}>
      {arrow} {sign}{value}
    </span>
  );
}
