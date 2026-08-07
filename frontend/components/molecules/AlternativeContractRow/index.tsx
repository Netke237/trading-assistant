import { Text, Data } from '@/components/primitives';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { statusForScore } from '@/lib/status';
import type { AlternativeContract } from '@/types/domain';
import styles from './AlternativeContractRow.module.css';

interface AlternativeContractRowProps {
  alt: AlternativeContract;
  rank: number;
}

export function AlternativeContractRow({ alt, rank }: AlternativeContractRowProps) {
  const rrStatus = statusForScore(alt.score);
  const rrTone =
    rrStatus === 'PASS' ? 'pass' : rrStatus === 'CAUTION' ? 'caution' : rrStatus === 'REJECT' ? 'reject' : undefined;

  return (
    <div className={styles.card}>
      <div className={styles.topRow}>
        <div className={styles.leftGroup}>
          <Text size={11} tone="dim">Alt {rank}</Text>
          <Text size={12} tone="primary">
            {alt.symbol} {alt.strike}{alt.right} {alt.expiry}
          </Text>
          <Text size={11} tone="secondary">DTE {alt.dte}</Text>
        </div>
        <div className={styles.rightGroup}>
          <StatusBadge status={alt.contractConfidence} tooltip={alt.reason} tooltipAlign="right" />
          <Data size={12} weight={500}>{alt.score}</Data>
        </div>
      </div>

      <div className={styles.metricsRow}>
        <Metric label="Mid" value={`$${alt.mid.toFixed(2)}`} />
        <Metric label="Δ" value={alt.delta.toFixed(2)} />
        <Metric label="θ" value={`$${alt.theta.toFixed(2)}`} />
        <Metric label="IV rank" value={`${alt.ivRank}`} />
        <Metric label="R/R" value={`${alt.rrRatio.toFixed(1)}×`} tone={rrTone} />
      </div>

      <Text size={11} tone="secondary" className={styles.reason}>
        {alt.reason}
      </Text>
    </div>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: 'pass' | 'caution' | 'reject';
}) {
  return (
    <div className={styles.metric}>
      <Text size={11} tone="secondary">{label}</Text>
      <Data size={12} weight={500} tone={tone}>{value}</Data>
    </div>
  );
}
