import '@testing-library/jest-dom';
import { render, screen, within } from '@testing-library/react';
import { TiingoBudget, formatBytes, meterTone, formatDuration } from '..';
import type { IngestionStatus, TiingoUsage } from '@/lib/api';

// HISTORY-INCREMENTAL-NIGHTLY C1 (#572): Settings -> Data shows the Tiingo budget
// and the last ingestion run, read from GET /api/data/ingest/status. The shapes
// below mirror backend/app/routers/ingestion.py (ingest_status),
// services/ingestion_job.py (_state + RUN_COUNTERS) and data/tiingo_budget.py
// (usage_summary, _window_label).

const STARTED = '2026-11-05T02:00:00+00:00';
const FINISHED = '2026-11-05T03:02:05+00:00'; // 1 h 2 m 5 s later

function usage(over: Partial<TiingoUsage> = {}): TiingoUsage {
  return {
    requests_per_hour: { used: 12, limit: 50, nightly_stop_at: 50, window: 'rolling 1 h' },
    requests_per_day: { used: 340, limit: 1000, nightly_stop_at: 900, window: 'rolling 24 h' },
    symbols_per_month: { used: 120, limit: 500, nightly_stop_at: 475, window: 'rolling 31 d' },
    bytes_per_month: { used: 123_456_789, limit: 1_000_000_000, nightly_stop_at: 900_000_000, window: 'rolling 31 d' },
    ...over,
  };
}

function completed(over: Partial<IngestionStatus> = {}): IngestionStatus {
  return {
    status: 'completed',
    total: 1534,
    done: 1534,
    failed: 7,
    started_at: STARTED,
    finished_at: FINISHED,
    error: null,
    rebuild_refused: 2,
    single_provider_failed_symbols: ['AAA', 'BBB', 'CCC'],
    single_provider_updated: 4,
    suffix_only: 1400,
    adjustment_changed: 9,
    prefix_refetched: 31,
    prefix_rescaled: 8,
    prefix_confirmed: 11,
    confirm_retry: 1,
    lag_window_full: 5,
    single_provider_recent: 3,
    single_provider_skipped_current: 6,
    revalidated: 10,
    revalidation_skipped_budget: 0,
    tiingo_requests: 1234,
    tiingo_bytes: 45_600_000,
    tiingo_usage: usage(),
    tiingo_usage_error: null,
    ...over,
  };
}

/** The value cell of a labelled row in the last-run summary. */
function runValue(label: string): HTMLElement {
  const run = screen.getByRole('region', { name: 'Last ingestion run' });
  const term = within(run).getByText(label, { exact: true });
  const row = term.closest('[data-row]') as HTMLElement;
  return row.querySelector('[data-value]') as HTMLElement;
}

function meter(name: string): HTMLElement {
  return screen.getByRole('meter', { name });
}

describe('formatBytes (decimal units)', () => {
  test.each([
    [0, '0 B'],
    [999, '999 B'],
    [1000, '1 kB'],
    [1_500, '1.5 kB'],
    [1_000_000, '1 MB'],
    [123_456_789, '123.45 MB'],
    [999_999_999, '999.99 MB'],
    [1_000_000_000, '1 GB'],
    [900_000_000, '900 MB'],
    [2_345_000_000, '2.34 GB'],
  ])('%d -> %s', (bytes, text) => {
    expect(formatBytes(bytes)).toBe(text);
  });

  test('never rounds up past the true value', () => {
    // 999,999,999 B must not read as the 1 GB limit.
    expect(formatBytes(999_999_999)).not.toBe('1 GB');
    expect(formatBytes(1_999_999)).toBe('1.99 MB');
  });
});

describe('meterTone thresholds', () => {
  const e = (used: number) => ({ used, limit: 1000, nightly_stop_at: 900, window: 'rolling 24 h' });
  test('below the nightly stop is neutral', () => expect(meterTone(e(899))).toBe('neutral'));
  test('exactly at the nightly stop is caution', () => expect(meterTone(e(900))).toBe('caution'));
  test('between the stop and the limit is caution', () => expect(meterTone(e(999))).toBe('caution'));
  test('exactly at the limit is reject', () => expect(meterTone(e(1000))).toBe('reject'));
  test('above the limit is reject', () => expect(meterTone(e(1001))).toBe('reject'));
  test('no reserve: stop == limit, at the limit is reject, one below is neutral', () => {
    expect(meterTone({ used: 50, limit: 50, nightly_stop_at: 50, window: 'rolling 1 h' })).toBe('reject');
    expect(meterTone({ used: 49, limit: 50, nightly_stop_at: 50, window: 'rolling 1 h' })).toBe('neutral');
  });
});

