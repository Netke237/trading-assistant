'use client';
import { Text, Data } from '@/components/primitives';
import type { DataTone } from '@/components/primitives/Data';
import { Tooltip } from '@/components/atoms/Tooltip';
import { fundamentalScoreTooltip, safetyFlagTooltip } from '@/lib/statusTooltips';
import { toneForScore, FUNDAMENTAL_BAND } from '@/lib/status';
import type { FundamentalsOut } from '@/types/domain';
import styles from './FundamentalHealthCard.module.css';

function healthTone(score: number): DataTone {
  // Fundamentals health intentionally uses the stricter 65/40 band —
  // see FUNDAMENTAL_BAND's docstring in lib/status.ts.
  return toneForScore(score, FUNDAMENTAL_BAND);
}

export function FundamentalHealthCard({ f, compact = false }: {
  f: FundamentalsOut | null | undefined;
  compact?: boolean;
}) {
  if (!f) {
    return (
      <div className={styles.empty}>
        <Text size={12} tone="dim">Fundamental Health — no data</Text>
      </div>
    );
  }
  return (
    <div className={compact ? `${styles.card} ${styles.compact}` : styles.card}>
      <div className={styles.head}>
        <Text size={12} weight={500}>Fundamental Health</Text>
        <Tooltip text={fundamentalScoreTooltip('overall', f.score)}>
          <Data size={16} tone={healthTone(f.score)}>{f.score}</Data>
        </Tooltip>
      </div>
      <div className={styles.row}>
        <Text size={11} tone="dim">{f.quality_label} quality · {f.risk_label} risk</Text>
      </div>
      <div className={styles.buckets}>
        <div className={styles.bucket}>
          <Text size={11} tone="dim">Growth</Text>
          <Tooltip text={fundamentalScoreTooltip('growth', f.growth_score)}>
            <Data size={13} tone={healthTone(f.growth_score)}>{f.growth_score}</Data>
          </Tooltip>
        </div>
        <div className={styles.bucket}>
          <Text size={11} tone="dim">Quality</Text>
          <Tooltip text={fundamentalScoreTooltip('quality', f.quality_score)}>
            <Data size={13} tone={healthTone(f.quality_score)}>{f.quality_score}</Data>
          </Tooltip>
        </div>
        <div className={styles.bucket}>
          <Text size={11} tone="dim">Risk</Text>
          <Tooltip text={fundamentalScoreTooltip('risk', f.risk_score)}>
            <Data size={13} tone={healthTone(f.risk_score)}>{f.risk_score}</Data>
          </Tooltip>
        </div>
      </div>
      {(f.safety_flags ?? []).length > 0 && (
        <div className={styles.flags}>
          {(f.safety_flags ?? []).map(flag => (
            <Tooltip key={flag} text={safetyFlagTooltip(flag)}>
              <span className={styles.flag}>{flag.replace(/_/g, ' ')}</span>
            </Tooltip>
          ))}
        </div>
      )}
      {compact && (
        <details className={styles.definitions}>
          <summary>Score definitions & safety flags</summary>
          <div className={styles.definitionText}>
            <Text size={11} tone="secondary">{fundamentalScoreTooltip('overall', f.score)}</Text>
            <Text size={11} tone="secondary">{fundamentalScoreTooltip('growth', f.growth_score)}</Text>
            <Text size={11} tone="secondary">{fundamentalScoreTooltip('quality', f.quality_score)}</Text>
            <Text size={11} tone="secondary">{fundamentalScoreTooltip('risk', f.risk_score)}</Text>
            {(f.safety_flags ?? []).map(flag => (
              <Text key={flag} size={11} tone="secondary">{safetyFlagTooltip(flag)}</Text>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}
