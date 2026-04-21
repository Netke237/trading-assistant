/*
 * ScoreBar — label + fill bar + value. Drift log G5, Screen 1 #6.
 *
 * Fill color is derived from the value: <50 reject, 50–70 caution, >70 pass.
 * Pass `displayValue` when the "22/30" format differs from the raw percentage
 * (e.g. 22/30 fills at ~73% but the value text shows "22/30").
 */

import { Text, Data } from '@/components/primitives';
import { statusForScore } from '@/lib/status';
import type { Status } from '@/lib/status';
import styles from './ScoreBar.module.css';

interface ScoreBarProps {
  label: string;
  value: number;          // numerator (e.g. 22)
  max?: number;           // denominator (default 100)
  displayValue?: string;  // override right-side text (e.g. "22/30")
  className?: string;
}

const FILL_CLASS: Record<Status, string> = {
  PASS:    styles.fillPass,
  CAUTION: styles.fillCaution,
  REJECT:  styles.fillReject,
  PENDING: styles.fillReject,
  NO_DATA: styles.fillReject,
};

export function ScoreBar({ label, value, max = 100, displayValue, className }: ScoreBarProps) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  const status = statusForScore(value, max);
  const text = displayValue ?? `${value}/${max}`;

  return (
    <div className={[styles.row, className].filter(Boolean).join(' ')}>
      <Text size={12} tone="secondary">
        {label}
      </Text>
      <div
        className={styles.track}
        role="progressbar"
        aria-valuenow={value}
        aria-valuemin={0}
        aria-valuemax={max}
        aria-label={`${label} score ${text}`}
      >
        <div className={[styles.fill, FILL_CLASS[status]].join(' ')} style={{ width: `${pct}%` }} />
      </div>
      <Data size={12} className={styles.value}>
        {text}
      </Data>
    </div>
  );
}
