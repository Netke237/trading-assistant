import { Data } from '@/components/primitives';
import { confidenceTier, confidenceTone } from '@/lib/confidenceText';
import styles from './ConfidenceBadge.module.css';

const MODERATE_TOOLTIP = 'Moderate — confidence ≥50 still passes the gate; treat with normal care';

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
  const resolvedTitle = title ?? (tier === 'moderate' ? MODERATE_TOOLTIP : undefined);
  return (
    <span className={styles.badge} data-tier={tier} title={resolvedTitle}>
      <Data size={12} weight={500} tone={tone}>
        {label}
      </Data>
    </span>
  );
}
