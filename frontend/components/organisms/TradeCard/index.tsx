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

import { useState } from 'react';
import { Text, Data } from '@/components/primitives';
import { SymbolHeader } from '@/components/molecules/SymbolHeader';
import { ScoreCardPanel } from '@/components/molecules/ScoreCardPanel';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { InlineChartPanel } from '@/components/organisms/InlineChartPanel';
import type { TradeCardData } from '@/types/domain';
import styles from './TradeCard.module.css';

interface TradeCardProps {
  data: TradeCardData;
  /** Override the Send-to-broker button handler. */
  onSendToBroker?: () => void;
  /** Custom label — used by Step 7 to show basket count. */
  sendLabel?:    string;
  /** Disable the send button (e.g. empty basket). */
  sendDisabled?: boolean;
}

export function TradeCard({ data, onSendToBroker, sendLabel, sendDisabled }: TradeCardProps) {
  const [chartOpen, setChartOpen] = useState(false);

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
            <KV label="Target"        value={`$${data.exit.target.toFixed(2)}`} mono tone="pass" />
          </dl>
        </section>

        {/* 6. R:R */}
        <section className={styles.rrCard}>
          <Text size={14} weight={600}>Risk / Reward</Text>
          <div className={styles.rrBody}>
            <Data size={24} weight={500}>{data.rrRatio.toFixed(1)}×</Data>
            <Text size={11} tone="secondary">{data.rrModel}</Text>
          </div>
        </section>

        {/* 7. Final status */}
        <section className={`${styles.finalCard} ${styles[`final_${data.finalStatus}`]}`}>
          <Text size={14} weight={600}>Final Status</Text>
          <StatusBadge status={data.finalStatus} />
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

      <InlineChartPanel
        open={chartOpen}
        symbol={data.symbol}
        onClose={() => setChartOpen(false)}
      />
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
