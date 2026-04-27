import { Text } from '@/components/primitives';
import { StatusDot } from '@/components/atoms/StatusDot';
import type { Status } from '@/lib/status';
import styles from './ScanIndicator.module.css';

interface ScanIndicatorProps {
  status: Status | 'ACCENT';
}

export function ScanIndicator({ status }: ScanIndicatorProps) {
  return (
    <div className={styles.root}>
      <StatusDot tone={status} size="sm" />
      <Text size={10} tone="secondary">Scan</Text>
    </div>
  );
}
