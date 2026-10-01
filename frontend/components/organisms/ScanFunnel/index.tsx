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
  /** Several labelled removals on one stage (e.g. the stock Direction stage's
   *  "no conviction" and "no data"); parts with 0 are not shown. Overrides
   *  `rejected`/`rejectedLabel`. */
  rejectedParts?: { count: number; label: string }[];
  total: number;
  wide?: boolean;
}

function Stage({ label, count, rejected, rejectedLabel, rejectedParts, total, wide }: StageProps) {
  const pct = total > 0 ? Math.round((count / total) * 100) : 0;
  const parts = rejectedParts
    ? rejectedParts.filter((p) => p.count > 0)
    : rejected != null && rejected > 0 ? [{ count: rejected, label: rejectedLabel ?? '' }] : [];
  return (
    <>
      <div className={wide ? styles.stageWide : styles.stage}>
        <Text size={11} tone="secondary">{label}</Text>
        <Data size={12} weight={500}>{count}</Data>
        {parts.length > 0 ? (
          <span className={styles.rejected}>
            {parts.map((p) => `−${p.count}${p.label ? ` ${p.label}` : ''}`).join(' · ')}
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

/**
 * A result stored before the per-gate counters existed has none of them, and
 * `dropped()` necessarily reads absent as 0 to do any arithmetic at all. Hiding
 * the stages then leaves the chain ending on a number above Candidates with
 * nothing explaining the gap — the original complaint, relocated. Say so.
 */
function StaleCountsNote({ show, wide }: { show: boolean; wide?: boolean }) {
  if (!show) return null;
  return (
    <div className={wide ? styles.stageWide : styles.stage}>
      <Text size={11} tone="caution">
        Stored before per-gate counts were recorded — stages may not reconcile.
      </Text>
      <span />
      <span />
    </div>
  );
}

/**
 * The residual is NOT a pipeline stage. It holds raised exceptions, which can
 * abort a symbol at any point, AND any rejection whose reason matched no bucket
 * — so there is no position in the chain where subtracting it is honest:
 * placing the row after scoring claims those symbols survived scoring, which is
 * the misattribution the stage ordering below exists to avoid. Shown outside the
 * running subtraction instead, as a note on the total.
 *
 * Labelled "unattributed" rather than "errored" because a reworded reason
 * string lands here too, and calling a real gate rejection an error is the kind
 * of confident-but-wrong number this whole component was fixed to stop showing.
 */
function UnattributedNote({ count, wide }: { count: number; wide?: boolean }) {
  if (count <= 0) return null;
  return (
    <div className={wide ? styles.stageWide : styles.stage}>
      <Text size={11} tone="dim">Unattributed / errored</Text>
      <Data size={12} weight={500} tone="reject">−{count}</Data>
      <span />
    </div>
  );
}

export function ScanFunnel({ mode, pipeline }: Props) {
  if (mode === 'stock') {
    const p = pipeline as StockPipeline;
    const failedRegime    = dropped(p.failed_regime);
    const failedDirection = dropped(p.failed_direction);
    // P3a: the same gate removing a name with NO trend measurement ("no data"),
    // counted apart from a measured trend below the floor.
    const failedDirectionUnmeasured = dropped(p.failed_direction_unmeasured);
    const failedShortlist = dropped(p.failed_shortlist);
    const otherRejected   = dropped(p.other_rejected);
    // The floor THIS scan applied, read from the result (not a config fetch).
    const noConvictionLabel = typeof p.direction_min_trend === 'number'
      ? `no conviction (trend < ${p.direction_min_trend})`
      : 'no conviction';
    // Stage order MIRRORS THE BACKEND'S GATE ORDER (stock_scan.py: score ->
    // direction -> regime -> signal -> backtest). Listing them in any other
    // order still reconciles at the bottom, but every intermediate count then
    // misattributes: a "Signal — 40 remaining" row placed before the direction
    // gate implies signal ran on symbols the gate had already removed.
    // Errors come off the top, before any gate's count, because a symbol that
    // raised never produced an outcome at any gate. Every count below therefore
    // reads "symbols still in play that completed processing".
    const afterErrors    = p.scanned - otherRejected;
    const afterHistory   = afterErrors - p.failed_history;
    const afterScore     = afterHistory - p.failed_score;
    const afterDirection = afterScore - failedDirection - failedDirectionUnmeasured;
    const afterRegime    = afterDirection - failedRegime;
    const afterSignal    = afterRegime - p.failed_signal;
    const afterBacktest  = afterSignal - p.failed_backtest;
    return (
      <div className={styles.funnel}>
        <div className={styles.header}>
          <Text size={11} tone="dim" weight={500}>STOCK PIPELINE</Text>
        </div>
        <Stage label="Universe"   count={p.scanned}    total={p.scanned} />
        {/* Stock needs this as much as options: a persisted stock result from
            before these counters existed had its direction-conviction
            rejections sitting inside other_rejected, so without the note the
            funnel labels real gate rejections "Unattributed / errored" — the
            very thing UnattributedNote's own docstring says it exists to
            avoid. This was the last asymmetry between the two modes. */}
        <StaleCountsNote show={
          p.other_rejected === undefined
          || p.failed_direction === undefined
          || p.failed_shortlist === undefined
        } />
        <UnattributedNote count={otherRejected} />
        <Stage label="History"    count={afterHistory}  rejected={p.failed_history}  rejectedLabel="no history" total={p.scanned} />
        <Stage label="Score gate" count={afterScore}    rejected={p.failed_score}    rejectedLabel="REJECT"     total={p.scanned} />
        {failedDirection + failedDirectionUnmeasured > 0 && (
          <Stage label="Direction" count={afterDirection} total={p.scanned} rejectedParts={[
            { count: failedDirection, label: noConvictionLabel },
            { count: failedDirectionUnmeasured, label: 'no data' },
          ]} />
        )}
        {failedRegime > 0 && (
          <Stage label="Regime"    count={afterRegime}    rejected={failedRegime}    rejectedLabel="headwind"      total={p.scanned} />
        )}
        <Stage label="Signal"     count={afterSignal}   rejected={p.failed_signal}   rejectedLabel="no setup"   total={p.scanned} />
        <Stage label="Backtest"   count={afterBacktest} rejected={p.failed_backtest} rejectedLabel="gate fail"  total={p.scanned} />
        {failedShortlist > 0 && (
          <Stage label="Shortlist cap" count={afterBacktest - failedShortlist} rejected={failedShortlist} rejectedLabel="over cap" total={p.scanned} />
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
  const failedDirection = dropped(p.failed_direction);
  // Names whose trend was UNMEASURED are removed right after the pre-screen,
  // before the chain fetch (routers/scan.py _process_symbol), so they come off
  // there — counting them under the later Direction stage showed them as
  // having passed chain and contracts.
  const failedDirectionUnmeasured = dropped(p.failed_direction_unmeasured);
  const failedShortlist = dropped(p.failed_shortlist);
  const otherRejected   = dropped(p.other_rejected);
  // The floor THIS scan applied, read from the result (not a config fetch).
  const noConvictionLabel = typeof p.direction_min_trend === 'number'
    ? `no conviction (trend < ${p.direction_min_trend})`
    : 'no conviction';
  // Unattributed off the top — see UnattributedNote.
  const afterErrors     = p.scanned - otherRejected;
  const afterData       = afterErrors - p.failed_data;
  const afterPreScreen  = afterData - p.failed_pre_screen;
  const afterMeasured   = afterPreScreen - failedDirectionUnmeasured;
  const afterChain      = afterMeasured - p.no_chain;
  const afterScored     = afterChain - p.failed_score - p.failed_contracts;
  const afterDirection  = afterScored - failedDirection;
  return (
    <div className={styles.funnel}>
      <div className={styles.header}>
        <Text size={11} tone="dim" weight={500}>OPTIONS PIPELINE</Text>
      </div>
      <Stage wide label="Universe"        count={p.scanned}      total={p.scanned} />
      {/* ANY missing counter, not all of them. The first version of this change
          shipped `failed_direction`/`failed_shortlist` without `other_rejected`,
          so a blob stored then has one and not the other — requiring both to be
          absent would hide the warning on exactly that blob, where the chain is
          short by however many symbols errored. */}
      <StaleCountsNote wide show={
        p.other_rejected === undefined
        || p.failed_direction === undefined
        || p.failed_shortlist === undefined
      } />
      <UnattributedNote wide count={otherRejected} />
      <Stage wide label="Data / Filters (data/price/cap)" count={afterData}      rejected={p.failed_data}       rejectedLabel="filtered"  total={p.scanned} />
      <Stage wide label="Pre-screen (setup score)"        count={afterPreScreen} rejected={p.failed_pre_screen} rejectedLabel="score low" total={p.scanned} />
      {failedDirectionUnmeasured > 0 && (
        <Stage wide label="Trend measurement (direction gate)" count={afterMeasured} rejected={failedDirectionUnmeasured} rejectedLabel="no data" total={p.scanned} />
      )}
      <Stage wide label="Option chain (DTE window)"       count={afterChain}     rejected={p.no_chain}          rejectedLabel="no chain"  total={p.scanned} />
      <Stage wide label="Score + contracts (final + rules)" count={afterScored} rejected={p.failed_score + p.failed_contracts} rejectedLabel="rejected" total={p.scanned} />
      {failedDirection > 0 && (
        <Stage wide label="Direction conviction" count={afterDirection} rejected={failedDirection} rejectedLabel={noConvictionLabel} total={p.scanned} />
      )}
      {failedShortlist > 0 && (
        <Stage wide label="Shortlist cap" count={afterDirection - failedShortlist} rejected={failedShortlist} rejectedLabel="over cap" total={p.scanned} />
      )}
      <div className={styles.divider} />
      <div className={styles.finalStageWide}>
        <Text size={12} tone="pass" weight={500}>Candidates</Text>
        <Data size={13} weight={500} tone="pass">{p.candidates}</Data>
      </div>
    </div>
  );
}
