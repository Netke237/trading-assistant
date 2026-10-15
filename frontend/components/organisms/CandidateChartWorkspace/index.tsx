'use client';
import { createContext, useContext } from 'react';
import { useSearchParams } from 'next/navigation';
import ChartWorkspace from '@/components/organisms/ChartWorkspace';
import { parseCandidateChartContext } from '@/lib/candidateChart';
import { useOriginalBacktest } from '@/lib/useOriginalBacktest';
import type { CandidateChartContext, OriginalBacktestState } from '@/types/backtest';

export interface CandidateBacktestScope { context: CandidateChartContext | null; state: OriginalBacktestState; }
const CandidateBacktestContext = createContext<CandidateBacktestScope>({context: null, state: {status: 'idle'}});
export const useCandidateBacktest = () => useContext(CandidateBacktestContext);

/** Route boundary for original evidence; historical chart rendering is added separately. */
export default function CandidateChartWorkspace() {
  const params = useSearchParams();
  const context = parseCandidateChartContext(params);
  const state = useOriginalBacktest(context);
  return <CandidateBacktestContext.Provider value={{context, state}}><ChartWorkspace /></CandidateBacktestContext.Provider>;
}
