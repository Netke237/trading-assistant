/*
 * EventFlag — calendar icon + "Nd". Colored by proximity. Spec §5 EVENT FLAG.
 */

import { eventProximity } from '@/lib/date';
import styles from './EventFlag.module.css';

interface EventFlagProps {
  /** Days until the event. Negative values render nothing. */
  days: number;
  /** Optional label text (for a11y / tooltip). */
  title?: string;
  className?: string;
}

const PROXIMITY_CLASS = {
  distant:  styles.distant,
  near:     styles.near,
  imminent: styles.imminent,
};

export function EventFlag({ days, title, className }: EventFlagProps) {
  if (days < 0) return null;
  const proximity = eventProximity(days);
  return (
    <span
      className={[styles.flag, PROXIMITY_CLASS[proximity], className].filter(Boolean).join(' ')}
      title={title}
    >
      <CalendarIcon />
      {days}d
    </span>
  );
}

function CalendarIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={styles.icon}
    >
      <rect x="3" y="4" width="18" height="18" rx="2" />
      <path d="M16 2v4M8 2v4M3 10h18" />
    </svg>
  );
}
