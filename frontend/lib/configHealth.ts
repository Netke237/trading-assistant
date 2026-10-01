// DOCC-5: the config-health report from DOCC-4's GET /api/config/health, and
// the ONE function that decides what the banner and the TopBar chip show.
//
// The gate for this slice is a FALSE GREEN (plan
// docs/superpowers/plans/2026-09-30-docc-5-topbar-banner-plan.md §6): the chip
// may read "Config OK" only for a parsed, self-consistent report with no
// findings, fetched less than MAX_REPORT_AGE_MS ago, in a tab that has not seen
// a second worker. So the parser refuses, never repairs (DOCC-3's precedent),
// and `tierOf` is the only place a tier is decided -- the banner and the chip
// both reach it through `useConfigHealthView()` in lib/configHealthStore.ts.
import { isPlainObject } from '@/lib/eventThresholdsStore';

export interface ConfigHealthError { file: string; path: string; message: string; blocks: string }
export interface ConfigHealthLine  { file: string; path: string; message: string }
export interface ConfigHealthReport {
  ok: boolean;
  checked: string[];
  not_checked: string[];
  pid: number;
  errors: ConfigHealthError[];
  warnings: ConfigHealthLine[];
  stale: ConfigHealthLine[];
}

export type HealthStatus = 'idle' | 'loading' | 'ready' | 'failed';
export type HealthTier =
  'checking' | 'clean' | 'warning' | 'multiworker' | 'unknown' | 'stale' | 'error';

/** Two 30 s poll intervals plus the 10 s fetch timeout. */
export const POLL_INTERVAL_MS = 30_000;
export const FETCH_TIMEOUT_MS = 10_000;
export const MAX_REPORT_AGE_MS = 70_000;
/** A proxy's HTML error page must not fill the headline. */
export const MAX_REASON_CHARS = 200;

function stringArray(raw: Record<string, unknown>, key: string): string[] {
  const v = raw[key];
  if (!Array.isArray(v)) throw new Error(`${key}: expected an array of strings`);
  v.forEach((s, i) => {
    if (typeof s !== 'string') throw new Error(`${key}[${i}]: expected a string`);
  });
  return [...v] as string[];
}

function lines<K extends string>(
  raw: Record<string, unknown>, key: string, fields: readonly K[],
): Record<K, string>[] {
  const v = raw[key];
  if (!Array.isArray(v)) throw new Error(`${key}: expected an array`);
  return v.map((entry, i) => {
    if (!isPlainObject(entry)) throw new Error(`${key}[${i}]: expected an object`);
    const out = {} as Record<K, string>;
    for (const f of fields) {
      if (!(f in entry)) throw new Error(`${key}[${i}].${f}: missing`);
      if (typeof entry[f] !== 'string') throw new Error(`${key}[${i}].${f}: expected a string`);
      out[f] = entry[f] as string;
    }
    return out;
  });
}

const REQUIRED = ['ok', 'checked', 'not_checked', 'pid', 'errors', 'warnings', 'stale'] as const;

/** Throws an Error naming the path, e.g. "errors[1].blocks: expected a string". */
export function parseConfigHealth(raw: unknown): ConfigHealthReport {
  if (!isPlainObject(raw)) throw new Error('config health: expected an object');
  for (const k of REQUIRED) {
    if (!(k in raw)) throw new Error(`${k}: missing`);
  }
  if (typeof raw.ok !== 'boolean') throw new Error('ok: expected a boolean');
  const pid = raw.pid;
  if (typeof pid !== 'number' || !Number.isSafeInteger(pid) || pid <= 0) {
    throw new Error('pid: expected a positive integer');
  }
  const report: ConfigHealthReport = {
    ok: raw.ok,
    checked: stringArray(raw, 'checked'),
    not_checked: stringArray(raw, 'not_checked'),
    pid,
    errors: lines(raw, 'errors', ['file', 'path', 'message', 'blocks'] as const),
    warnings: lines(raw, 'warnings', ['file', 'path', 'message'] as const),
    stale: lines(raw, 'stale', ['file', 'path', 'message'] as const),
  };
  const clean = report.errors.length === 0 && report.warnings.length === 0 && report.stale.length === 0;
  if (report.ok !== clean) throw new Error('ok: contradicts errors/warnings/stale');
  // A green must say what it checked; the backend's only empty `checked` is the crash shape (ok: false).
  if (report.ok && report.checked.length === 0) throw new Error('ok: true with nothing checked');
  return report;
}

export interface HealthView {
  status: HealthStatus;
  report: ConfigHealthReport | null;
  error: string | null;
  /** ms, of the report in hand. */
  fetchedAt: number | null;
  multiWorker: boolean;
  /** The store's clock -- never Date.now() at render. */
  now: number;
}

/** Why the tier is `unknown`, or null when it is not. */
export function unknownReason(view: HealthView): string | null {
  if (tierOf(view) !== 'unknown') return null;
  if (view.report === null) {
    const e = (view.error ?? '').trim();
    if (!e) return 'no details';
    return e.length > MAX_REASON_CHARS ? `${e.slice(0, MAX_REASON_CHARS)}…` : e;
  }
  return `last check is older than ${MAX_REPORT_AGE_MS / 1000} s`;
}

/** The only tier decision. First match wins (plan §2.1). */
export function tierOf(view: HealthView): HealthTier {
  const { status, report, error, fetchedAt, multiWorker, now } = view;
  // 1. Nothing has finished yet. A failure sets `error` and a poll that starts
  //    keeps it, so a retry after a failure stays `unknown` (round-1 G1).
  if (report === null && error === null && (status === 'idle' || status === 'loading')) return 'checking';
  // 2. The last fetch failed (the store clears the report on failure).
  if (report === null) return 'unknown';
  // 3. A frozen green in a throttled tab.
  if (fetchedAt === null || now - fetchedAt > MAX_REPORT_AGE_MS) return 'unknown';
  if (report.errors.length) return 'error';
  if (report.stale.length) return 'stale';
  if (multiWorker) return 'multiworker';
  if (report.warnings.length) return 'warning';
  return 'clean';
}

/** Changes whenever what the banner would say changes (collapse is keyed on it). */
export function fingerprintOf(view: HealthView): string {
  const tier = tierOf(view);
  if (tier === 'checking' || tier === 'clean') return '';
  if (tier === 'unknown') return 'unknown';
  const r = view.report!;
  const parts = [
    ...r.errors.map((e) => `error|${e.file}|${e.path}|${e.message}|${e.blocks}`),
    ...r.stale.map((e) => `stale|${e.file}|${e.path}|${e.message}`),
    ...r.warnings.map((e) => `warning|${e.file}|${e.path}|${e.message}`),
  ].sort();
  return [tier, `mw=${view.multiWorker}`, ...parts].join('\n');
}

export type HealthTone = 'reject' | 'caution' | 'pass' | 'dim';
export const TIER_TONE: Record<HealthTier, HealthTone> = {
  error: 'reject', stale: 'caution', unknown: 'caution', multiworker: 'caution',
  warning: 'caution', checking: 'dim', clean: 'pass',
};
export const TIER_SHORT_LABEL: Record<HealthTier, string> = {
  checking: 'Config: checking…',
  clean: 'Config OK',
  error: 'Config error',
  stale: 'Restart needed',
  unknown: 'Config unknown',
  multiworker: 'Several workers',
  warning: 'Config warning',
};

/** The banner's element id; the chip focuses it. */
export const CONFIG_HEALTH_BANNER_ID = 'config-health-banner';

export function hhmmss(ms: number): string {
  const d = new Date(ms);
  const p = (n: number) => String(n).padStart(2, '0');
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}
