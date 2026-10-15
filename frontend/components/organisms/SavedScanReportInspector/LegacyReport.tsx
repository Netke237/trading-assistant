import React from 'react';
import { SavedScanResultsTable } from '@/components/molecules/SavedScanResultsTable';
import styles from './SavedScanReportInspector.module.css';

function object(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : undefined;
}
function text(value: unknown): string {
  return typeof value === 'string' && value.trim() ? value : 'Unavailable';
}
function input(inputs: Record<string, unknown> | undefined, key: string): string {
  return inputs?.[`${key}_unavailable`] === true ? 'Unavailable' : text(inputs?.[key]);
}

export function LegacyReport({ entry }: { entry: Record<string, unknown> }) {
  const inputs = object(entry.inputs);
  const result = object(entry.result);
  const candidates = result?.candidates;
  const rows = Array.isArray(candidates) && candidates.every(row => object(row))
    ? candidates as Record<string, unknown>[] : undefined;
  const unavailablePaths = object(entry.unavailable_field_paths)?.result;
  const incomplete = result?.candidates_unavailable === true
    || (Array.isArray(unavailablePaths) && unavailablePaths.some(path => typeof path === 'string' && /^result(?:\.candidates(?:\[\d+\])?)?$/.test(path)))
    || (!Array.isArray(unavailablePaths) && Array.isArray(entry.unavailable_fields) && entry.unavailable_fields.includes('result'));
  return <details className={styles.legacy}>
    <summary>{text(entry.run_id)} · {text(entry.status)}</summary>
    <dl className={styles.metadata}>
      <dt>Started</dt><dd>{text(entry.started_at)}</dd>
      <dt>Last updated</dt><dd>{text(entry.ended_at)}</dd>
      <dt>Recorded direction</dt><dd>{input(inputs, 'direction')}</dd>
      <dt>Recorded horizon</dt><dd>{input(inputs, 'horizon')}</dd>
      <dt>Candidate records</dt><dd>{rows && !incomplete ? rows.length : 'Unavailable'}</dd>
    </dl>
    {rows && (!incomplete || rows.length > 0) && <SavedScanResultsTable category="legacy" rows={rows} />}
    {incomplete ? <p>Candidate records are incomplete; some legacy records are unavailable.</p>
      : !rows && <p>Candidate records unavailable in this legacy format.</p>}
    <details className={styles.raw}><summary>Raw data</summary><pre>{JSON.stringify(entry, null, 2)}</pre></details>
  </details>;
}
