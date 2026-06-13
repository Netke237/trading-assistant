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
}

function Stage({ label, count, rejected, rejectedLabel, total }: StageProps) {
  const pct = total > 0 ? Math.round((count / total) * 100) : 0;
  return (
    <>
      <div className={styles.stage}>
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

export function ScanFunnel({ mode, pipeline }: Props) {
  if (mode === 'stock') {
    const p = pipeline as StockPipeline;
    const afterHistory = p.scanned - p.failed_history;
    const afterScore   = afterHistory - p.failed_score;
    const afterSignal  = afterScore - p.failed_signal;
    return (
      <div className={styles.funnel}>
        <div className={styles.header}>
          <Text size={11} tone="dim" weight={500}>STOCK PIPELINE</Text>
        </div>
        <Stage label="Universe"   count={p.scanned}    total={p.scanned} />
        <Stage label="History"    count={afterHistory}  rejected={p.failed_history}  rejectedLabel="no history" total={p.scanned} />
        <Stage label="Score gate" count={afterScore}    rejected={p.failed_score}    rejectedLabel="REJECT"     total={p.scanned} />
        <Stage label="Signal"     count={afterSignal}   rejected={p.failed_signal}   rejectedLabel="no setup"   total={p.scanned} />
        <Stage label="Backtest"   count={p.candidates + p.failed_backtest} rejected={p.failed_backtest} rejectedLabel="gate fail" total={p.scanned} />
        <div className={styles.divider} />
        <div className={styles.finalStage}>
          <Text size={12} tone="pass" weight={500}>Candidates</Text>
          <Data size={13} weight={500} tone="pass">{p.candidates}</Data>
        </div>
      </div>
    );
  }

  const p = pipeline as OptionsPipeline;
  const afterData      = p.scanned - p.failed_data;
  const afterPreScreen = afterData - p.failed_pre_screen;
  const afterChain     = afterPreScreen - p.no_chain;
  return (
    <div className={styles.funnel}>
      <div className={styles.header}>
        <Text size={11} tone="dim" weight={500}>OPTIONS PIPELINE</Text>
      </div>
      <Stage label="Universe"        count={p.scanned}      total={p.scanned} />
      <Stage label="Data / Filters"  count={afterData}      rejected={p.failed_data}       rejectedLabel="filtered"  total={p.scanned} />
      <Stage label="Pre-screen"      count={afterPreScreen} rejected={p.failed_pre_screen} rejectedLabel="score low" total={p.scanned} />
      <Stage label="Option chain"    count={afterChain}     rejected={p.no_chain}          rejectedLabel="no chain"  total={p.scanned} />
      <Stage label="Score + contracts" count={afterChain - p.failed_score - p.failed_contracts} rejected={p.failed_score + p.failed_contracts} rejectedLabel="rejected" total={p.scanned} />
      <div className={styles.divider} />
      <div className={styles.finalStage}>
        <Text size={12} tone="pass" weight={500}>Candidates</Text>
        <Data size={13} weight={500} tone="pass">{p.candidates}</Data>
      </div>
    </div>
  );
}
