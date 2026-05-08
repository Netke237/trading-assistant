'use client';

/*
 * TradeCard — final deliverable of the 7-step Screener workflow.
 * Spec §5 Trade Card: 8 sections arranged in a 2-column layout.
 *
 *   1. Header (symbol / company / price / direction / status)
 *   2. Stock Scorecard (breakdown bars + total + confidence)
 *   3. Contract Scorecard
 *   4. Entry plan       ┐
 *   5. Exit plan        │ grouped "Plan" column
 *   6. R:R              ┘
 *   7. Final status banner
 *   8. Actions (Send to broker | View chart | Export)
 *
 * Section 8 "View chart" toggles the InlineChartPanel on step-7.
 * Drift log G8 — inline chart slides in below the card.
 */

import { useMemo, useState } from 'react';
import { Text, Data } from '@/components/primitives';
import { SymbolHeader } from '@/components/molecules/SymbolHeader';
import { ScoreCardPanel } from '@/components/molecules/ScoreCardPanel';
import { InlineChartPanel } from '@/components/organisms/InlineChartPanel';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { LabeledStatusBadge } from '@/components/molecules/LabeledStatusBadge';
import { capitalAtRisk } from '@/lib/risk';
import type { TradeCardData, TargetLevel } from '@/types/domain';
import styles from './TradeCard.module.css';

interface TradeCardProps {
  data: TradeCardData;
  /** Unique recommendation ID displayed in the UI. */
  recId?: string;
  /** Override the Send-to-broker button handler. */
  onSendToBroker?: () => void;
  /** Custom label — used by Step 7 to show basket count. */
  sendLabel?:    string;
  /** Disable the send button (e.g. empty basket). */
  sendDisabled?: boolean;
  /** Number of contracts for CaR estimate. Default 1. */
  contracts?: number;
}

function generateRecId(): string {
  return 'REC-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6).toUpperCase();
}

