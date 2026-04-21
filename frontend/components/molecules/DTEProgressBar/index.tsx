/*
 * DTEProgressBar — days-to-expiry progress bar.
 * Color derived from % remaining. Drift log G6.
 */

import { Data } from '@/components/primitives';
import { dteFillPct, dteStatus } from '@/lib/date';
import styles from './DTEProgressBar.module.css';

interface DTEProgressBarProps {
  daysRemaining: number;
  totalDays: number;
  className?: string;
}

const STATUS_CLASS = {
  PASS:    styles.pass,
  CAUTION: styles.caution,
  REJECT:  styles.reject,
};

export function DTEProgressBar({ daysRemaining, totalDays, className }: DTEProgressBarProps) {
  const pct = dteFillPct(daysRemaining, totalDays);
  const status = dteStatus(daysRemaining, totalDays);

  return (
    <div
      className={[styles.wrap, className].filter(Boolean).join(' ')}
      role="progressbar"
      aria-valuenow={daysRemaining}
      aria-valuemin={0}
      aria-valuemax={totalDays}
      aria-label={`${daysRemaining} of ${totalDays} days remaining`}
    >
      <div className={styles.track}>
        <div className={[styles.fill, STATUS_CLASS[status]].join(' ')} style={{ width: `${pct}%` }} />
      </div>
      <Data size={11} tone="secondary" className={styles.label}>
        {daysRemaining}d
      </Data>
    </div>
  );
}
