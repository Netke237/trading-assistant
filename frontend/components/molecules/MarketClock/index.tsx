'use client';

import { useEffect, useState } from 'react';
import { getMarketState, formatMinutes, type MarketState, type MarketStatus } from '@/lib/marketHours';
import styles from './MarketClock.module.css';

const STATUS_CLASS: Record<MarketStatus, string> = {
  OPEN:  styles.open,
  PRE:   styles.dim,
  AFTER: styles.dim,
  CLOSED: styles.dim,
};

const STATUS_LABEL: Record<MarketStatus, string> = {
  OPEN:   'OPEN',
  PRE:    'PRE',
  AFTER:  'AFTER',
  CLOSED: 'CLOSED',
};

export function MarketClock() {
  const [state, setState] = useState<MarketState | null>(null);

  useEffect(() => {
    const update = () => setState(getMarketState(new Date()));
    update();
    const id = setInterval(update, 60_000);
    return () => clearInterval(id);
  }, []);

  if (!state) return null;

  const { status, minutesUntilChange, nextOpenLabel } = state;

  const timeText =
    status === 'CLOSED'
      ? `opens ${nextOpenLabel}`
      : formatMinutes(minutesUntilChange);

  return (
    <div className={`${styles.clock} ${STATUS_CLASS[status]}`} title="US equity market hours (open time shown in CET)">
      <span className={styles.dot} aria-hidden />
      <span className={styles.label}>{STATUS_LABEL[status]}</span>
      <span className={styles.sep} aria-hidden>·</span>
      <span className={styles.time}>{timeText}</span>
    </div>
  );
}
