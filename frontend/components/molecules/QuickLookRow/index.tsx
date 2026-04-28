import { Data } from '@/components/primitives';
import { StatusDot } from '@/components/atoms/StatusDot';
import { statusForScore } from '@/lib/status';
import type { Status } from '@/lib/status';
import styles from './QuickLookRow.module.css';

const SCORE_TONE: Record<string, 'pass' | 'caution' | 'reject'> = {
  PASS: 'pass',
  CAUTION: 'caution',
  REJECT: 'reject',
};

interface QuickLookRowProps {
  symbol: string;
  score: number;
  status: Status;
}

export function QuickLookRow({ symbol, score, status }: QuickLookRowProps) {
  const scoreTone = SCORE_TONE[statusForScore(score)];

  return (
    <div className={styles.root} aria-label={`${symbol}, score ${score}, ${status}`}>
      <StatusDot tone={status} size="sm" />
      <Data size={12} weight={500}>{symbol}</Data>
      <Data size={12} tone={scoreTone}>{score}</Data>
    </div>
  );
}