describe('formatDuration', () => {
  test('hours, minutes, seconds', () => expect(formatDuration(STARTED, FINISHED)).toBe('1 h 2 m 5 s'));
  test('minutes and seconds', () => expect(formatDuration(STARTED, '2026-11-05T02:12:30+00:00')).toBe('12 m 30 s'));
  test('seconds only', () => expect(formatDuration(STARTED, '2026-11-05T02:00:45+00:00')).toBe('45 s'));
  test('missing end gives null', () => expect(formatDuration(STARTED, null)).toBeNull());
  test('missing start gives null', () => expect(formatDuration(null, FINISHED)).toBeNull());
  test('unparseable gives null', () => expect(formatDuration('nope', FINISHED)).toBeNull());
});

describe('TiingoBudget — full payload', () => {
  test('renders four meters with used / limit, window and nightly stop', () => {
    render(<TiingoBudget status={completed()} />);
    expect(screen.getAllByRole('meter')).toHaveLength(4);

    const hour = meter('Requests per hour');
    expect(hour).toHaveTextContent('12 / 50');
    expect(hour).toHaveTextContent('rolling 1 h');
    expect(hour).toHaveTextContent('nightly stop at 50');
    expect(hour).toHaveAttribute('aria-valuenow', '12');
    expect(hour).toHaveAttribute('aria-valuemax', '50');

    const day = meter('Requests per day');
    expect(day).toHaveTextContent('340 / 1,000');
    expect(day).toHaveTextContent('rolling 24 h');
    expect(day).toHaveTextContent('nightly stop at 900');

    const syms = meter('Distinct symbols per month');
    expect(syms).toHaveTextContent('120 / 500');
    expect(syms).toHaveTextContent('rolling 31 d');
    expect(syms).toHaveTextContent('nightly stop at 475');

    const bytes = meter('Response bytes per month');
    expect(bytes).toHaveTextContent('123.45 MB / 1 GB');
    expect(bytes).toHaveTextContent('rolling 31 d');
    expect(bytes).toHaveTextContent('nightly stop at 900 MB');

    for (const m of screen.getAllByRole('meter')) expect(m).toHaveAttribute('data-tone', 'neutral');
    expect(screen.queryByText(/limit reached/)).not.toBeInTheDocument();
    expect(screen.queryByText(/nightly reserve reached/)).not.toBeInTheDocument();
  });

  test('renders the last-run summary exactly as reported', () => {
    render(<TiingoBudget status={completed()} />);
    expect(runValue('Status')).toHaveTextContent('completed');
    expect(runValue('Started')).toHaveTextContent(new Date(STARTED).toLocaleString());
    expect(runValue('Duration')).toHaveTextContent('1 h 2 m 5 s');
    expect(runValue('Symbols')).toHaveTextContent('1,534 / 1,534');
    expect(runValue('Failed')).toHaveTextContent(/^7$/);
    expect(runValue('Rebuild refused')).toHaveTextContent(/^2$/);
    expect(runValue('Single-provider failures')).toHaveTextContent(/^3$/);
    expect(runValue('Tiingo requests')).toHaveTextContent('1,234');
    expect(runValue('Tiingo bytes')).toHaveTextContent('45.6 MB');
    expect(runValue('Rescaled')).toHaveTextContent(/^8$/);
    expect(runValue('Confirmed')).toHaveTextContent(/^11$/);
    expect(runValue('Lag-window full')).toHaveTextContent(/^5$/);
    expect(runValue('Suffix only')).toHaveTextContent('1,400');
    expect(runValue('Prefix refetched')).toHaveTextContent(/^31$/);
  });

  test('zero failures are shown as the reported 0, not hidden', () => {
    render(<TiingoBudget status={completed({ failed: 0, rebuild_refused: 0, single_provider_failed_symbols: [] })} />);
    expect(runValue('Failed')).toHaveTextContent(/^0$/);
    expect(runValue('Rebuild refused')).toHaveTextContent(/^0$/);
    expect(runValue('Single-provider failures')).toHaveTextContent(/^0$/);
  });
});

describe('TiingoBudget — tone boundaries', () => {
  test('used === nightly_stop_at is caution with the reserve message', () => {
    render(<TiingoBudget status={completed({ tiingo_usage: usage({
      requests_per_day: { used: 900, limit: 1000, nightly_stop_at: 900, window: 'rolling 24 h' },
    }) })} />);
    const day = meter('Requests per day');
    expect(day).toHaveAttribute('data-tone', 'caution');
    expect(day).toHaveTextContent('nightly reserve reached — the nightly run stops here');
    expect(day).not.toHaveTextContent('limit reached');
  });

  test('one below nightly_stop_at is neutral', () => {
    render(<TiingoBudget status={completed({ tiingo_usage: usage({
      requests_per_day: { used: 899, limit: 1000, nightly_stop_at: 900, window: 'rolling 24 h' },
    }) })} />);
    expect(meter('Requests per day')).toHaveAttribute('data-tone', 'neutral');
  });

  test('used === limit is reject with "limit reached"', () => {
    render(<TiingoBudget status={completed({ tiingo_usage: usage({
      bytes_per_month: { used: 1_000_000_000, limit: 1_000_000_000, nightly_stop_at: 900_000_000, window: 'rolling 31 d' },
    }) })} />);
    const bytes = meter('Response bytes per month');
    expect(bytes).toHaveAttribute('data-tone', 'reject');
    expect(bytes).toHaveTextContent('limit reached');
    expect(bytes).not.toHaveTextContent('nightly reserve reached');
  });

  test('one below the limit (above the stop) is caution', () => {
    render(<TiingoBudget status={completed({ tiingo_usage: usage({
      symbols_per_month: { used: 499, limit: 500, nightly_stop_at: 475, window: 'rolling 31 d' },
    }) })} />);
    expect(meter('Distinct symbols per month')).toHaveAttribute('data-tone', 'caution');
  });
});

