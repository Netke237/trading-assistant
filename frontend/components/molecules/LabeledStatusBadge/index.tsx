import { Text } from '@/components/primitives';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import type { Status } from '@/lib/status';
import styles from './LabeledStatusBadge.module.css';

interface LabeledStatusBadgeProps {
  label: string;
  status: Status;
  tooltip?: string;
}

export function LabeledStatusBadge({ label, status, tooltip }: LabeledStatusBadgeProps) {
  return (
    <div className={styles.root}>
      <Text size={12} tone="secondary">{label}</Text>
      <StatusBadge status={status} tooltip={tooltip} />
    </div>
  );
}
