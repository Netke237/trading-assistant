'use client';
import { useEffect, useMemo, useState } from 'react';
import { api, BacktestArtifactError } from '@/lib/api';
import type { BacktestArtifact, CandidateChartContext, OriginalBacktestState } from '@/types/backtest';

function initialState(context: CandidateChartContext | null, activeSymbol: string | null): OriginalBacktestState {
  if (!context) return {status: 'idle'};
  if (context.source === 'prebreakout' || context.source === 'fib') return {status: 'unavailable', reason: 'unsupported'};
  if (activeSymbol !== context.symbol) return {status: 'unavailable', reason: 'context_mismatch'};
  if (context.status !== 'available') return {status: 'unavailable', reason: context.status};
  if (!context.artifactId) return {status: 'unavailable', reason: 'original_unavailable'};
  return {status: 'loading'};
}

export function useOriginalBacktest(context: CandidateChartContext | null, activeSymbol: string | null = context?.symbol ?? null): OriginalBacktestState {
  const key = JSON.stringify([context?.source, context?.symbol, context?.artifactId, context?.status, activeSymbol]);
  // A new token on every transition also invalidates A -> B -> A before effects run.
  const token = useMemo(() => ({key}), [key]);
  const [reply, setReply] = useState<{token: typeof token; state: OriginalBacktestState} | null>(null);
  const initial = initialState(context, activeSymbol);
  const source = context?.source;
  const symbol = context?.symbol;
  const artifactId = context?.artifactId;
  const status = context?.status;
  useEffect(() => {
    const selected = source && symbol ? {source, symbol, artifactId: artifactId ?? null, status: status!} : null;
    if (initialState(selected, activeSymbol).status !== 'loading' || !artifactId || !symbol) return;
    const controller = new AbortController();
    let active = true;
    api.getOriginalBacktest(artifactId, symbol, controller.signal).then((artifact: BacktestArtifact) => {
      if (!active) return;
      const matches = artifact?.schema_version === 1 && artifact?.artifact_id === artifactId &&
        artifact?.identity?.symbol === symbol && artifact?.provenance === 'original' && artifact?.detail?.status === 'success';
      setReply({token, state: matches ? {status: 'ready', artifact} : {status: 'unavailable', reason: 'invalid_evidence'}});
    }).catch((error: unknown) => {
      if (!active) return;
      setReply({token, state: {status: 'unavailable', reason: error instanceof BacktestArtifactError ? error.reason : 'failed'}});
    });
    return () => {active = false; controller.abort();};
  }, [token, source, symbol, artifactId, status, activeSymbol]);
  // This guard runs during render, before the previous request effect cleans up.
  return initial.status !== 'loading' ? initial : reply?.token === token ? reply.state : initial;
}
