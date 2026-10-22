import React from 'react';
import styles from './SavedScanReportInspector.module.css';

export function SavedExclusions({ rows }: { rows: unknown[] }) {
  return <details>
    <summary>Saved exclusions</summary>
    {rows.length === 0 ? <p>No exclusions recorded.</p> : <div className={styles.tableScroll}><table className={styles.recordsTable}>
      <thead><tr><th scope="col">Symbol</th><th scope="col">Recorded reason</th><th scope="col">Recorded details</th></tr></thead>
      <tbody>{rows.map((value, index) => {
        const row = value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
        const symbol = row.symbol_unavailable !== true && typeof row.symbol === 'string' && row.symbol.trim() ? row.symbol : 'Unavailable';
        const reason = row.reason_unavailable !== true && typeof row.reason === 'string' && row.reason.trim() ? row.reason : 'Unavailable';
        return <tr key={index}><th scope="row">{symbol}</th><td>{reason}</td><td><details><summary>Raw record</summary><pre>{JSON.stringify(value, null, 2)}</pre></details></td></tr>;
      })}</tbody>
    </table></div>}
  </details>;
}
