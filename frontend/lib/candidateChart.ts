import type { BacktestArtifactReference, BacktestArtifactStatus, CandidateChartContext, CandidateChartSource } from '@/types/backtest';

const sources: readonly string[] = ['stocks', 'pullback', 'prebreakout', 'fib'];
const statuses: readonly string[] = ['available', 'unsupported', 'insufficient_history', 'invalid_input', 'failed', 'invalid_evidence', 'storage_unavailable', 'capture_unavailable', 'original_unavailable'];
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const symbolPattern = /^[A-Z][A-Z0-9.\-^]{0,14}$/;
const contextKeys = ['source', 'backtest_artifact_id', 'backtest_artifact_status'];
type Query = Pick<URLSearchParams, 'get' | 'getAll' | 'has'>;

export function buildCandidateChartHref(row: BacktestArtifactReference & {symbol: string; direction?: string}, source: CandidateChartSource): string {
  const query = new URLSearchParams({symbol: row.symbol, source});
  const setup = source === 'prebreakout' || source === 'fib';
  const status = setup ? 'unsupported' : row.backtest_artifact_status ?? 'original_unavailable';
  query.set('backtest_artifact_status', status);
  if (!setup && status === 'available' && row.backtest_artifact_id) query.set('backtest_artifact_id', row.backtest_artifact_id);
  return `/chart?${query}`;
}

/** Candidate scope never falls through to a symbol-only live chart when malformed. */
export function parseCandidateChartContext(query: Query | null): CandidateChartContext | null {
  if (!query || !contextKeys.some(key => query.has(key))) return null;
  const rawSource = query.get('source') ?? '';
  const source = sources.includes(rawSource) ? rawSource as CandidateChartSource : 'unknown';
  const symbol = query.get('symbol') ?? '';
  const invalid = (): CandidateChartContext => ({source, symbol, artifactId: null, status: 'invalid_input'});
  if (source === 'unknown' || !symbolPattern.test(symbol) || ['symbol', ...contextKeys].some(key => query.getAll(key).length > 1)) return invalid();
  if (source === 'prebreakout' || source === 'fib') return {source, symbol, artifactId: null, status: 'unsupported'};
  const rawStatus = query.get('backtest_artifact_status') ?? 'original_unavailable';
  if (!statuses.includes(rawStatus)) return invalid();
  const status = rawStatus as BacktestArtifactStatus;
  const artifactId = query.get('backtest_artifact_id');
  if (status === 'available' && (!artifactId || !uuid.test(artifactId))) return invalid();
  return {source, symbol, artifactId: status === 'available' ? artifactId : null, status};
}
