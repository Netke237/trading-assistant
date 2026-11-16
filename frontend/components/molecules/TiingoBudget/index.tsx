/*
 * TiingoBudget — HISTORY-INCREMENTAL-NIGHTLY C1 (#572).
 *
 * Presentational: renders the Tiingo budget meters and the last ingestion run
 * from one GET /api/data/ingest/status payload. It fetches nothing; DataForm in
 * Settings -> Data does the fetch.
 *
 * Rules that hold throughout:
 *  - Only fields the endpoint returns are shown; nothing is derived or added.
 *    Failure counts are shown exactly as reported.
 *  - A missing (older backend / no run since restart) value shows "—"; a null
 *    Tiingo ledger counter says why it is null. Never 0 for a missing value.
 *  - Bytes use decimal units (1 kB = 1e3, 1 MB = 1e6, 1 GB = 1e9) and are
 *    truncated, never rounded up, so a value below a limit never reads as it.
 *
 * C1b (#643): the latest run recorded in storage (`last_run`) is shown only when
 * the live state has no run of this process (idle, started_at null), under its own
 * heading, never as live, never with the live status tone. A stored null ledger
 * counter is "unknown", never "counted at run end"; a stored `running` row was
 * never finalised and has no counters.
 */

import { Data, Text } from '@/components/primitives';
import type { IngestionRunSummary, IngestionStatus, TiingoUsageEntry, TiingoUsageKey } from '@/lib/api';
import styles from './TiingoBudget.module.css';

export type MeterTone = 'neutral' | 'caution' | 'reject';

const DASH = '—';

const METERS: { key: TiingoUsageKey; label: string; bytes: boolean }[] = [
  { key: 'requests_per_hour', label: 'Requests per hour', bytes: false },
  { key: 'requests_per_day', label: 'Requests per day', bytes: false },
  { key: 'symbols_per_month', label: 'Distinct symbols per month', bytes: false },
  { key: 'bytes_per_month', label: 'Response bytes per month', bytes: true },
];

const TONE_MESSAGE: Record<Exclude<MeterTone, 'neutral'>, string> = {
  reject: 'limit reached',
  caution: 'nightly reserve reached — the nightly run stops here',
};

const BYTE_UNITS: [number, string][] = [[1e9, 'GB'], [1e6, 'MB'], [1e3, 'kB']];

function isNum(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v);
}

function fmtInt(n: number): string {
  return n.toLocaleString('en-US');
}

/** Decimal-unit bytes, truncated to two decimals (integer arithmetic, no float rounding). */
export function formatBytes(bytes: number): string {
  const b = Math.trunc(bytes);
  for (const [unit, name] of BYTE_UNITS) {
    if (b >= unit) {
      const scaled = b * 100;
      const hundredths = (scaled - (scaled % unit)) / unit;
      const whole = Math.floor(hundredths / 100);
      const frac = hundredths % 100;
      const fracText = frac === 0 ? '' : `.${String(frac).padStart(2, '0').replace(/0$/, '')}`;
      return `${fmtInt(whole)}${fracText} ${name}`;
    }
  }
  return `${fmtInt(b)} B`;
}

/** used >= limit → reject; else used >= nightly_stop_at → caution; else neutral. */
export function meterTone(e: TiingoUsageEntry): MeterTone {
  if (e.used >= e.limit) return 'reject';
  if (e.used >= e.nightly_stop_at) return 'caution';
  return 'neutral';
}

