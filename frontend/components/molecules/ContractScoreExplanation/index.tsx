import React from 'react';
import type { OptionContract, ComponentExplanation } from '@/types/domain';
import { Text } from '@/components/primitives/Text';
import { Data } from '@/components/primitives/Data';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import {
  getComponentDisplayName,
  formatMetricValue,
  formatPercentRatio,
  validateExplanation,
} from '@/lib/contractExplanation';
import styles from './ContractScoreExplanation.module.css';

export interface ContractScoreExplanationProps {
  id: string;
  contract: OptionContract;
}

const ContractScoreExplanationContent: React.FC<ContractScoreExplanationProps> = ({ id, contract }) => {
  const exp = contract.explanation;

  if (!exp || !validateExplanation(exp, contract.id)) {
    return (
      <div id={id} role="region" aria-label="Contract evaluation breakdown" className={styles.container}>
        <div className={styles.unavailable}>
          <Text size={12} tone="dim">
            Explanation unavailable for this result
          </Text>
        </div>
      </div>
    );
  }

  const isBlocked = exp.outcome === 'blocked';
  const componentsList = ['liquidity', 'spread', 'delta', 'dte', 'iv_rank']
    .map((k) => exp.components[k])
    .filter((c): c is ComponentExplanation => Boolean(c));

  return (
    <div id={id} role="region" aria-label={`Score explanation for ${contract.id}`} className={styles.container}>
      {/* Header with authoritative score & thresholds */}
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <div className={styles.scorePill}>
            <Text size={12} weight={500} tone="secondary">
              Composite Score:
            </Text>
            <Data
              size={18}
              weight={500}
              tone={isBlocked ? 'reject' : exp.status === 'PASS' ? 'pass' : exp.status === 'CAUTION' ? 'caution' : 'reject'}
            >
              {exp.score}
            </Data>
            {!isBlocked && exp.unrounded_score != null && (
              <Data size={12} tone="dim">
                ({exp.unrounded_score} unrounded)
              </Data>
            )}
          </div>
          <StatusBadge status={exp.status} />
        </div>
        <div className={styles.thresholds}>
          <Text size={11} tone="dim">
            Rules Applied: Pass ≥ {exp.pass_threshold} · Caution ≥ {exp.caution_threshold}
          </Text>
        </div>
      </div>

      {/* Blocked banner if contract was hard-rejected */}
      {isBlocked && (
        <div className={styles.blockedBanner}>
          <div className={styles.blockedTitle}>
            <span>⚠️</span>
            <span>Score forced to 0 by blocking rule(s)</span>
          </div>
          <div className={styles.blockersGrid}>
            {exp.blockers.map((b, i) => (
              <div key={i} className={styles.blockerItem}>
                <div className={styles.blockerHeader}>
                  <Text size={11} weight={500} tone="reject">
                    {b.label}
                  </Text>
                  <Text size={10} tone="dim">
                    {b.code}
                  </Text>
                </div>
                <div className={styles.blockerDetail}>
                  <Text size={11} tone="secondary">
                    {b.metric}:
                  </Text>
                  <Data size={11} tone="primary">
                    {b.observed != null ? String(b.observed) : '—'} {b.operator} {String(b.threshold)}
                  </Data>
                </div>
              </div>
            ))}
          </div>
          <Text size={10} tone="dim">
            Component scores below are diagnostic; final contract score is 0 due to active hard blocker(s).
          </Text>
        </div>
      )}

      {/* Low aggregate notice */}
      {!isBlocked && exp.status === 'REJECT' && (
        <div className={styles.blockedBanner} style={{ backgroundColor: 'transparent' }}>
          <Text size={12} tone="caution">
            Aggregate score ({exp.score}) is below caution threshold ({exp.caution_threshold}). No hard blockers were triggered.
          </Text>
        </div>
      )}

      {/* Five weighted component cards */}
      <div className={styles.componentsGrid}>
        {componentsList.map((comp) => {
          const isLiq = comp.name === 'liquidity';
          const isSpread = comp.name === 'spread';
          const isDelta = comp.name === 'delta';
          const isDte = comp.name === 'dte';
          const isIv = comp.name === 'iv_rank';

          return (
            <div key={comp.name} className={styles.componentCard}>
              <div className={styles.cardHeader}>
                <Text size={12} weight={500}>
                  {getComponentDisplayName(comp.name)}
                </Text>
                <Data size={12} weight={500} title="Component score out of 100">
                  {comp.raw_score}/100
                </Data>
              </div>

              <div className={styles.cardMetrics}>
                <div className={styles.metricRow}>
                  <span className={styles.metricLabel}>Weight:</span>
                  <Data size={11}>{comp.weight * 100}%</Data>
                </div>

                {isLiq && (
                  <>
                    <div className={styles.metricRow}>
                      <span className={styles.metricLabel}>Volume:</span>
                      <Data size={11}>
                        {comp.volume?.toLocaleString('en-US') ?? '—'}
                        {comp.preferred_volume_min ? ` (≥${comp.preferred_volume_min})` : ''}
                      </Data>
                    </div>
                    <div className={styles.nestedGroup}>
                      <div className={styles.metricRow}>
                        <span className={styles.metricLabel}>Open Int (nested):</span>
                        <Data size={11}>
                          {comp.open_interest?.toLocaleString('en-US') ?? '—'}
                          {comp.preferred_oi_min ? ` (≥${comp.preferred_oi_min})` : ''}
                        </Data>
                      </div>
                    </div>
                  </>
                )}

                {isSpread && (
                  <div className={styles.metricRow}>
                    <span className={styles.metricLabel}>Spread %:</span>
                    <Data size={11}>
                      {formatMetricValue(comp.observed, '%')}
                      {comp.preferred_max ? ` (≤${formatPercentRatio(comp.preferred_max)})` : ''}
                    </Data>
                  </div>
                )}

                {isDelta && (
                  <div className={styles.metricRow}>
                    <span className={styles.metricLabel}>Delta:</span>
                    <Data size={11}>
                      {formatMetricValue(comp.observed)}
                      {comp.preferred_min != null && comp.preferred_max != null
                        ? ` (${comp.preferred_min}–${comp.preferred_max})`
                        : ''}
                    </Data>
                  </div>
                )}

                {isDte && (
                  <div className={styles.metricRow}>
                    <span className={styles.metricLabel}>DTE:</span>
                    <Data size={11}>
                      {formatMetricValue(comp.observed, 'days')}
                      {comp.preferred_min != null && comp.preferred_max != null
                        ? ` (${comp.preferred_min}–${comp.preferred_max}d)`
                        : ''}
                    </Data>
                  </div>
                )}

                {isIv && (
                  <>
                    <div className={styles.metricRow}>
                      <span className={styles.metricLabel}>{comp.basis === 'rank' ? 'Underlying IV Rank:' : 'IV:'}</span>
                      <Data size={11}>{formatMetricValue(comp.observed, '', comp.basis)}</Data>
                    </div>
                    {comp.preferred_max != null && comp.basis !== 'none' && (
                      <div className={styles.metricRow}>
                        <span className={styles.metricLabel}>Preferred maximum:</span>
                        <Data size={11}>
                          ≤{' '}
                          {comp.basis === 'absolute'
                            ? `${comp.preferred_max}% IV`
                            : `${comp.preferred_max} rank`}
                        </Data>
                      </div>
                    )}
                    {comp.basis === 'none' && (
                      <Text size={10} tone="dim">
                        Neutral 50 applied (no IV data)
                      </Text>
                    )}
                  </>
                )}
              </div>

              {comp.flags.length > 0 && comp.basis !== 'none' && (
                <Text size={10} tone="caution">
                  Rule notes: {comp.flags.map(flag => flag === 'iv_rank_elevated'
                    ? (comp.basis === 'rank' ? 'IV rank above preferred maximum' : 'IV above preferred maximum')
                    : flag.replace(/_/g, ' ')).join(', ')}
                </Text>
              )}

              <div className={styles.pointsSummary}>
                <span className={styles.metricLabel}>Contribution:</span>
                <div>
                  <Data size={11} tone="pass" title={`Exact contribution: ${comp.contribution}`}>
                    +{comp.contribution.toFixed(1)}
                  </Data>
                  <Data size={11} tone={comp.lost_points > 0 ? 'caution' : 'dim'} className={styles.lostPoints} title={`Exact loss: ${comp.lost_points}`}>
                    (−{comp.lost_points.toFixed(1)} lost)
                  </Data>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {exp.hard_bounds && Object.keys(exp.hard_bounds).length > 0 && (
        <div className={styles.contextualStrip} aria-label="Effective hard bounds">
          <Text size={11}>Effective hard bounds (volume 0 is exempt when OI meets its minimum):</Text>
          {Object.entries(exp.hard_bounds).map(([key, value]) => (
            <Text key={key} size={11}>{key.replace(/_/g, ' ')}: {value}</Text>
          ))}
        </div>
      )}
      {exp.raw_inputs && Object.entries(exp.raw_inputs).some(([, value]) => value == null) && (
        <Text size={11}>Missing raw inputs: {Object.entries(exp.raw_inputs).filter(([, value]) => value == null).map(([key]) => key.replace(/_/g, ' ')).join(', ')}. Scorer-normalized values are shown above.</Text>
      )}
      {/* Footer: Largest losses + Contextual strip */}
      <div className={styles.footerSection}>
        {exp.largest_losses.length > 0 && exp.largest_losses[0].lost_points > 0 && (
          <div className={styles.lossesStrip}>
            <Text size={11} weight={500}>
              Largest Weighted Losses:
            </Text>
            {exp.largest_losses.slice(0, 3).map((loss) => (
              <span key={loss.name} className={styles.lossItem}>
                <Text size={11} tone="secondary">
                  {getComponentDisplayName(loss.name)}:
                </Text>
                <Data size={11} tone="caution">
                  −{loss.lost_points.toFixed(1)} pts
                </Data>
              </span>
            ))}
          </div>
        )}

        <div className={styles.contextualStrip}>
          <Text size={11} tone="secondary">
            Contextual Metrics (not directly weighted):
          </Text>
          <div className={styles.contextItem}>
            <Text size={11} tone="dim">
              Premium:
            </Text>
            <Data size={11}>${contract.price.toFixed(2)}</Data>
          </div>
          <div className={styles.contextItem}>
            <Text size={11} tone="dim">
              Θ/day:
            </Text>
            <Data size={11}>{contract.theta.toFixed(2)}</Data>
          </div>
          <div className={styles.contextItem}>
            <Text size={11} tone="dim">
              IV Percentile:
            </Text>
            <Data size={11}>{contract.ivPercentile != null ? contract.ivPercentile : '—'}</Data>
          </div>
        </div>
      </div>
    </div>
  );
};

export const ContractScoreExplanation = React.memo(ContractScoreExplanationContent);
