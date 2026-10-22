import { buildCandidateChartHref, parseCandidateChartContext } from '@/lib/candidateChart';
import { formatUnavailableReason } from '@/components/organisms/CandidateChartWorkspace';
import type { OriginalBacktestUnavailableReason } from '@/types/backtest';

describe('SETUP-BACKTEST-CHART (#391) Candidate Chart & Plain Words', () => {
  const artifactId = 'c8b41724-4f45-4bb6-a973-123456789abc';

  it('builds candidate chart href for prebreakout candidates with available artifact', () => {
    const row = {
      symbol: 'AAPL',
      confidence: 88,
      direction: 'Bullish' as const,
      backtest_artifact_id: artifactId,
      backtest_artifact_status: 'available' as const,
    };
    const href = buildCandidateChartHref(row, 'prebreakout');
    const url = new URL(href, 'http://localhost');
    expect(url.pathname).toBe('/chart');
    expect(url.searchParams.get('symbol')).toBe('AAPL');
    expect(url.searchParams.get('source')).toBe('prebreakout');
    expect(url.searchParams.get('backtest_artifact_status')).toBe('available');
    expect(url.searchParams.get('backtest_artifact_id')).toBe(artifactId);
  });

  it('builds candidate chart href for fib pullback candidates with available artifact', () => {
    const row = {
      symbol: 'MSFT',
      confidence: 92,
      direction: 'Bearish' as const,
      backtest_artifact_id: artifactId,
      backtest_artifact_status: 'available' as const,
    };
    const href = buildCandidateChartHref(row, 'fib');
    const url = new URL(href, 'http://localhost');
    expect(url.pathname).toBe('/chart');
    expect(url.searchParams.get('symbol')).toBe('MSFT');
    expect(url.searchParams.get('source')).toBe('fib');
    expect(url.searchParams.get('backtest_artifact_status')).toBe('available');
    expect(url.searchParams.get('backtest_artifact_id')).toBe(artifactId);
  });

  it('parses prebreakout and fib context into CandidateChartContext with available status and artifact ID', () => {
    const query = new URLSearchParams({
      symbol: 'NVDA',
      source: 'prebreakout',
      backtest_artifact_status: 'available',
      backtest_artifact_id: artifactId,
    });
    const parsed = parseCandidateChartContext(query);
    expect(parsed).toEqual({
      source: 'prebreakout',
      symbol: 'NVDA',
      artifactId,
      status: 'available',
    });

    const fibQuery = new URLSearchParams({
      symbol: 'AMD',
      source: 'fib',
      backtest_artifact_status: 'available',
      backtest_artifact_id: artifactId,
    });
    const fibParsed = parseCandidateChartContext(fibQuery);
    expect(fibParsed).toEqual({
      source: 'fib',
      symbol: 'AMD',
      artifactId,
      status: 'available',
    });
  });

  it('formats all unavailable reasons into plain explanatory language while preserving raw tokens', () => {
    const reasons: OriginalBacktestUnavailableReason[] = [
      'unsupported',
      'insufficient_history',
      'storage_unavailable',
      'capture_unavailable',
      'original_unavailable',
      'invalid_evidence',
      'invalid_input',
      'failed',
      'missing',
      'expired',
      'context_mismatch',
    ];

    for (const reason of reasons) {
      const formatted = formatUnavailableReason(reason);
      expect(formatted).toContain(reason);
      expect(formatted.length).toBeGreaterThan(reason.length);
    }
  });
});
