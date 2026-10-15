'use client';
import { createContext, useContext, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import ChartWorkspace from '@/components/organisms/ChartWorkspace';
import CandidateBacktestWorkspace from '@/components/organisms/CandidateBacktestWorkspace';
import FreshBacktestControls from '@/components/organisms/FreshBacktestControls';
import { parseCandidateChartContext } from '@/lib/candidateChart';
import { useOriginalBacktest } from '@/lib/useOriginalBacktest';
import type { BacktestArtifact, CandidateChartContext, OriginalBacktestState } from '@/types/backtest';

export interface CandidateBacktestScope { context: CandidateChartContext | null; state: OriginalBacktestState; }
const CandidateBacktestContext = createContext<CandidateBacktestScope>({context: null, state: {status: 'idle'}});
export const useCandidateBacktest = () => useContext(CandidateBacktestContext);

/** Route boundary keeps historical engine evidence isolated from the live workspace. */
export default function CandidateChartWorkspace() {
  const params = useSearchParams();
  const context = parseCandidateChartContext(params);
  const state = useOriginalBacktest(context);
  return <CandidateBacktestContext.Provider value={{context, state}}>
    <CandidateEvidence key={JSON.stringify(context)} context={context} state={state}/>
  </CandidateBacktestContext.Provider>;
}

function CandidateEvidence({context,state}:CandidateBacktestScope) {
  const [fresh,setFresh]=useState<BacktestArtifact|null>(null);
  const [showFresh,setShowFresh]=useState(false);
  const original=state.status==='ready'?state.artifact:null;
  return <>
    {context&&<FreshBacktestControls key={original?.artifact_id??state.status} symbol={context.symbol} original={original} onResult={artifact=>{setFresh(artifact);setShowFresh(true);}}/>}
    {fresh&&<nav aria-label="Backtest result selection"><button onClick={()=>setShowFresh(false)}>Show original backtest</button><button onClick={()=>setShowFresh(true)}>Show fresh backtest</button></nav>}
    {showFresh&&fresh?<CandidateBacktestWorkspace artifact={fresh}/>:state.status === 'ready' ? <CandidateBacktestWorkspace artifact={state.artifact}/> : <>
      {context && <p role="status">{state.status === 'loading' ? 'Loading original backtest evidence…' : state.status === 'unavailable' ? `Original backtest unavailable: ${state.reason}. Live chart below; no historical result has been substituted.` : 'Original backtest unavailable.'}</p>}
      <ChartWorkspace />
    </>}
  </>;
}
