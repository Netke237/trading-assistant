'use client';
import { Text, Data } from '@/components/primitives';
import type { FundamentalsOut } from '@/types/domain';
import styles from './FundamentalHealthCard.module.css';

function healthTone(score: number): 'pass' | 'caution' | 'reject' {
  return score >= 65 ? 'pass' : score >= 40 ? 'caution' : 'reject';
}

export function FundamentalHealthCard({ f }: { f: FundamentalsOut | null | undefined }) {
  if (!f) {
    return (
      <div className={styles.empty}>
        <Text size={12} tone="dim">Fundamental Health — no data</Text>
      </div>
    );
  }
  return (
    <div className={styles.card}>
      <div className={styles.head}>
        <Text size={12} weight={500}>Fundamental Health</Text>
        <Data size={16} tone={healthTone(f.score)}>{f.score}</Data>
      </div>
      <div className={styles.row}>
        <Text size={11} tone="dim">{f.quality_label} quality · {f.risk_label} risk</Text>
      </div>
      <div className={styles.buckets}>
        <div className={styles.bucket}>
          <Text size={11} tone="dim">Growth</Text>
          <Data size={13} tone={healthTone(f.growth_score)}>{f.growth_score}</Data>
        </div>
        <div className={styles.bucket}>
          <Text size={11} tone="dim">Quality</Text>
          <Data size={13} tone={healthTone(f.quality_score)}>{f.quality_score}</Data>
        </div>
        <div className={styles.bucket}>
          <Text size={11} tone="dim">Risk</Text>
          <Data size={13} tone={healthTone(f.risk_score)}>{f.risk_score}</Data>
        </div>
      </div>
      {(f.safety_flags ?? []).length > 0 && (
        <div className={styles.flags}>
          {(f.safety_flags ?? []).map(flag => (
            <span key={flag} className={styles.flag}>{flag.replace(/_/g, ' ')}</span>
          ))}
        </div>
      )}
    </div>
  );
}
