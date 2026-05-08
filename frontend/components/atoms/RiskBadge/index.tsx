import type { Status } from '@/lib/status';
import styles from './RiskBadge.module.css';

interface RiskBadgeProps {
  status: Status;
  label?: string;
}

const STATUS_CLASS: Record<Status, string> = {
  PASS: styles.pass,
  CAUTION: styles.caution,
  REJECT: styles.reject,
  PENDING: styles.pending,
  NO_DATA: styles.noData,
};

export function RiskBadge({ status, label }: RiskBadgeProps) {
  return (
    <span className={[styles.badge, STATUS_CLASS[status]].filter(Boolean).join(' ')}>
      {label ?? status}
    </span>
  );
}
