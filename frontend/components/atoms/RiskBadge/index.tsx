import type { Status } from '@/lib/status';
import { Tooltip } from '@/components/atoms/Tooltip';
import styles from './RiskBadge.module.css';

interface RiskBadgeProps {
  status: Status;
  label?: string;
  className?: string;
  /** Business-interpretation tooltip shown on hover. */
  tooltip?: string;
  tooltipPosition?: 'top' | 'bottom';
  tooltipAlign?: 'center' | 'right';
}

const STATUS_CLASS: Record<Status, string> = {
  PASS: styles.pass,
  CAUTION: styles.caution,
  REJECT: styles.reject,
  PENDING: styles.pending,
  NO_DATA: styles.noData,
};

export function RiskBadge({ status, label, className, tooltip, tooltipPosition, tooltipAlign }: RiskBadgeProps) {
  const badge = (
    <span className={[styles.badge, STATUS_CLASS[status], className].filter(Boolean).join(' ')}>
      {label ?? status}
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
