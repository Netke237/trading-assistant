import { Text } from '@/components/primitives';
import { StatusDot } from '@/components/atoms/StatusDot';
import type { Status } from '@/lib/status';
import styles from './RegimeIndicator.module.css';

interface RegimeIndicatorProps {
  status: Status;
  label?: string;
}

export function RegimeIndicator({ status, label }: RegimeIndicatorProps) {
  return (
    <div className={styles.root}>
      <StatusDot tone={status} size="sm" />
      <Text size={12} tone="secondary">{label ?? 'Regime'}</Text>
    </div>
  );
}
