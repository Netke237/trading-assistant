import { Data } from '@/components/primitives';
import { confidenceTier, confidenceTone } from '@/lib/confidenceText';
import styles from './ConfidenceBadge.module.css';

export function ConfidenceBadge({
  confidence,
  title,
}: {
  confidence: number | null | undefined;
  title?: string;
}) {
  const tier = confidenceTier(confidence);
  const tone = confidenceTone(tier);
  const label = confidence === null || confidence === undefined ? '—' : `${confidence}%`;
  return (
    <span className={styles.badge} data-tier={tier} title={title}>
      <Data size={12} weight={500} tone={tone}>
        {label}
      </Data>
    </span>
  );
}
