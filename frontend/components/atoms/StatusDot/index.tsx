/*
 * StatusDot — small colored circle. Used for regime indicator, nav-rail scan
 * state, alert-type left borders. Spec §4 (top bar + nav rail bottom).
 */

import type { Status } from '@/lib/status';
import styles from './StatusDot.module.css';

export type StatusDotTone = Status | 'ACCENT';

interface StatusDotProps {
  tone: StatusDotTone;
  size?: 'sm' | 'md';
  className?: string;
}

const TONE_CLASS: Record<StatusDotTone, string> = {
  PASS:    styles.pass,
  CAUTION: styles.caution,
  REJECT:  styles.reject,
  PENDING: styles.pending,
  NO_DATA: styles.noData,
  ACCENT:  styles.accent,
};

export function StatusDot({ tone, size = 'md', className }: StatusDotProps) {
  return (
    <span
      aria-hidden="true"
      className={[styles.dot, styles[size], TONE_CLASS[tone], className].filter(Boolean).join(' ')}
    />
  );
}
