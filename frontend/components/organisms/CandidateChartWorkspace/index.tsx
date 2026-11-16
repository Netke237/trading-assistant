'use client';
import { createContext, useContext, useId, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import ChartWorkspace from '@/components/organisms/ChartWorkspace';
import CandidateBacktestWorkspace from '@/components/organisms/CandidateBacktestWorkspace';
import FreshBacktestControls from '@/components/organisms/FreshBacktestControls';
import { formatUtcMinute } from '@/components/organisms/CandidateBacktestWorkspace/presentation';
import { Text, Title } from '@/components/primitives';
import { parseCandidateChartContext } from '@/lib/candidateChart';
import { useOriginalBacktest } from '@/lib/useOriginalBacktest';
import type { BacktestArtifact, CandidateChartContext, OriginalBacktestState, OriginalBacktestUnavailableReason } from '@/types/backtest';
import styles from './CandidateChartWorkspace.module.css';

export interface CandidateBacktestScope { context: CandidateChartContext | null; state: OriginalBacktestState; }
const CandidateBacktestContext = createContext<CandidateBacktestScope>({context: null, state: {status: 'idle'}});
export const useCandidateBacktest = () => useContext(CandidateBacktestContext);

export function formatUnavailableReason(reason: OriginalBacktestUnavailableReason): string {
  switch (reason) {
    case 'unsupported':
      return 'unsupported (this setup type does not provide a backtest curve)';
    case 'insufficient_history':
      return 'insufficient_history (not enough price bars to run the backtest)';
    case 'storage_unavailable':
      return 'storage_unavailable (database error saving backtest artifact)';
    case 'capture_unavailable':
      return 'capture_unavailable (backtest details were not captured during scan)';
    case 'original_unavailable':
      return 'original_unavailable (no original backtest artifact was recorded)';
    case 'invalid_evidence':
      return 'invalid_evidence (backtest output could not be reconciled)';
    case 'invalid_input':
      return 'invalid_input (malformed candidate parameters)';
    case 'failed':
      return 'failed (engine error during backtest execution)';
    case 'missing':
      return 'missing (artifact record was not found)';
    case 'expired':
      return 'expired (backtest artifact has expired)';
    case 'context_mismatch':
      return 'context_mismatch (symbol does not match candidate context)';
    default:
      return reason;
  }
}

/** Route boundary keeps historical engine evidence isolated from the live workspace. */
export default function CandidateChartWorkspace() {
  const params = useSearchParams();
  const context = parseCandidateChartContext(params);
  const state = useOriginalBacktest(context);
  return <CandidateBacktestContext.Provider value={{context, state}}>
    <CandidateEvidence key={JSON.stringify(context)} context={context} state={state}/>
  </CandidateBacktestContext.Provider>;
}

const SOURCE_LABELS: Record<CandidateChartContext['source'], string> = {
  stocks: 'Stocks screener',
  prebreakout: 'Pre-Breakout screener · prebreakout',
  pullback: 'Pre-Breakout screener · pullback',
  fib: 'Pre-Breakout screener · fib',
  unknown: 'Screener candidate',
};

/** Recorded identity of the displayed run: strategy · direction · interval · first → last recorded candle. */
function runLine(artifact: BacktestArtifact): string {
  const {identity, detail} = artifact;
  const candles = detail?.candles ?? [];
  const period = candles.length ? `Recorded period ${formatUtcMinute(candles[0].time)} → ${formatUtcMinute(candles[candles.length - 1].time)} UTC` : 'Recorded period unavailable';
  return `${identity.strategy} · ${identity.direction} · Interval ${identity.interval} · ${period}`;
}

function CandidateEvidence({context,state}:CandidateBacktestScope) {
  const [fresh,setFresh]=useState<BacktestArtifact|null>(null);
  const [showFresh,setShowFresh]=useState(false);
  // Display-only disclosure; the form keeps its own fields, consent and status while closed.
  const [configuring,setConfiguring]=useState(false);
  const panelId=useId();
  const original=state.status==='ready'?state.artifact:null;
  // The standalone live chart is unchanged: no review header, disclosure or status.
  if(!context)return <ChartWorkspace />;
  const shown=showFresh&&fresh?fresh:original;
  const chip=shown?(shown.provenance==='fresh'?'Fresh run':'Original scan'):state.status==='loading'?'Loading original scan':'No original result';
  const identityText=shown?runLine(shown):state.status==='loading'?'Loading the recorded run identity…':'No recorded backtest result is displayed.';
  const symbol=shown?.identity.symbol??context.symbol;
  const pressed=(on:boolean)=>on?`${styles.choice} ${styles.choiceOn}`:styles.choice;
  return <div className={styles.review}>
    <section className={styles.header} aria-label="Backtest review">
      <div className={styles.intro}>
        <Text as="p" size={12} tone="secondary" className={styles.crumb}>{SOURCE_LABELS[context.source]} / Backtest review / {context.symbol}</Text>
        <Title as="h1" size={24} className={styles.title}>{symbol} <span className={styles.titleSub}>/ Backtest review</span></Title>
        <Text as="p" size={14} className={styles.question}>Did the strategy beat buying and holding?</Text>
        <Text as="p" size={12} tone="secondary" className={styles.runLine}>{identityText}</Text>
      </div>
      <div className={styles.actions}>
        <div className={styles.actionRow}>
          <Text as="span" size={12} className={shown?.provenance==='fresh'?`${styles.chip} ${styles.chipFresh}`:styles.chip}>{chip}</Text>
          <button type="button" className={styles.freshToggle} aria-expanded={configuring} aria-controls={panelId} onClick={()=>setConfiguring(open=>!open)}><span aria-hidden="true">+ </span>Separate fresh run</button>
        </div>
        {fresh&&<div className={styles.choices} role="group" aria-label="Backtest result selection">
          <button type="button" className={pressed(!showFresh)} aria-pressed={!showFresh} onClick={()=>setShowFresh(false)}>Show original backtest</button>
          <button type="button" className={pressed(showFresh)} aria-pressed={showFresh} onClick={()=>setShowFresh(true)}>Show fresh backtest</button>
        </div>}
      </div>
    </section>
    <div id={panelId} className={styles.freshPanel}>
      <FreshBacktestControls key={original?.artifact_id??state.status} symbol={context.symbol} original={original} open={configuring} onOpenChange={setConfiguring} onResult={artifact=>{setFresh(artifact);setShowFresh(true);}}/>
    </div>
    {shown?<div className={styles.report}><CandidateBacktestWorkspace artifact={shown}/></div>:<>
      <p role="status" className={styles.status}>{state.status === 'loading' ? 'Loading original backtest evidence…' : state.status === 'unavailable' ? `Original backtest unavailable: ${formatUnavailableReason(state.reason)}. Live chart below; no historical result has been substituted.` : 'Original backtest unavailable.'}</p>
      <div className={styles.live}><ChartWorkspace /></div>
    </>}
  </div>;
}