/** Elapsed time between two ISO timestamps; null unless both parse and end >= start. */
export function formatDuration(start: string | null | undefined, end: string | null | undefined): string | null {
  if (!start || !end) return null;
  const a = Date.parse(start);
  const b = Date.parse(end);
  if (Number.isNaN(a) || Number.isNaN(b) || b < a) return null;
  const total = Math.round((b - a) / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h} h ${m} m ${s} s`;
  if (m > 0) return `${m} m ${s} s`;
  return `${s} s`;
}

function formatTime(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function validEntry(e: unknown): e is TiingoUsageEntry {
  const x = e as TiingoUsageEntry | null | undefined;
  return !!x && isNum(x.used) && isNum(x.limit) && isNum(x.nightly_stop_at) && typeof x.window === 'string';
}

function Meter({ label, entry, bytes }: { label: string; entry: TiingoUsageEntry; bytes: boolean }) {
  const fmt = bytes ? formatBytes : fmtInt;
  const tone = meterTone(entry);
  const fill = entry.limit > 0 ? Math.min(entry.used / entry.limit, 1) * 100 : 100;
  const stop = entry.limit > 0 && entry.nightly_stop_at < entry.limit
    ? (Math.max(entry.nightly_stop_at, 0) / entry.limit) * 100
    : null;
  return (
    <div
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={entry.limit}
      aria-valuenow={entry.used}
      aria-valuetext={`${fmt(entry.used)} of ${fmt(entry.limit)}`}
      data-tone={tone}
      className={[styles.meter, tone !== 'neutral' ? styles[tone] : null].filter(Boolean).join(' ')}
    >
      <div className={styles.meterHead}>
        <Text size={12} weight={400} tone="secondary">{label}</Text>
        <Data size={12} tone={tone === 'neutral' ? 'primary' : tone}>
          {fmt(entry.used)} / {fmt(entry.limit)}
        </Data>
      </div>
      <div className={styles.track}>
        <div className={styles.fill} style={{ width: `${fill}%` }} />
        {stop !== null && <div className={styles.stop} style={{ left: `${stop}%` }} />}
      </div>
      <Text size={11} tone="dim">
        {entry.window} · nightly stop at {fmt(entry.nightly_stop_at)}
      </Text>
      {tone !== 'neutral' && (
        <Text size={11} tone={tone}>{TONE_MESSAGE[tone]}</Text>
      )}
    </div>
  );
}

function Usage({ status }: { status: IngestionStatus }) {
  const usage = status.tiingo_usage;
  let body: React.ReactNode;
  if (usage === undefined) {
    body = <Text size={12} tone="dim">Tiingo usage not reported by this backend</Text>;
  } else if (usage === null) {
    body = <Text size={12} tone="caution">{status.tiingo_usage_error || 'Tiingo usage unavailable'}</Text>;
  } else {
    body = (
      <div className={styles.meters}>
        {METERS.map(({ key, label, bytes }) => {
          const entry = usage[key];
          return validEntry(entry)
            ? <Meter key={key} label={label} entry={entry} bytes={bytes} />
            : (
              <div key={key} className={styles.meter}>
                <Text size={12} weight={400} tone="secondary">{label}</Text>
                <Text size={11} tone="dim">not reported</Text>
              </div>
            );
        })}
      </div>
    );
  }
  return (
    <section aria-label="Tiingo budget" className={styles.section}>
      <Text as="p" size={12} weight={500}>Tiingo budget</Text>
      {body}
    </section>
  );
}

function RunRow({ label, children, tone }: {
  label: string; children: React.ReactNode; tone?: 'primary' | 'pass' | 'caution' | 'reject' | 'accent' | 'dim';
}) {
  return (
    <div className={styles.runRow} data-row>
      <Text size={12} weight={400} tone="secondary">{label}</Text>
      <span data-value data-tone={tone ?? 'primary'}><Data size={12} tone={tone ?? 'primary'}>{children}</Data></span>
    </div>
  );
}

const STATUS_TONE: Record<string, 'pass' | 'reject' | 'accent' | 'dim'> = {
  completed: 'pass', error: 'reject', running: 'accent', idle: 'dim',
};

function count(v: number | undefined | null): string {
  return isNum(v) ? fmtInt(v) : DASH;
}

function ledger(v: number | null | undefined, running: boolean, bytes: boolean): { text: string; tone?: 'dim' } {
  if (v === undefined) return { text: DASH };
  if (v === null || !isNum(v)) {
    return { text: running ? 'counted at run end' : 'unknown (ledger missed an attempt)', tone: 'dim' };
  }
  return { text: bytes ? formatBytes(v) : fmtInt(v) };
}

/** The per-run counter rows, read from the live state or from a stored summary. */
function RunCounters({ run, running }: { run: IngestionRunSummary; running: boolean }) {
  const failures = run.single_provider_failed_symbols;
  const requests = ledger(run.tiingo_requests, running, false);
  const size = ledger(run.tiingo_bytes, running, true);
  return (
    <>
      <RunRow label="Symbols">{count(run.done)} / {count(run.total)}</RunRow>
      <RunRow label="Failed">{count(run.failed)}</RunRow>
      <RunRow label="Rebuild refused">{count(run.rebuild_refused)}</RunRow>
      <RunRow label="Single-provider failures">{Array.isArray(failures) ? fmtInt(failures.length) : DASH}</RunRow>
      <RunRow label="Tiingo requests" tone={requests.tone}>{requests.text}</RunRow>
      <RunRow label="Tiingo bytes" tone={size.tone}>{size.text}</RunRow>
      <RunRow label="Rescaled">{count(run.prefix_rescaled)}</RunRow>
      <RunRow label="Confirmed">{count(run.prefix_confirmed)}</RunRow>
      <RunRow label="Lag-window full">{count(run.lag_window_full)}</RunRow>
      <RunRow label="Suffix only">{count(run.suffix_only)}</RunRow>
      <RunRow label="Prefix refetched">{count(run.prefix_refetched)}</RunRow>
    </>
  );
}

const STORED_HEADING = 'Latest run recorded in storage';
const STORED_NOTE = 'recorded before the last backend restart; a run whose record could not be written is not shown';
const NOT_FINALISED = 'Not finalised: no finish was recorded for this run (the backend stopped during it, '
  + 'or its final record could not be written); no counters were recorded';

/** The latest run recorded in storage — shown only when this process has no run yet. */
function StoredRun({ status }: { status: IngestionStatus }) {
  const run = status.last_run;
  let body: React.ReactNode;
  if (status.last_run_error) {
    body = <Text size={12} tone="caution">{status.last_run_error}</Text>;
  } else if (!run) {
    body = <Text size={12} tone="dim">No run recorded</Text>;
  } else if (run.status === 'running') {
    body = (
      <>
        <Text as="p" size={12} tone="secondary">{NOT_FINALISED}</Text>
        <div className={styles.runGrid}>
          <RunRow label="Started">{formatTime(run.started_at)}</RunRow>
        </div>
      </>
    );
  } else {
    const summary: IngestionRunSummary = run.summary ?? {};
    const duration = run.finished_at ? formatDuration(run.started_at, run.finished_at) : null;
    body = (
      <>
        {run.status === 'error' && (
          <Text as="p" size={12} tone="secondary">{summary.error || 'Run failed (no error text reported)'}</Text>
        )}
        <div className={styles.runGrid}>
          <RunRow label="Status">{run.status}</RunRow>
          <RunRow label="Started">{formatTime(run.started_at)}</RunRow>
          <RunRow label="Finished">{formatTime(run.finished_at)}</RunRow>
          {duration !== null && <RunRow label="Duration">{duration}</RunRow>}
          <RunCounters run={summary} running={false} />
        </div>
      </>
    );
  }
  return (
    <section aria-label={STORED_HEADING} className={styles.section}>
      <Text as="p" size={12} weight={500}>{STORED_HEADING}</Text>
      <Text as="p" size={11} tone="dim">{STORED_NOTE}</Text>
      {body}
    </section>
  );
}

function LastRun({ status }: { status: IngestionStatus }) {
  const noRun = status.status === 'idle' && !status.started_at;
  // No run of this process: a backend that reports last_run shows the stored run instead.
  if (noRun && (status.last_run !== undefined || !!status.last_run_error)) {
    return <StoredRun status={status} />;
  }
  const running = status.status === 'running';
  const duration = status.finished_at ? formatDuration(status.started_at, status.finished_at) : null;
  return (
    <section aria-label="Last ingestion run" className={styles.section}>
      <Text as="p" size={12} weight={500}>Last ingestion run</Text>
      <Text as="p" size={11} tone="dim">The nightly run and a manual “Run now” share this summary; it shows whichever ran last.</Text>
      {noRun ? (
        <Text size={12} tone="dim">No run since the backend started</Text>
      ) : (
        <>
          {status.status === 'error' && (
            <Text as="p" size={12} tone="reject">{status.error || 'Run failed (no error text reported)'}</Text>
          )}
          <div className={styles.runGrid}>
            <RunRow label="Status" tone={STATUS_TONE[status.status] ?? 'primary'}>{status.status ?? DASH}</RunRow>
            <RunRow label="Started">{formatTime(status.started_at)}</RunRow>
            {duration !== null && <RunRow label="Duration">{duration}</RunRow>}
            <RunCounters run={status} running={running} />
          </div>
        </>
      )}
    </section>
  );
}

export function TiingoBudget({ status }: { status: IngestionStatus }) {
  return (
    <div className={styles.root}>
      <Usage status={status} />
      <LastRun status={status} />
    </div>
  );
}
