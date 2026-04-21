/*
 * SymbolHeader — "AAPL · Apple Inc · $185.20" + status badge + direction pill.
 * Spec §Screen 2 (Stock Ranking right panel), §Screen 3 (TradeCard top).
 */

import { Text, Data } from '@/components/primitives';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import type { Status } from '@/lib/status';
import type { Direction } from '@/types/domain';
import styles from './SymbolHeader.module.css';

interface SymbolHeaderProps {
  ticker: string;
  company: string;
  price: number;
  direction: Direction;
  status: Status;
  /** Ticker size. 14 for tables/rails, 24 for TradeCard hero. */
  size?: 14 | 18 | 24;
  className?: string;
}

function DirectionPill({ direction }: { direction: Direction }) {
  const cls = direction === 'Bullish' ? styles.bullish : styles.bearish;
  return <span className={[styles.direction, cls].join(' ')}>{direction}</span>;
}

export function SymbolHeader({
  ticker,
  company,
  price,
  direction,
  status,
  size = 18,
  className,
}: SymbolHeaderProps) {
  return (
    <div className={[styles.row, className].filter(Boolean).join(' ')}>
      <div className={styles.leftGroup}>
        <Data size={size} weight={500} className={styles.ticker}>
          {ticker}
        </Data>
        <Text size={13} tone="secondary">
          {company}
        </Text>
        <Data size={14} weight={500}>
          ${price.toFixed(2)}
        </Data>
      </div>
      <StatusBadge status={status} />
      <DirectionPill direction={direction} />
    </div>
  );
}
