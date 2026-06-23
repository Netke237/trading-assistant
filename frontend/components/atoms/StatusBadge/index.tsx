/*
 * StatusBadge — PASS / CAUTION / REJECT / PENDING / NO DATA.
 * Drift log Screen 1 #5 (correct labels), Screen 3 #6 (confidence badges).
 */

import type { Status } from '@/lib/status';
import { STATUS_LABEL } from '@/lib/status';
import { Tooltip } from '@/components/atoms/Tooltip';
import styles from './StatusBadge.module.css';

interface StatusBadgeProps {
  status: Status;
  /** Optional override of the default label (e.g. 'HIGH CONFIDENCE'). */
  label?: string;
  className?: string;
  /** Business-interpretation tooltip shown on hover. */
  tooltip?: string;
  tooltipPosition?: 'top' | 'bottom';
  tooltipAlign?: 'center' | 'right';
}

const STATUS_CLASS: Record<Status, string> = {
  PASS:    styles.pass,
  CAUTION: styles.caution,
  REJECT:  styles.reject,
  PENDING: styles.pending,
  NO_DATA: styles.noData,
};

export function StatusBadge({ status, label, className, tooltip, tooltipPosition, tooltipAlign }: StatusBadgeProps) {
  const badge = (
    <span className={[styles.badge, STATUS_CLASS[status], className].filter(Boolean).join(' ')}>
      {label ?? STATUS_LABEL[status]}
    </span>
  );
  if (tooltip) {
    return (
      <Tooltip text={tooltip} position={tooltipPosition} align={tooltipAlign}>
        {badge}
      </Tooltip>
    );
  }
  return badge;
}
