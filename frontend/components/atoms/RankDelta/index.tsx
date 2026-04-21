/*
 * RankDelta — ▲ +2 / ▼ -1 / — 0. Drift log Screen 4 #4. Spec §5.
 */

import styles from './RankDelta.module.css';

interface RankDeltaProps {
  value: number;
  className?: string;
}

export function RankDelta({ value, className }: RankDeltaProps) {
  if (value === 0 || Number.isNaN(value)) {
    return <span className={[styles.delta, styles.flat, className].filter(Boolean).join(' ')}>—</span>;
  }
  const up = value > 0;
  const arrow = up ? '▲' : '▼';
  const sign = up ? '+' : '';
  return (
    <span className={[styles.delta, up ? styles.up : styles.down, className].filter(Boolean).join(' ')}>
      {arrow} {sign}{value}
    </span>
  );
}
