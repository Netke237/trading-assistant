import React from 'react';
import type { ScanReportMetadata } from '@/lib/scanReports';
import styles from './SavedScanReportInspector.module.css';

export function UnsavedReport({ update }: { update: ScanReportMetadata }) {
  const counts = Object.entries(update.pipeline_counts ?? {});
  return <div role="alert">
    <p>Current run {update.run_id}: report unsaved — persistence unavailable. Durable evidence below belongs to its own saved run.</p>
    <details key={update.run_id} className={styles.raw}>
      <summary>Unsaved current survivors and recorded counts</summary>
      <p>Recorded survivors: {update.accepted_symbols ? update.accepted_symbols.join(', ') || 'None recorded' : 'Unavailable'}</p>
      {counts.length ? <dl className={styles.metadata}>{counts.map(([key, value]) => <React.Fragment key={key}>
        <dt>{key.replace(/_/g, ' ')}</dt><dd>{typeof value === 'number' && Number.isFinite(value) ? value : 'Unavailable'}</dd>
      </React.Fragment>)}</dl> : <p>Recorded counts unavailable.</p>}
      <details className={styles.raw}><summary>Raw unsaved-run data</summary><pre>{JSON.stringify(update, null, 2)}</pre></details>
    </details>
  </div>;
}
