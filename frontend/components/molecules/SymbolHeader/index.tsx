/*
 * SymbolHeader — "AAPL · Apple Inc · $185.20" + status badge + direction pill.
 * Spec §Screen 2 (Stock Ranking right panel), §Screen 3 (TradeCard top).
 */

import { Text, Data } from '@/components/primitives';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { Tooltip } from '@/components/atoms/Tooltip';
import { OpenChartButton } from '@/components/atoms/OpenChartButton';
import type { Status } from '@/lib/status';
import { GENERIC_STATUS_TOOLTIP } from '@/lib/statusTooltips';
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
  /** Show a jump-to-chart icon button beside the ticker. Off by default so
   *  existing call sites (step-4-ranking, analysis page) are unaffected. */
  showChartButton?: boolean;
  className?: string;
}

const DIRECTION_TOOLTIP: Record<Direction, string> = {
  Bullish: 'Scan direction: Bullish. You are looking for upward moves — call options profit when the stock rises above the strike before expiry.',
  Bearish: 'Scan direction: Bearish. You are looking for downward moves — put options profit when the stock falls below the strike before expiry.',
};

function DirectionPill({ direction }: { direction: Direction }) {
  const cls = direction === 'Bullish' ? styles.bullish : styles.bearish;
  return (
    <Tooltip text={DIRECTION_TOOLTIP[direction]} position="bottom">
      <span className={[styles.direction, cls].join(' ')}>{direction}</span>
    </Tooltip>
  );
}

export function SymbolHeader({
  ticker,
  company,
  price,
  direction,
  status,
  size = 18,
  showChartButton = false,
  className,
}: SymbolHeaderProps) {
  return (
    <div className={[styles.row, className].filter(Boolean).join(' ')}>
      <div className={styles.leftGroup}>
        {showChartButton && <OpenChartButton symbol={ticker} />}
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
      <StatusBadge status={status} tooltip={GENERIC_STATUS_TOOLTIP[status]} tooltipPosition="bottom" />
      <DirectionPill direction={direction} />
    </div>
  );
}
