'use client';
import { createContext, useContext } from 'react';
import { useSearchParams } from 'next/navigation';
import ChartWorkspace from '@/components/organisms/ChartWorkspace';
import CandidateBacktestWorkspace from '@/components/organisms/CandidateBacktestWorkspace';
import { parseCandidateChartContext } from '@/lib/candidateChart';
import { useOriginalBacktest } from '@/lib/useOriginalBacktest';
import type { CandidateChartContext, OriginalBacktestState } from '@/types/backtest';

export interface CandidateBacktestScope { context: CandidateChartContext | null; state: OriginalBacktestState; }
const CandidateBacktestContext = createContext<CandidateBacktestScope>({context: null, state: {status: 'idle'}});
export const useCandidateBacktest = () => useContext(CandidateBacktestContext);

/** Route boundary keeps historical engine evidence isolated from the live workspace. */
export default function CandidateChartWorkspace() {
  const params = useSearchParams();
  const context = parseCandidateChartContext(params);
  const state = useOriginalBacktest(context);
  return <CandidateBacktestContext.Provider value={{context, state}}>
    {state.status === 'ready' ? <CandidateBacktestWorkspace artifact={state.artifact}/> : <>
      {context && <p role="status">{state.status === 'loading' ? 'Loading original backtest evidence…' : state.status === 'unavailable' ? `Original backtest unavailable: ${state.reason}. Live chart below; no historical result has been substituted.` : 'Original backtest unavailable.'}</p>}
      <ChartWorkspace />
    </>}
  </CandidateBacktestContext.Provider>;
}