export function TradeCard({ data, recId: propRecId, onSendToBroker, sendLabel, sendDisabled, contracts = 1 }: TradeCardProps) {
  const [chartOpen, setChartOpen] = useState(false);
  const displayRecId = useMemo(() => propRecId ?? generateRecId(), [propRecId]);
  const car = useMemo(() => capitalAtRisk(data.contractDetails?.mid ?? 0, contracts), [data.contractDetails?.mid, contracts]);

  const stockBars = [
    { label: 'Trend',      value: data.stockBreakdown.trend      },
    { label: 'Pullback',   value: data.stockBreakdown.pullback   },
    { label: 'Trigger',    value: data.stockBreakdown.trigger    },
    { label: 'Event',      value: data.stockBreakdown.event      },
    { label: 'Volatility', value: data.stockBreakdown.volatility },
  ];

  const contractBars = [
    { label: 'DTE fit',    value: data.contractBreakdown.dteFit           },
    { label: 'Delta',      value: data.contractBreakdown.delta            },
    { label: 'IV',         value: data.contractBreakdown.ivAttractiveness },
    { label: 'Liquidity',  value: data.contractBreakdown.liquidity        },
    { label: 'Spread',     value: data.contractBreakdown.spread           },
  ];

  return (
    <div className={styles.wrap}>
      {/* 1. Header */}
      <div className={styles.headerCard}>
        <SymbolHeader
          ticker={data.symbol}
          company={data.company}
          price={data.price}
          direction={data.direction}
          status={data.status}
          size={24}
        />
      </div>

      <div className={styles.grid}>
        {/* 2. Stock Scorecard */}
        <ScoreCardPanel
          title="Stock Scorecard"
          bars={stockBars}
          total={data.stockScore}
          confidence={data.stockConfidence}
        />

        {/* 3. Contract Scorecard */}
        <ScoreCardPanel
          title={`Contract — ${data.contract}`}
          bars={contractBars}
          total={data.contractScore}
          confidence={data.contractConfidence}
        />

        {/* 3b. Contract Details (optional) */}
        {data.contractDetails && (
          <section className={styles.detailsCard}>
            <Text size={14} weight={600}>Contract Details</Text>
            <div className={styles.detailsGrid}>
              <DetailCell label="Strike"  value={`$${data.contractDetails.strike}`} />
              <DetailCell label="Expiry"  value={data.contractDetails.expiry} />
              <DetailCell label="Right"   value={data.contractDetails.right === 'C' ? 'Call' : 'Put'} />
              <DetailCell label="Mid"     value={`$${data.contractDetails.mid.toFixed(2)}`} />
              <DetailCell label="Δ"       value={data.contractDetails.delta.toFixed(2)} mono />
              <DetailCell label="Θ / day" value={`$${data.contractDetails.theta.toFixed(2)}`} mono />
              <DetailCell label="IV rank" value={`${data.contractDetails.ivRank}`} mono />
              <DetailCell label="DTE"     value={`${data.contractDetails.dte}d`} mono />
              <DetailCell label="CaR"     value={`$${car.toFixed(0)}`} mono />
            </div>
          </section>
        )}

        {/* 4. Entry plan */}
        <section className={styles.planCard}>
          <Text size={14} weight={600}>Entry Plan</Text>
          <dl className={styles.kvList}>
            <KV label="Order type"  value={data.entry.orderType} />
            <KV label="Limit"       value={`$${data.entry.limit.toFixed(2)}`} mono />
            <KV label="Max fill"    value={`$${data.entry.maxFill.toFixed(2)}`} mono />
          </dl>
        </section>

        {/* 5. Exit plan */}
        <section className={styles.planCard}>
          <Text size={14} weight={600}>Exit Plan</Text>
          <dl className={styles.kvList}>
            <KV label="Invalidation"  value={`$${data.exit.invalidation.toFixed(2)}`} mono />
            <KV label="Premium stop"  value={`$${data.exit.premiumStop.toFixed(2)}`} mono />
            <KV label="Time stop"     value={`${data.exit.timeStopDays}d`} mono />
          </dl>
        </section>

        {/* 5b. Sell-to-close plan */}
        <section className={`${styles.planCard} ${styles.targetsCard}`}>
          <Text size={14} weight={600}>Sell-to-Close Plan</Text>
          <div className={styles.targetsTable}>
            {data.exit.targets.map((t, i) => (
              <TargetRow key={t.id ?? i} index={i} target={t} totalContracts={data.contractDetails?.dte ?? 1} />
            ))}
          </div>
        </section>

        {/* 6. R:R */}
        <section className={styles.rrCard}>
          <Text size={14} weight={600}>Risk / Reward</Text>
          <div className={styles.rrBody}>
            <Data size={24} weight={500}>{data.rrRatio.toFixed(1)}×</Data>
            <Text size={11} tone="secondary">{data.rrModel}</Text>
          </div>
        </section>

        {/* 7. Final Recommendation Scorecard */}
        <section className={`${styles.scoreCard} ${styles[`final_${data.finalStatus}`]}`}>
          <div className={styles.scoreCardHeader}>
            <Text size={14} weight={600}>Final Recommendation</Text>
            <LabeledStatusBadge label="Final Status" status={data.finalStatus} />
          </div>
          <div className={styles.scoreCardBody}>
            <div className={styles.scoreRow}>
              <Text size={12} tone="secondary">Stock confidence</Text>
              <StatusBadge status={data.stockConfidence} />
            </div>
            <div className={styles.scoreRow}>
              <Text size={12} tone="secondary">Contract confidence</Text>
              <StatusBadge status={data.contractConfidence} />
            </div>
            <div className={styles.scoreRow}>
              <Text size={12} tone="secondary">R:R ratio</Text>
              <Data size={14} tone="primary">{data.rrRatio.toFixed(2)}x</Data>
            </div>
            <div className={styles.scoreRow}>
              <Text size={11} tone="dim">{data.rrModel}</Text>
            </div>
          </div>
        </section>
      </div>

      {/* 8. Actions */}
      <div className={styles.actions}>
        <button
          type="button"
          className={`${styles.btn} ${styles.btnPrimary}`}
          onClick={onSendToBroker}
          disabled={sendDisabled || !onSendToBroker}
        >
          <Text size={13} weight={500}>{sendLabel ?? 'Send to broker'}</Text>
        </button>
        <button
          type="button"
          className={styles.btn}
          onClick={() => setChartOpen((v) => !v)}
          aria-expanded={chartOpen}
        >
          <Text size={13} weight={500}>{chartOpen ? 'Hide chart' : 'View chart'}</Text>
        </button>
        <button type="button" className={styles.btn}>
          <Text size={13} weight={500}>Export JSON</Text>
        </button>
      </div>

      <div
        style={{
          borderTop: '1px solid var(--border-subtle)',
          paddingTop: 'var(--space-2)',
          marginTop: 'var(--space-2)',
        }}
      >
        <Text size={11} tone="dim">{displayRecId}</Text>
      </div>

      <InlineChartPanel
        open={chartOpen}
        symbol={data.symbol}
        onClose={() => setChartOpen(false)}
      />
    </div>
  );
}

