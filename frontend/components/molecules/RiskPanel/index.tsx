/*
 * RiskPanel — dashboard bento card showing portfolio risk metrics.
 * Reads from riskStore and portfolioStore. Auto-computes metrics on mount.
 */

'use client';

import { useEffect } from 'react';
import { Text, Data } from '@/components/primitives';
import { RiskBadge } from '@/components/atoms/RiskBadge';
import { Tooltip } from '@/components/atoms/Tooltip';
import { riskStatusTooltip } from '@/lib/statusTooltips';
import { useRiskStore } from '@/lib/riskStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import styles from './RiskPanel.module.css';

export function RiskPanel() {
  const positions = usePortfolioStore((s) => s.positions);
  const metrics = useRiskStore((s) => s.metrics);
  const limits = useRiskStore((s) => s.limits);
  const computeMetrics = useRiskStore((s) => s.computeMetrics);

  useEffect(() => {
    computeMetrics(positions);
  }, [positions, computeMetrics]);

  return (
    <div className={styles.wrap}>
      <div className={styles.grid}>
        <Stat
          label="Exposure"
          value={`${(metrics.totalExposurePct * 100).toFixed(1)}%`}
          tone={metrics.totalExposurePct > limits.maxTotalExposurePct ? 'reject' : metrics.totalExposurePct > limits.maxTotalExposurePct * 0.8 ? 'caution' : 'pass'}
          tooltip={riskStatusTooltip(metrics, limits, 'exposure')}
        />
        <Stat
          label="Positions"
          value={`${metrics.concurrentPositions} / ${limits.maxConcurrentPositions}`}
          tone={metrics.concurrentPositions >= limits.maxConcurrentPositions ? 'reject' : metrics.concurrentPositions >= limits.maxConcurrentPositions * 0.8 ? 'caution' : 'pass'}
          tooltip={riskStatusTooltip(metrics, limits, 'positions')}
        />
        <Stat
          label="Largest"
          value={`${(metrics.largestConcentrationPct * 100).toFixed(1)}% ${metrics.largestConcentrationSymbol}`}
          tone={metrics.largestConcentrationPct > limits.maxSingleTradeExposurePct ? 'reject' : metrics.largestConcentrationPct > limits.maxSingleTradeExposurePct * 0.8 ? 'caution' : 'pass'}
          tooltip={riskStatusTooltip(metrics, limits, 'concentration')}
        />
        <Stat
          label="Daily"
          value={`${metrics.dailyRecommendations} / ${limits.maxDailyRecommendations}`}
          tone={metrics.dailyRecommendations >= limits.maxDailyRecommendations ? 'reject' : metrics.dailyRecommendations >= limits.maxDailyRecommendations * 0.8 ? 'caution' : 'pass'}
          tooltip={riskStatusTooltip(metrics, limits, 'daily')}
        />
      </div>
      <div className={styles.status}>
        <RiskBadge status={metrics.status} label={metrics.status} tooltip={riskStatusTooltip(metrics, limits)} />
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
  tooltip,
}: {
  label: string;
  value: string;
  tone?: 'pass' | 'caution' | 'reject';
  tooltip?: string;
}) {
  const stat = (
    <div className={styles.stat}>
      <Text size={11} tone="secondary">{label}</Text>
      <Data size={16} weight={500} tone={tone}>{value}</Data>
    </div>
  );
  return tooltip ? <Tooltip text={tooltip}>{stat}</Tooltip> : stat;
}
