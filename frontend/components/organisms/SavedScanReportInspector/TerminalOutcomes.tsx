'use client';
import React, { useState } from 'react';
import type { ScanReportCategory, TerminalOutcomeKind, TerminalOutcomes as TerminalOutcomesData, TerminalOutcomeValue } from '@/lib/scanReports';
import styles from './SavedScanReportInspector.module.css';

// Only the setup scans record terminal outcomes (scan_report_lifecycle.run_reported_scan
// sets terminal_enabled for exactly these categories).
export const TERMINAL_OUTCOME_CATEGORIES: readonly ScanReportCategory[] = ['prebreakout', 'pullback', 'fib'];

const OUTCOME_LABELS: Record<TerminalOutcomeKind, string> = {
    accepted: 'Accepted',
    excluded: 'Excluded by scan policy',
    no_data: 'No data',
    error: 'Data/processing error',
    no_setup: 'No setup returned',
    filtered: 'Filtered by a rule',
};
// Human-readable text for each finite backend code (scan_report_lifecycle._TERMINAL_CODES).
// A generic no-setup code never names a rule: the engine does not report which one failed.
const REASONS: Record<string, string> = {
    candidate_returned: 'Returned as a candidate',
    scan_policy: 'Excluded by scan policy before evaluation',
    missing_history: 'No price history returned',
    insufficient_history: 'Insufficient daily price history',
    missing_price: 'No current price available',
    insufficient_intraday_history: 'Insufficient intraday (15-min) history',
    regime_data_unavailable: 'Regime data unavailable',
    trend_unmeasured: 'Trend not measured, so direction conviction could not be checked',
    history_fetch_failed: 'Price history fetch failed',
    signal_processing_failed: 'Setup signal computation failed',
    regime_fetch_failed: 'Intraday regime data fetch failed',
    data_processing_failed: 'Data processing failed',
    unsupported_strategy: 'Unsupported strategy',
    setup_not_returned: 'No setup returned; individual failed rules not reported',
    fib_level_not_returned: 'No setup returned; individual failed rules not reported',
    ema_side: 'Close on the wrong side of the EMA trend filter',
    price_min: 'Price below the minimum price',
    price_max: 'Price above the maximum price',
    score_status: 'Stock score status REJECT',
    score_min: 'Stock score below the minimum score',
    direction_conviction: 'Trend score below the direction-conviction floor',
    regime_headwind: 'Regime headwind filter',
    backtest_gate: 'Backtest gate not passed',
    confidence_gate: 'Confidence below the reject threshold',
    shortlist_cap: 'Cut by the shortlist cap',
};
// Units verified against the backend producers; values are shown exactly as recorded
// (no rounding, inversion or rescaling). Keys without a verified unit show the raw value.
const dollars = (v: number) => `$${v}`;
const percent = (v: number) => `${v}%`;
const scale = (v: number) => `${v} (0–100 scale)`;
const fraction = (v: number) => `${v} (fraction 0–1)`;
const UNITS: Record<string, (v: number) => string> = {
    current_close: dollars, ema_value: dollars, price: dollars, min_price: dollars, max_price: dollars,
    ema_period: v => `${v} bars`,
    score: scale, min_stock_score: scale, trend_score: scale, min_trend: scale,
    confidence: percent, confidence_reject_below: percent,
    win_rate: fraction, min_win_rate: fraction,
    n_trades: v => `${v} trades`, min_trades: v => `${v} trades`,
    cap: v => `${v} candidates`, original_count: v => `${v} candidates`,
};
function formatValue(key: string, value: TerminalOutcomeValue): string {
    if (typeof value === 'boolean')
        return value ? 'yes' : 'no';
    if (typeof value === 'number' && UNITS[key])
        return UNITS[key](value);
    return String(value);
}
function isTerminalOutcomes(value: unknown): value is TerminalOutcomesData {
    if (!value || typeof value !== 'object')
        return false;
    const v = value as Partial<TerminalOutcomesData>;
    return !!v.counts && typeof v.counts === 'object' && Array.isArray(v.outcomes) && Array.isArray(v.unknown_symbols) && Array.isArray(v.input_symbols);
}
function Values({ values }: { values?: Record<string, TerminalOutcomeValue> }) {
    const entries = Object.entries(values ?? {});
    if (!entries.length)
        return <>none recorded</>;
    return <ul className={styles.values}>{entries.map(([k, v]) => <li key={k}>{k}: {formatValue(k, v)}</li>)}</ul>;
}
interface Props {
    value: unknown;
    runId: string;
    tableRunId?: string | null;
    sameCategory: boolean;
}
export function TerminalOutcomes({ value, runId, tableRunId, sameCategory }: Props) {
    const [query, setQuery] = useState('');
    if (!isTerminalOutcomes(value))
        return <p>Terminal outcome diagnostics unavailable for this run.</p>;
    const { counts, outcomes, unknown_symbols: unknown } = value;
    const recorded = counts.accepted + counts.excluded + counts.no_data + counts.error_count + counts.no_setup + counts.filtered;
    const total = recorded + unknown.length;
    const items: Array<[string, number | null]> = [
        ['Input symbols', counts.input], ['Evaluated symbols', counts.evaluated],
        [OUTCOME_LABELS.accepted, counts.accepted], [OUTCOME_LABELS.excluded, counts.excluded],
        [OUTCOME_LABELS.no_data, counts.no_data], [OUTCOME_LABELS.error, counts.error_count],
        [OUTCOME_LABELS.no_setup, counts.no_setup], [OUTCOME_LABELS.filtered, counts.filtered],
        ['Unknown (no outcome recorded)', unknown.length],
    ];
    const matches = sameCategory && !!tableRunId && tableRunId === runId;
    const tableNote = !sameCategory ? 'the table shows another category' : tableRunId ? `table run ${tableRunId}` : 'no table run identified';
    const needle = query.trim().toUpperCase();
    const rows = [
        ...outcomes.map(o => ({ symbol: o.symbol, outcome: OUTCOME_LABELS[o.terminal] ?? o.terminal, reason: REASONS[o.code] ?? o.code, observations: o.observations, thresholds: o.thresholds })),
        ...unknown.map(symbol => ({ symbol, outcome: 'Unknown', reason: 'No terminal outcome recorded for this symbol', observations: undefined, thresholds: undefined })),
    ].filter(r => !needle || r.symbol.toUpperCase().includes(needle));
    return <section className={styles.terminal} aria-label="Terminal outcomes">
  <h4>Terminal outcomes</h4>
  <p>{matches ? `Breakdown for saved run ${runId} matches the displayed table run.` : `Snapshot: this breakdown belongs to saved run ${runId}, not to the rows shown (${tableNote}).`}</p>
  {!value.complete && <p><strong>Partial diagnostics</strong> — the run was interrupted, cancelled or failed, some symbols have no recorded outcome, or the evaluated symbols do not match the input stage. Symbols without a final outcome are counted as unknown.</p>}
  {value.diagnostic_unavailable && <p>Conflicting records were dropped for some symbols; those symbols are counted as unknown.</p>}
  {!value.resolution_available && <p>Symbol resolution unavailable: input and evaluated counts are unavailable.</p>}
  <ul className={styles.counts} aria-label="Terminal outcome counts">{items.map(([label, n]) => <li key={label}><span>{label}</span> <strong>{n == null ? 'unavailable' : n}</strong></li>)}</ul>
  <p>Each input symbol is counted once: it has exactly one terminal outcome, or it is unknown. The category counts plus unknown therefore add up to the input count. A recorded reason is the step that ended that symbol&apos;s evaluation; later rules were not evaluated for it, so reasons are not per-rule failure counts and must not be summed as rule rejections.</p>
  <p>{counts.input == null ? `Category counts plus unknown: ${total}; input count unavailable.` : `Category counts plus unknown: ${total} of ${counts.input} input symbols.`}{counts.input != null && total !== counts.input && ' Counts do not reconcile with the input count; treat this breakdown as partial.'}</p>
  <label>Search symbol <input type="search" aria-label="Search symbol outcomes" value={query} onChange={e => setQuery(e.target.value)}/></label>
  <table>
   <caption>Per-symbol terminal outcomes (saved run {runId})</caption>
   <thead><tr><th>Symbol</th><th>Outcome</th><th>Recorded reason</th><th>Observations</th><th>Thresholds</th></tr></thead>
   <tbody>{rows.map(r => <tr key={`${r.outcome}:${r.symbol}`}><td>{r.symbol}</td><td>{r.outcome}</td><td>{r.reason}</td><td><Values values={r.observations}/></td><td><Values values={r.thresholds}/></td></tr>)}</tbody>
  </table>
  {needle && rows.length === 0 && <p>No recorded outcome matches “{query.trim()}”.</p>}
 </section>;
}