function TargetRow({ target, index, totalContracts }: { target: TargetLevel; index: number; totalContracts: number }) {
  const statusVal = target.status;
  const rowTone = statusVal === 'HIT' ? 'pass' : statusVal === 'MISSED' ? 'reject' : undefined;
  const statusClass = statusVal ? styles[`target_${statusVal}`] : styles.target_PENDING;
  const badgeStatus = statusVal === 'HIT' ? 'PASS' : statusVal === 'MISSED' ? 'REJECT' : 'PENDING';
  const isScaleOut = target.contractsToSell !== undefined && target.contractsToSell < totalContracts;
  const label = target.id ? target.id.toUpperCase() : `T${index + 1}`;

  return (
    <div className={`${styles.targetRow} ${statusClass}`}>
      <div className={styles.targetMain}>
        <div className={styles.targetId}>
          <Text size={12} weight={600} tone={rowTone}>{label}</Text>
          {statusVal && <StatusBadge status={badgeStatus as 'PENDING' | 'PASS' | 'REJECT'} />}
        </div>
        <div className={styles.targetValues}>
          <KV label="Stock price" value={`$${(target.targetPrice ?? target.stockPrice).toFixed(2)}`} mono tone={rowTone} />
          {target.estimatedOptionPrice !== undefined && (
            <KV label="Est. option" value={`$${target.estimatedOptionPrice.toFixed(2)}`} mono tone={rowTone} />
          )}
          {target.rrContribution !== undefined && (
            <KV label="R:R" value={`${target.rrContribution.toFixed(1)}x`} mono />
          )}
          {target.contractsToSell !== undefined && (
            <KV label="Contracts" value={`${target.contractsToSell}`} mono />
          )}
        </div>
        {isScaleOut && target.contractsToSell !== undefined && (
          <Text size={11} tone="caution">
            Scale out: sell {target.contractsToSell} of {totalContracts}
          </Text>
        )}
      </div>
      {target.pricingMethod && (
        <span className={styles.pricingBadge}>
          <Text size={10} tone="dim">{target.pricingMethod}</Text>
        </span>
      )}
    </div>
  );
}

function KV({
  label,
  value,
  mono,
  tone,
}: {
  label: string;
  value: string;
  mono?: boolean;
  tone?: 'pass' | 'caution' | 'reject';
}) {
  return (
    <div className={styles.kvRow}>
      <Text size={12} tone="secondary">{label}</Text>
      {mono
        ? <Data size={13} weight={500} tone={tone}>{value}</Data>
        : <Text size={13} weight={500}>{value}</Text>}
    </div>
  );
}

function DetailCell({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className={styles.detailsCell}>
      <Text size={10} tone="dim">{label.toUpperCase()}</Text>
      {mono
        ? <Data size={13} weight={500}>{value}</Data>
        : <Text size={13} weight={500}>{value}</Text>}
    </div>
  );
}
