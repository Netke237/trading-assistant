'use client';
import type { OptionsPipeline } from '@/lib/scanStore';
import type { StockPipeline } from '@/types/stockDomain';
import { Text, Data } from '@/components/primitives';
import styles from './ScanFunnel.module.css';

interface StageProps {
  label: string;
  count: number;
  rejected?: number;
  rejectedLabel?: string;
  total: number;
  wide?: boolean;
}

function Stage({ label, count, rejected, rejectedLabel, total, wide }: StageProps) {
  const pct = total > 0 ? Math.round((count / total) * 100) : 0;
  return (
    <>
      <div className={wide ? styles.stageWide : styles.stage}>
        <Text size={11} tone="secondary">{label}</Text>
        <Data size={12} weight={500}>{count}</Data>
        {rejected != null && rejected > 0 ? (
          <span className={styles.rejected}>
            −{rejected}{rejectedLabel ? ` ${rejectedLabel}` : ''}
          </span>
        ) : <span />}
      </div>
      <div className={styles.bar}>
        <div className={styles.barFill} style={{ width: `${pct}%` }} />
      </div>
    </>
  );
}

interface Props {
  mode: 'options' | 'stock';
  pipeline: OptionsPipeline | StockPipeline;
}

/**
 * ONE rule for which stages render, in both modes: the fixed stages every scan
 * runs are always shown, and a CONDITIONAL gate is shown only when it actually
 * dropped something. A gate that did not run (the direction gate is defined for
 * four direction/horizon pairs only), and a counter absent from a result
 * persisted before it existed, both read as "nothing dropped" and stay hidden —
 * so the funnel never implies a gate ran, and never fabricates a zero for a
 * figure it does not have.
 */
function dropped(n: number | undefined): number {
  return n ?? 0;
}

export function ScanFunnel({ mode, pipeline }: Props) {
  if (mode === 'stock') {
    const p = pipeline as StockPipeline;
    const failedRegime    = dropped(p.failed_regime);
    const failedDirection = dropped(p.failed_direction);
    const failedShortlist = dropped(p.failed_shortlist);
    const otherRejected   = dropped(p.other_rejected);
    // Stage order MIRRORS THE BACKEND'S GATE ORDER (stock_scan.py: score ->
    // direction -> regime -> signal -> backtest). Listing them in any other
    // order still reconciles at the bottom, but every intermediate count then
    // misattributes: a "Signal — 40 remaining" row placed before the direction
    // gate implies signal ran on symbols the gate had already removed.
    const afterHistory   = p.scanned - p.failed_history;
    const afterScore     = afterHistory - p.failed_score;
    const afterDirection = afterScore - failedDirection;
    const afterRegime    = afterDirection - failedRegime;
    const afterSignal    = afterRegime - p.failed_signal;
    const afterBacktest  = afterSignal - p.failed_backtest;
    const afterOther     = afterBacktest - otherRejected;
    return (
      <div className={styles.funnel}>
        <div className={styles.header}>
          <Text size={11} tone="dim" weight={500}>STOCK PIPELINE</Text>
        </div>
        <Stage label="Universe"   count={p.scanned}    total={p.scanned} />
        <Stage label="History"    count={afterHistory}  rejected={p.failed_history}  rejectedLabel="no history" total={p.scanned} />
        <Stage label="Score gate" count={afterScore}    rejected={p.failed_score}    rejectedLabel="REJECT"     total={p.scanned} />
        {failedDirection > 0 && (
          <Stage label="Direction" count={afterDirection} rejected={failedDirection} rejectedLabel="no conviction" total={p.scanned} />
        )}
        {failedRegime > 0 && (
          <Stage label="Regime"    count={afterRegime}    rejected={failedRegime}    rejectedLabel="headwind"      total={p.scanned} />
        )}
        <Stage label="Signal"     count={afterSignal}   rejected={p.failed_signal}   rejectedLabel="no setup"   total={p.scanned} />
        <Stage label="Backtest"   count={afterBacktest} rejected={p.failed_backtest} rejectedLabel="gate fail"  total={p.scanned} />
        {otherRejected > 0 && (
          <Stage label="Other"     count={afterOther}     rejected={otherRejected}   rejectedLabel="errors"        total={p.scanned} />
        )}
        {failedShortlist > 0 && (
          <Stage label="Shortlist cap" count={afterOther - failedShortlist} rejected={failedShortlist} rejectedLabel="over cap" total={p.scanned} />
        )}
        <div className={styles.divider} />
        <div className={styles.finalStage}>
          <Text size={12} tone="pass" weight={500}>Candidates</Text>
          <Data size={13} weight={500} tone="pass">{p.candidates}</Data>
        </div>
      </div>
    );
  }

  const p = pipeline as OptionsPipeline;
  const afterData       = p.scanned - p.failed_data;
  const afterPreScreen  = afterData - p.failed_pre_screen;
  const afterChain      = afterPreScreen - p.no_chain;
  const afterScored     = afterChain - p.failed_score - p.failed_contracts;
  const failedDirection = dropped(p.failed_direction);
  const failedShortlist = dropped(p.failed_shortlist);
  const otherRejected   = dropped(p.other_rejected);
  const afterDirection  = afterScored - failedDirection;
  const afterOther      = afterDirection - otherRejected;
  return (
    <div className={styles.funnel}>
      <div className={styles.header}>
        <Text size={11} tone="dim" weight={500}>OPTIONS PIPELINE</Text>
      </div>
      <Stage wide label="Universe"        count={p.scanned}      total={p.scanned} />
      <Stage wide label="Data / Filters (data/price/cap)" count={afterData}      rejected={p.failed_data}       rejectedLabel="filtered"  total={p.scanned} />
      <Stage wide label="Pre-screen (setup score)"        count={afterPreScreen} rejected={p.failed_pre_screen} rejectedLabel="score low" total={p.scanned} />
      <Stage wide label="Option chain (DTE window)"       count={afterChain}     rejected={p.no_chain}          rejectedLabel="no chain"  total={p.scanned} />
      <Stage wide label="Score + contracts (final + rules)" count={afterScored} rejected={p.failed_score + p.failed_contracts} rejectedLabel="rejected" total={p.scanned} />
      {failedDirection > 0 && (
        <Stage wide label="Direction conviction" count={afterDirection} rejected={failedDirection} rejectedLabel="no conviction" total={p.scanned} />
      )}
      {otherRejected > 0 && (
        <Stage wide label="Other (errors / unclassified)" count={afterOther} rejected={otherRejected} rejectedLabel="errors" total={p.scanned} />
      )}
      {failedShortlist > 0 && (
        <Stage wide label="Shortlist cap" count={afterOther - failedShortlist} rejected={failedShortlist} rejectedLabel="over cap" total={p.scanned} />
      )}
      <div className={styles.divider} />
      <div className={styles.finalStageWide}>
        <Text size={12} tone="pass" weight={500}>Candidates</Text>
        <Data size={13} weight={500} tone="pass">{p.candidates}</Data>
      </div>
    </div>
  );
}
