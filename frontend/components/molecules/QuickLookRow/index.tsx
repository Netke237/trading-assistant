import { Data } from '@/components/primitives';
import { StatusDot } from '@/components/atoms/StatusDot';
import type { Status } from '@/lib/status';
import styles from './QuickLookRow.module.css';

interface QuickLookRowProps {
  symbol: string;
  score: number;
  status: Status;
}

export function QuickLookRow({ symbol, score, status }: QuickLookRowProps) {
  return (
    <div className={styles.root}>
      <StatusDot tone={status} size="sm" />
      <Data size={12} weight={500}>{symbol}</Data>
      <Data size={12} tone="secondary">{score}</Data>
    </div>
  );
}