describe('TiingoBudget — usage not available', () => {
  test('tiingo_usage null shows the backend error text and no meters', () => {
    render(<TiingoBudget status={completed({
      tiingo_usage: null,
      tiingo_usage_error: 'tiingo usage unavailable: connection refused',
    })} />);
    expect(screen.getByText('tiingo usage unavailable: connection refused')).toBeInTheDocument();
    expect(screen.queryAllByRole('meter')).toHaveLength(0);
  });

  test('older backend without the keys says usage is not reported, no meters, no 0', () => {
    const s = completed();
    delete s.tiingo_usage;
    delete s.tiingo_usage_error;
    render(<TiingoBudget status={s} />);
    expect(screen.getByText('Tiingo usage not reported by this backend')).toBeInTheDocument();
    expect(screen.queryAllByRole('meter')).toHaveLength(0);
    const budget = screen.getByRole('region', { name: 'Tiingo budget' });
    expect(budget).not.toHaveTextContent(/\b0\b/);
  });
});

describe('TiingoBudget — ledger counters', () => {
  test('null while running shows "counted at run end"', () => {
    render(<TiingoBudget status={completed({
      status: 'running', done: 200, failed: 1, finished_at: null,
      tiingo_requests: null, tiingo_bytes: null,
    })} />);
    expect(runValue('Status')).toHaveTextContent('running');
    expect(runValue('Symbols')).toHaveTextContent('200 / 1,534');
    expect(runValue('Tiingo requests')).toHaveTextContent('counted at run end');
    expect(runValue('Tiingo bytes')).toHaveTextContent('counted at run end');
    expect(screen.queryByText('Duration')).not.toBeInTheDocument();
  });

  test('null after completion shows "unknown (ledger missed an attempt)"', () => {
    render(<TiingoBudget status={completed({ tiingo_requests: null, tiingo_bytes: null })} />);
    expect(runValue('Tiingo requests')).toHaveTextContent('unknown (ledger missed an attempt)');
    expect(runValue('Tiingo bytes')).toHaveTextContent('unknown (ledger missed an attempt)');
    expect(runValue('Tiingo requests')).not.toHaveTextContent(/\d/);
  });

  test('counters absent (older backend) show "—", never 0', () => {
    const s = completed();
    for (const k of ['tiingo_requests', 'tiingo_bytes', 'prefix_rescaled', 'prefix_confirmed',
      'lag_window_full', 'suffix_only', 'prefix_refetched', 'rebuild_refused',
      'single_provider_failed_symbols'] as const) delete s[k];
    render(<TiingoBudget status={s} />);
    for (const label of ['Tiingo requests', 'Tiingo bytes', 'Rescaled', 'Confirmed', 'Lag-window full',
      'Suffix only', 'Prefix refetched', 'Rebuild refused', 'Single-provider failures']) {
      expect(runValue(label)).toHaveTextContent(/^—$/);
    }
  });
});

describe('TiingoBudget — run states', () => {
  test('idle with no started_at: no run since the backend started, no counts', () => {
    render(<TiingoBudget status={{
      status: 'idle', total: 0, done: 0, failed: 0, started_at: null, finished_at: null, error: null,
      rebuild_refused: 0, single_provider_failed_symbols: [], single_provider_updated: 0,
      tiingo_usage: usage(), tiingo_usage_error: null,
    }} />);
    const run = screen.getByRole('region', { name: 'Last ingestion run' });
    expect(within(run).getByText('No run since the backend started')).toBeInTheDocument();
    expect(run).not.toHaveTextContent(/\d/);
  });

  test('error run shows the error text and the reported counts', () => {
    render(<TiingoBudget status={completed({
      status: 'error', error: 'database is locked', done: 40, failed: 3,
    })} />);
    expect(runValue('Status')).toHaveTextContent('error');
    expect(screen.getByText('database is locked')).toBeInTheDocument();
    expect(runValue('Failed')).toHaveTextContent(/^3$/);
    expect(runValue('Symbols')).toHaveTextContent('40 / 1,534');
  });
});
