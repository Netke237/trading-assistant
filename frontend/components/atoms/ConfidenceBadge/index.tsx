import { Data } from '@/components/primitives';
import { confidenceTier, confidenceTone } from '@/lib/confidenceText';
import { Tooltip } from '@/components/atoms/Tooltip';
import type { ConfidenceTier } from '@/lib/confidenceText';
import styles from './ConfidenceBadge.module.css';

const TIER_TOOLTIP: Record<ConfidenceTier, string> = {
  high:    'High signal confidence — in backtests this pattern consistently beat a 50/50 baseline by a wide margin. Trade at normal size.',
  moderate:'Moderate signal confidence — the pattern shows a positive backtest edge, but not a dominant one. Normal caution applies.',
  low:     'Low signal confidence — this pattern has historically underperformed a 50/50 baseline in backtests. The signal may still be valid, but there is less statistical backing. Consider smaller size or skipping.',
  unknown: 'Fewer than 20 non-overlapping past setups. Not enough history to validate this pattern, so it cannot reach PASS.',
};

export function ConfidenceBadge({
  confidence,
  title,
}: {
  confidence: number | null | undefined;
  title?: string;
}) {
  const tier = confidenceTier(confidence);
  const tone = confidenceTone(tier);
  const label = confidence === null || confidence === undefined ? 'Unvalidated' : `${confidence}%`;
  const tooltipText = title ?? TIER_TOOLTIP[tier];
  return (
    <Tooltip text={tooltipText}>
      <span className={styles.badge} data-tier={tier}>
        <Data size={12} weight={500} tone={tone}>
          {label}
        </Data>
      </span>
    </Tooltip>
  );
}
