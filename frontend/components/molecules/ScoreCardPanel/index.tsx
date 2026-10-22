/*
 * ScoreCardPanel — title + list of ScoreBars + total score + confidence badge.
 * Used in TradeCard (Stock Scorecard, Contract Scorecard) and the right rail.
 */

import { Text, Data } from '@/components/primitives';
import { ScoreBar } from '@/components/atoms/ScoreBar';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { ConfidenceBadge } from '@/components/atoms/ConfidenceBadge';
import type { Status } from '@/lib/status';
import { TradeCardQualification, type QualificationPresentation } from '@/components/molecules/TradeCardQualification';
import { CollapsibleSection } from '@/components/molecules/CollapsibleSection';
import styles from './ScoreCardPanel.module.css';

export interface ScoreBarData {
  label: string;
  value: number;
  max?: number;
  displayValue?: string;
  detailText?: string;
}

interface ScoreCardPanelProps {
  title: string;
  bars: ScoreBarData[];
  total: number;
  totalMax?: number;
  confidence: Status;
  /** Optional numeric signal-confidence (0–100); when set, shown left of the status badge. */
  confidenceScore?: number | null;
  confidenceText?: string | null;
  /** Business-interpretation tooltip for the status badge. */
  statusTooltip?: string;
  /** Right-align the status tooltip panel (use when the panel sits near the right edge). */
  statusTooltipAlignRight?: boolean;
  /** Opt-in captured evidence presentation; supply the same result as the bars/total. */
  qualification?: QualificationPresentation;
  className?: string;
}

export function ScoreCardPanel({
  title,
  bars,
  total,
  totalMax = 100,
  confidence,
  confidenceScore,
  confidenceText,
  statusTooltip,
  statusTooltipAlignRight,
  className,
  qualification,
}: ScoreCardPanelProps) {
  return (
    <div className={[styles.panel, className].filter(Boolean).join(' ')}>
      <div className={styles.header}>
        <Text size={14} weight={600}>
          {title}
        </Text>
      </div>
      <div className={styles.bars}>
        {bars.map((b) => (
          <div key={b.label}>
            <ScoreBar
              label={b.label}
              value={b.value}
              max={b.max}
              displayValue={b.displayValue}
            />
            {b.detailText && (
              <Text size={11} tone="dim" className={styles.barDetail}>{b.detailText}</Text>
            )}
          </div>
        ))}
      </div>
      {qualification?.kind === 'stock' && <div className={styles.backtest}>
        <Text size={12} weight={500}>Backtested setup confidence</Text>
        <Text size={11} tone="secondary">Based on historical entry signals, adjusted for favourable versus adverse move size. This is a confidence score, not this contract’s predicted chance of profit.</Text>
        {confidenceText && <Text size={11} tone="secondary">{confidenceText}</Text>}
        {confidenceScore === undefined && <Text size={11} tone="dim">Backtest confidence not supplied</Text>}
      </div>}
      <div className={styles.footer}>
        <div className={styles.totalGroup}>
          <Text size={12} tone="secondary">
            Score
          </Text>
          <Data size={18} weight={500}>
            {total}/{totalMax}
          </Data>
        </div>
        <div className={styles.statusGroup}>
          {confidenceScore !== undefined && (
            <ConfidenceBadge confidence={confidenceScore} title={confidenceText ?? undefined} />
          )}
          <StatusBadge
            status={confidence}
            tooltip={statusTooltip}
            tooltipAlign={statusTooltipAlignRight ? 'right' : 'center'}
          />
        </div>
      </div>
      {qualification && (
        total === (qualification.kind === 'stock' ? qualification.card.stockScore : qualification.card.contractScore)
        && confidence === (qualification.kind === 'stock' ? qualification.card.stockConfidence : qualification.card.contractConfidence)
          ? <CollapsibleSection
              key={qualification.kind}
              title={`Captured ${qualification.kind} scoring evidence`}
              storageKey={`bamendjou:tradecard:${qualification.kind}:scoring-evidence:collapsed`}
              defaultCollapsed
              keepMounted
            >
              <TradeCardQualification {...qualification} />
            </CollapsibleSection>
          : <Text size={12} tone="dim">Evidence does not match displayed score</Text>
      )}
    </div>
  );
}
